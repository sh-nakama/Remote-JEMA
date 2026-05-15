"""Scrape TEPCO area supply/demand 30-minute CSV data.

Source: https://www.tepco.co.jp/forecast/html/area_jukyu-j.html
CSV URL pattern: https://www.tepco.co.jp/forecast/html/images/eria_jukyu_{YYYYMM}_03.csv
Encoding: UTF-8 (with BOM on some months)
Row 1: units header (skip)
Row 2: column names in Japanese
Row 3+: data
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime

import httpx
import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from repower.config import TEPCO_BASE_URL
from repower.db import DemandSupply30m, get_session, init_db

logger = logging.getLogger(__name__)

# Canonical column order after DATE and TIME
SUPPLY_COLUMNS = [
    "area_demand_mw",
    "nuclear",
    "lng",
    "coal",
    "oil",
    "thermal_other",
    "hydro",
    "geothermal",
    "biomass",
    "solar_actual",
    "solar_curtail",
    "wind_actual",
    "wind_curtail",
    "pumped",
    "battery",
    "interconnect",
    "other",
    "total_supply",
]

ALL_COLUMNS = ["date", "time"] + SUPPLY_COLUMNS


def _csv_url(year: int, month: int) -> str:
    return f"{TEPCO_BASE_URL}/eria_jukyu_{year}{month:02d}_03.csv"


def fetch_csv(year: int, month: int) -> pd.DataFrame:
    """Download and parse one month's TEPCO area CSV into a DataFrame."""
    url = _csv_url(year, month)
    logger.info("Fetching %s", url)

    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()

    # Detect BOM and decode
    raw = resp.content
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    text_data = raw.decode("utf-8")

    # Skip the first header row (units), use second row as header
    df = pd.read_csv(
        io.StringIO(text_data),
        skiprows=1,
        header=0,
        encoding="utf-8",
    )

    # Rename columns positionally — the Japanese headers vary slightly
    if len(df.columns) >= 20:
        df.columns = ALL_COLUMNS
    else:
        raise ValueError(f"Unexpected column count: {len(df.columns)} for {url}")

    # Parse date
    df["date"] = pd.to_datetime(df["date"], format="%Y/%m/%d").dt.date

    # Numeric coercion
    for col in SUPPLY_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def upsert_dataframe(df: pd.DataFrame, db_path: str | None = None) -> int:
    """Upsert a DataFrame of TEPCO rows into the database. Returns rows affected."""
    init_db(db_path)
    session = get_session(db_path)
    rows_affected = 0

    try:
        for _, row in df.iterrows():
            stmt = sqlite_upsert(DemandSupply30m).values(
                date=row["date"],
                time=row["time"],
                area_demand_mw=row["area_demand_mw"],
                nuclear=row["nuclear"],
                lng=row["lng"],
                coal=row["coal"],
                oil=row["oil"],
                thermal_other=row["thermal_other"],
                hydro=row["hydro"],
                geothermal=row["geothermal"],
                biomass=row["biomass"],
                solar_actual=row["solar_actual"],
                solar_curtail=row["solar_curtail"],
                wind_actual=row["wind_actual"],
                wind_curtail=row["wind_curtail"],
                pumped=row["pumped"],
                battery=row["battery"],
                interconnect=row["interconnect"],
                other=row["other"],
                total_supply=row["total_supply"],
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "time"],
                set_={col: stmt.excluded[col] for col in SUPPLY_COLUMNS},
            )
            session.execute(stmt)
            rows_affected += 1

        session.commit()
    finally:
        session.close()

    return rows_affected


def scrape_tepco(months_back: int = 1, db_path: str | None = None) -> int:
    """Scrape TEPCO via the unified BaseAreaScraper framework.

    Kept as a thin shim so legacy callers (CLI, tests) continue to work.
    For multi-area pipelines prefer ``scrape_all_areas`` from
    ``repower.scrapers.areas``.
    """
    from repower.scrapers.areas import TepcoScraper
    return TepcoScraper().scrape(months_back=months_back, db_path=db_path)


def _legacy_scrape_tepco(months_back: int = 1, db_path: str | None = None) -> int:
    today = date.today()
    total = 0

    targets: list[tuple[int, int]] = []
    for offset in range(months_back + 1):
        m = today.month - offset
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        targets.append((y, m))

    for year, month in targets:
        try:
            df = fetch_csv(year, month)
            n = upsert_dataframe(df, db_path)
            logger.info("TEPCO %04d-%02d: upserted %d rows", year, month, n)
            total += n
        except httpx.HTTPStatusError as e:
            logger.warning("TEPCO %04d-%02d: HTTP %s", year, month, e.response.status_code)
        except Exception as e:
            logger.error("TEPCO %04d-%02d: %s", year, month, e)

    return total
