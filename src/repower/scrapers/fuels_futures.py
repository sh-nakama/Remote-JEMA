"""Scrape fuel/commodity prices via yfinance (daily close).

Tickers:
- BZ=F  — Brent crude futures (USD/bbl)
- NG=F  — Henry Hub natural gas (USD proxy for JKM direction)
- NWC=F — Newcastle coal (if available), fallback to manual
- JPY=X — USD/JPY exchange rate
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from repower.db import FuelDaily, get_session, init_db

logger = logging.getLogger(__name__)

TICKERS = {
    "BZ=F": "USD",   # Brent crude
    "NG=F": "USD",   # Henry Hub NG (JKM proxy direction)
    "JPY=X": "JPY",  # USD/JPY
}


def fetch_fuels(days_back: int = 7) -> list[dict]:
    """Fetch daily close prices for energy commodities. Returns list of row dicts."""
    end = date.today()
    start = end - timedelta(days=days_back + 5)  # extra buffer for weekends

    rows: list[dict] = []
    for ticker, currency in TICKERS.items():
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


def scrape_fuels(days_back: int = 7, db_path: str | None = None) -> int:
    """Scrape and store fuel prices. Returns rows upserted."""
    rows = fetch_fuels(days_back)
    n = upsert_fuels(rows, db_path)
    logger.info("Fuels: upserted %d rows", n)
    return n
