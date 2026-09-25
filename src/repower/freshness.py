"""Data freshness: how far each market-data source lags JST today.

Scrapers fail soft, so an upstream break shows up as "0 rows" in a green run. The
daily cron runs ``repower check-freshness`` last, turning a silent outage red.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import func, select

from repower.config import EPRX_BALANCING_PARQUET, EPRX_TIELINE_PARQUET
from repower.db import DemandSupply30m, FuelDaily, JepxAreaPrice30m, JepxSpot30m, get_session, init_db
from repower.scrapers.areas import AREA_NAMES
from repower.timeutil import today_jst

# Days a source may lag before it counts as stale. JEPX and EPRX publish daily; fuel
# closes skip weekends and holidays. TSO supply is judged twice: the newest area must
# stay current (a scraper-wide break), while each area alone gets a long leash, since
# some publish monthly (Tohoku was ~6 weeks behind the rest in September 2026).
LIMITS = {
    "JEPX system price": 3,
    "JEPX area prices": 3,
    "EPRX balancing": 5,
    "EPRX tieline": 5,
    "Fuels & FX": 6,
    "Supply (newest area)": 5,
}
AREA_LIMIT = 60


def _parquet_latest(path) -> date | None:
    try:
        latest = pd.read_parquet(path, columns=["date"])["date"].max()
    except FileNotFoundError:
        return None
    return None if pd.isna(latest) else date.fromisoformat(str(latest)[:10])


def source_ages(db_path: str | None = None, today: date | None = None) -> list[dict]:
    """``{"source", "latest", "age", "limit", "stale"}`` per source; missing data is stale."""
    today = today or today_jst()
    init_db(db_path)
    session = get_session(db_path)
    try:
        supplied = DemandSupply30m.area_demand_mw.is_not(None)
        latest = {
            "JEPX system price": session.scalar(
                select(func.max(JepxSpot30m.date)).where(JepxSpot30m.system_price.is_not(None))),
            "JEPX area prices": session.scalar(
                select(func.max(JepxAreaPrice30m.date)).where(JepxAreaPrice30m.price.is_not(None))),
            "Fuels & FX": session.scalar(select(func.max(FuelDaily.date))),
            "Supply (newest area)": session.scalar(select(func.max(DemandSupply30m.date)).where(supplied)),
        }
        per_area = dict(session.execute(
            select(DemandSupply30m.area, func.max(DemandSupply30m.date)).where(supplied)
            .group_by(DemandSupply30m.area)
        ).all())
    finally:
        session.close()
    latest["EPRX balancing"] = _parquet_latest(EPRX_BALANCING_PARQUET)
    latest["EPRX tieline"] = _parquet_latest(EPRX_TIELINE_PARQUET)

    limits = dict(LIMITS)
    for area in AREA_NAMES:
        latest[f"Supply ({area})"] = per_area.get(area)
        limits[f"Supply ({area})"] = AREA_LIMIT

    rows = []
    for source, limit in limits.items():
        d = latest.get(source)
        age = max(0, (today - d).days) if d else None
        rows.append({"source": source, "latest": d, "age": age, "limit": limit,
                     "stale": age is None or age > limit})
    return rows
