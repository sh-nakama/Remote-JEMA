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
from datetime import date

import httpx
import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from repower.config import JEPX_BASE_URL
from repower.db import JepxSpot30m, get_session, init_db

logger = logging.getLogger(__name__)


def _csv_url(year: int) -> str:
    # jepx.org redirects to jepx.jp homepage; use jepx.jp directly
    return f"https://www.jepx.jp/market/excel/spot_{year}.csv"


def fetch_jepx_csv(year: int) -> pd.DataFrame:
    """Download and parse one year's JEPX spot CSV."""
    url = _csv_url(year)
    logger.info("Fetching %s", url)

    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()

    # cp932 encoding confirmed for jepx.jp CSVs
    text_data = resp.content.decode("cp932")

    df = pd.read_csv(io.StringIO(text_data), header=0)
    cols = df.columns.tolist()

    # Fixed indices for the 2026 jepx.jp format:
    #   0=date, 1=period, 5=system price, 8=Tokyo area price
    # Search by keyword first so this is resilient to minor layout changes.
    def _find_col(keyword: str, fallback: int) -> str:
        for i, c in enumerate(cols):
            if keyword in str(c):
                return cols[i]
        return cols[fallback]

    date_col = cols[0]
    period_col = cols[1]
    system_col = _find_col("システムプライス", 5)
    tokyo_col = _find_col("エリアプライス東京", 8)

    result = pd.DataFrame()
    result["date_raw"] = df[date_col].astype(str)
    result["period"] = pd.to_numeric(df[period_col], errors="coerce")
    result["system_price"] = pd.to_numeric(df[system_col], errors="coerce")
    result["tokyo_area_price"] = pd.to_numeric(df[tokyo_col], errors="coerce")

    # Convert date — format may be YYYY/MM/DD or YYYY-MM-DD
    result["date"] = pd.to_datetime(result["date_raw"], format="mixed", dayfirst=False).dt.date

    # Convert period (1-48) to time string HH:MM
    def period_to_time(p: int) -> str:
        if pd.isna(p) or p < 1:
            return "00:00"
        p = int(p)
        minutes = (p - 1) * 30
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    result["time"] = result["period"].apply(period_to_time)
    result = result.dropna(subset=["date", "system_price"])

    return result[["date", "time", "system_price", "tokyo_area_price"]]


def upsert_jepx(df: pd.DataFrame, db_path: str | None = None) -> int:
    """Upsert JEPX spot data. Returns rows affected."""
    init_db(db_path)
    session = get_session(db_path)
    rows_affected = 0

    try:
        for _, row in df.iterrows():
            stmt = sqlite_upsert(JepxSpot30m).values(
                date=row["date"],
                time=row["time"],
                system_price=row["system_price"],
                tokyo_area_price=row["tokyo_area_price"],
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

        session.commit()
    finally:
        session.close()

    return rows_affected


def scrape_jepx(year: int | None = None, db_path: str | None = None) -> int:
    """Scrape JEPX for the given year (default: current year). Returns rows upserted."""
    if year is None:
        year = date.today().year

    try:
        df = fetch_jepx_csv(year)
        n = upsert_jepx(df, db_path)
        logger.info("JEPX %d: upserted %d rows", year, n)
        return n
    except httpx.HTTPStatusError as e:
        logger.warning("JEPX %d: HTTP %s", year, e.response.status_code)
        return 0
    except Exception as e:
        logger.error("JEPX %d: %s", year, e)
        return 0
