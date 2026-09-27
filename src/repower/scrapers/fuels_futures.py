"""Scrape fuel/commodity prices via yfinance (daily close).

Tickers:
- JKM=F — Platts JKM LNG futures (USD/MMBtu)
- BZ=F  — Brent crude futures (USD/bbl)
- NG=F  — Henry Hub natural gas futures (USD/MMBtu)
- JPY=X — USD/JPY exchange rate

No Newcastle coal series is available on yfinance.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from repower.db import FuelDaily, get_session, init_db

logger = logging.getLogger(__name__)

TICKERS = {
    "JKM=F": "USD",  # Platts JKM LNG
    "BZ=F": "USD",   # Brent crude
    "NG=F": "USD",   # Henry Hub gas
    "JPY=X": "JPY",  # USD/JPY
}

# A ticker whose stored history starts later than this many days ago is fetched back that
# far, so a new (or short-lived) series fills the driver charts (up to 1Y) at once.
BACKFILL_DAYS = 800
# A trading series never starts exactly on the cut-off, so allow its first close this late.
_BACKFILL_SLACK_DAYS = 30


def fetch_fuels(days_back: int = 7, backfill: frozenset[str] = frozenset()) -> list[dict]:
    """Fetch daily closes for every ticker; those in *backfill* go back BACKFILL_DAYS."""
    end = date.today()

    rows: list[dict] = []
    for ticker, currency in TICKERS.items():
        span = BACKFILL_DAYS if ticker in backfill else days_back
        start = end - timedelta(days=span + 5)  # extra buffer for weekends
        try:
            data = yf.download(
                ticker,
                start=start.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=True,
            )
            if data.empty:
                logger.warning("No data for %s", ticker)
                continue

            for idx, row in data.iterrows():
                if "Close" not in row.index:
                    continue
                val = row["Close"]
                close_val = float(val.iloc[0]) if hasattr(val, "iloc") else float(val)
                if math.isnan(close_val):
                    continue
                rows.append({
                    "date": idx.date(),
                    "ticker": ticker,
                    "close": close_val,
                    "currency": currency,
                })
        except Exception as e:
            logger.error("yfinance %s: %s", ticker, e)

    return rows


def upsert_fuels(rows: list[dict], db_path: str | None = None) -> int:
    """Upsert fuel price rows. Returns rows affected."""
    if not rows:
        return 0

    init_db(db_path)
    session = get_session(db_path)
    affected = 0

    try:
        for row in rows:
            stmt = sqlite_upsert(FuelDaily).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "ticker"],
                set_={"close": stmt.excluded.close, "currency": stmt.excluded.currency},
            )
            session.execute(stmt)
            affected += 1
        session.commit()
    finally:
        session.close()

    return affected


def tickers_to_backfill(db_path: str | None = None, today: date | None = None) -> frozenset[str]:
    """TICKERS whose stored history starts later than the back-fill window (or is empty)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        first = dict(
            session.execute(select(FuelDaily.ticker, func.min(FuelDaily.date)).group_by(FuelDaily.ticker)).all()
        )
    finally:
        session.close()
    cutoff = (today or date.today()) - timedelta(days=BACKFILL_DAYS - _BACKFILL_SLACK_DAYS)
    return frozenset(t for t in TICKERS if first.get(t) is None or first[t] > cutoff)


def scrape_fuels(days_back: int = 7, db_path: str | None = None) -> int:
    """Scrape and store fuel prices. Returns rows upserted."""
    backfill = tickers_to_backfill(db_path)
    if backfill:
        logger.info("Fuels: back-filling %d days for %s", BACKFILL_DAYS, sorted(backfill))
    rows = fetch_fuels(days_back, backfill)
    n = upsert_fuels(rows, db_path)
    logger.info("Fuels: upserted %d rows", n)
    return n
