"""Scrape JEPX day-ahead spot market prices (30-minute granularity).

Source: https://www.jepx.jp/market/excel/spot_YYYY.csv
Column layout (as of 2026):
  0  年月日 (date)
  1  時刻コード (period 1-48)
  5  システムプライス (system price, yen/kWh)
  8  エリアプライス東京 (Tokyo area price, yen/kWh)
Encoding: cp932.
"""

from __future__ import annotations

import io
import logging

import httpx
import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from repower.db import JepxAreaPrice30m, JepxSpot30m, get_session, init_db
from repower.scrapers.http_cache import conditional_get, invalidate
from repower.timeutil import today_jst

logger = logging.getLogger(__name__)


# Map area slug → Japanese keyword used in the JEPX CSV header column name.
JEPX_AREA_KEYWORDS: dict[str, str] = {
    "hokkaido": "エリアプライス北海道",
    "tohoku":   "エリアプライス東北",
    "tepco":    "エリアプライス東京",
    "chubu":    "エリアプライス中部",
    "hokuriku": "エリアプライス北陸",
    "kansai":   "エリアプライス関西",
    "chugoku":  "エリアプライス中国",
    "shikoku":  "エリアプライス四国",
    "kyushu":   "エリアプライス九州",
}


def _csv_url(year: int) -> str:
    # jepx.org redirects to jepx.jp homepage; use jepx.jp directly
    return f"https://www.jepx.jp/market/excel/spot_{year}.csv"


def parse_jepx_csv(content: bytes) -> pd.DataFrame:
    """Parse the raw bytes of one year's JEPX spot CSV (cp932) into a long-format
    DataFrame: ``date, time, system_price, tokyo_area_price`` plus one column per
    area slug in JEPX_AREA_KEYWORDS (e.g. ``hokkaido_price``). Pure, no network."""
    # cp932 encoding confirmed for jepx.jp CSVs
    text_data = content.decode("cp932")

    df = pd.read_csv(io.StringIO(text_data), header=0)
    cols = df.columns.tolist()

    def _find_col(keyword: str, fallback: int | None = None) -> str | None:
        for i, c in enumerate(cols):
            if keyword in str(c):
                return cols[i]
        if fallback is None:
            return None
        return cols[fallback] if fallback < len(cols) else cols[0]

    date_col = cols[0]
    period_col = cols[1]
    system_col = _find_col("システムプライス", 5)

    result = pd.DataFrame()
    result["date_raw"] = df[date_col].astype(str)
    result["period"] = pd.to_numeric(df[period_col], errors="coerce")
    result["system_price"] = pd.to_numeric(df[system_col], errors="coerce")

    # Pull every area price column we can find, by Japanese keyword.
    for slug, kw in JEPX_AREA_KEYWORDS.items():
        col = _find_col(kw)
        if col is not None and col in df.columns:
            result[f"{slug}_price"] = pd.to_numeric(df[col], errors="coerce")
        else:
            result[f"{slug}_price"] = pd.NA

    # Backwards-compat: keep the legacy "tokyo_area_price" alias.
    result["tokyo_area_price"] = result["tepco_price"]

    # Convert date — format may be YYYY/MM/DD or YYYY-MM-DD
    result["date"] = pd.to_datetime(result["date_raw"], format="mixed", dayfirst=False).dt.date

    # Convert period (1-48) to time string HH:MM
    def period_to_time(p) -> str:
        if pd.isna(p) or p < 1:
            return "00:00"
        p = int(p)
        minutes = (p - 1) * 30
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    result["time"] = result["period"].apply(period_to_time)
    result = result.dropna(subset=["date"])

    keep = ["date", "time", "system_price", "tokyo_area_price"] + [
        f"{slug}_price" for slug in JEPX_AREA_KEYWORDS
    ]
    return result[keep]


def fetch_jepx_csv(year: int, db_path: str | None = None) -> pd.DataFrame | None:
    """Download one year's JEPX spot CSV via the conditional-GET cache and parse it.

    Returns the parsed DataFrame, or ``None`` if the file is unchanged since the
    last run (304) or missing (404) — the caller then skips the upsert. The
    current-year file changes daily so it is re-fetched; past years 304-skip.
    """
    url = _csv_url(year)
    status, content = conditional_get(url, db_path=db_path, timeout=60)
    if status != "ok" or content is None:
        logger.info("JEPX %d: %s (%s) — skipping", year, status, url)
        return None
    logger.info("JEPX %d: fetched %s", year, url)
    try:
        return parse_jepx_csv(content)
    except Exception:
        # Unusable 200 body — drop the cache entry so the next run re-fetches.
        invalidate(url, db_path=db_path)
        raise


def upsert_jepx(df: pd.DataFrame, db_path: str | None = None) -> int:
    """Upsert JEPX spot data into both legacy and per-area tables.

    Returns the number of (date, time) rows processed (legacy table count).
    """
    init_db(db_path)
    session = get_session(db_path)
    rows_affected = 0

    try:
        for _, row in df.iterrows():
            # Legacy wide table — system + tokyo only
            stmt = sqlite_upsert(JepxSpot30m).values(
                date=row["date"],
                time=row["time"],
                system_price=None if pd.isna(row["system_price"]) else float(row["system_price"]),
                tokyo_area_price=None if pd.isna(row["tokyo_area_price"]) else float(row["tokyo_area_price"]),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "time"],
                set_={
                    "system_price": stmt.excluded.system_price,
                    "tokyo_area_price": stmt.excluded.tokyo_area_price,
                },
            )
            session.execute(stmt)
            rows_affected += 1

            # New long table — one row per area
            for slug in JEPX_AREA_KEYWORDS:
                price = row.get(f"{slug}_price")
                if price is None or pd.isna(price):
                    continue
                a_stmt = sqlite_upsert(JepxAreaPrice30m).values(
                    area=slug,
                    date=row["date"],
                    time=row["time"],
                    price=float(price),
                )
                a_stmt = a_stmt.on_conflict_do_update(
                    index_elements=["area", "date", "time"],
                    set_={"price": a_stmt.excluded.price},
                )
                session.execute(a_stmt)

        session.commit()
    finally:
        session.close()

    return rows_affected


def scrape_jepx(year: int | None = None, db_path: str | None = None) -> int:
    """Scrape JEPX for the given year (default: current year). Returns rows upserted."""
    if year is None:
        year = today_jst().year

    try:
        df = fetch_jepx_csv(year, db_path)
        if df is None:  # 304 unchanged or 404 — nothing to upsert
            return 0
        n = upsert_jepx(df, db_path)
        logger.info("JEPX %d: upserted %d rows", year, n)
        return n
    except httpx.HTTPStatusError as e:
        logger.warning("JEPX %d: HTTP %s", year, e.response.status_code)
        return 0
    except Exception as e:
        logger.error("JEPX %d: %s", year, e)
        return 0


def scrape_jepx_years(start_year: int, end_year: int | None = None,
                      db_path: str | None = None) -> dict[int, int]:
    """Backfill multiple JEPX years (inclusive). Returns ``{year: rows}``."""
    if end_year is None:
        end_year = today_jst().year
    out: dict[int, int] = {}
    for y in range(start_year, end_year + 1):
        out[y] = scrape_jepx(y, db_path)
    return out
