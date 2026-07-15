"""Compute daily analysis features from scraped data.

Produces a JSON-serializable dict of metrics for a given date,
comparing against trailing windows (7d, 30d, 90d).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select, and_

from repower.db import (
    AnalysisRecord,
    DemandSupply30m,
    FuelDaily,
    JepxSpot30m,
    NewsItem,
    get_session,
    init_db,
)
from repower.timeutil import yesterday_jst

logger = logging.getLogger(__name__)


def _query_demand_supply(session, start: date, end: date, area: str) -> pd.DataFrame:
    # The table holds all 9 TSO areas; demand/mix stats are per-area figures, so
    # an unfiltered query would mash unrelated areas' 30-min rows together.
    stmt = select(DemandSupply30m).where(
        and_(
            DemandSupply30m.area == area,
            DemandSupply30m.date >= start,
            DemandSupply30m.date <= end,
        )
    )
    rows = session.execute(stmt).scalars().all()
    if not rows:
        return pd.DataFrame()
    data = [{c.name: getattr(r, c.name) for c in DemandSupply30m.__table__.columns} for r in rows]
    return pd.DataFrame(data)


def _query_jepx(session, start: date, end: date) -> pd.DataFrame:
    stmt = select(JepxSpot30m).where(
        and_(JepxSpot30m.date >= start, JepxSpot30m.date <= end)
    )
    rows = session.execute(stmt).scalars().all()
    if not rows:
        return pd.DataFrame()
    data = [{c.name: getattr(r, c.name) for c in JepxSpot30m.__table__.columns} for r in rows]
    return pd.DataFrame(data)


def _query_fuels(session, start: date, end: date) -> pd.DataFrame:
    stmt = select(FuelDaily).where(
        and_(FuelDaily.date >= start, FuelDaily.date <= end)
    )
    rows = session.execute(stmt).scalars().all()
    if not rows:
        return pd.DataFrame()
    data = [{c.name: getattr(r, c.name) for c in FuelDaily.__table__.columns} for r in rows]
    return pd.DataFrame(data)


def _safe_pct(value, reference) -> float | None:
    if pd.isna(value) or pd.isna(reference) or not reference:
        return None
    return round((value - reference) / abs(reference) * 100, 2)


def compute_features(target_date: date, db_path: str | None = None, area: str = "tepco") -> dict[str, Any]:
    """Compute analysis features for a single date. Returns a dict.

    Demand/supply metrics are computed for one TSO ``area`` (default Tokyo);
    the JEPX section is always the Tokyo area price, matching the digest's
    "Tokyo Power Market" framing.
    """
    init_db(db_path)
    session = get_session(db_path)

    try:
        # Date windows
        d7 = target_date - timedelta(days=7)
        d30 = target_date - timedelta(days=30)

        # ── Demand/Supply for target date ──────────────────────────────────
        ds_today = _query_demand_supply(session, target_date, target_date, area)
        ds_30d = _query_demand_supply(session, d30, target_date - timedelta(days=1), area)

        features: dict[str, Any] = {"date": target_date.isoformat(), "area": area}

        # Rows can exist with every numeric value NULL (e.g. a TSO column shift
        # that parsed dates but no figures) — idxmax/idxmin raise on all-NaN, so
        # treat that the same as no rows at all.
        if ds_today.empty or not ds_today["area_demand_mw"].notna().any():
            features["demand"] = {"status": "no_data"}
        else:
            demand = ds_today["area_demand_mw"]
            features["demand"] = {
                "peak_mw": int(demand.max()),
                "min_mw": int(demand.min()),
                "avg_mw": int(demand.mean()),
                "peak_time": ds_today.loc[demand.idxmax(), "time"],
            }

            # Generation mix (% of total supply)
            gen_cols = ["nuclear", "lng", "coal", "oil", "thermal_other",
                        "hydro", "geothermal", "biomass", "solar_actual",
                        "wind_actual", "pumped", "battery", "interconnect", "other"]
            total = ds_today["total_supply"].sum()
            if total > 0:
                mix = {}
                for col in gen_cols:
                    val = ds_today[col].sum()
                    mix[col] = round(val / total * 100, 2)
                features["generation_mix_pct"] = mix

                # Renewable share
                re_cols = ["hydro", "geothermal", "biomass", "solar_actual", "wind_actual"]
                features["renewable_share_pct"] = round(
                    sum(ds_today[c].sum() for c in re_cols) / total * 100, 2
                )

            # Compare to 30d trailing average
            if not ds_30d.empty:
                trailing_avg = ds_30d["area_demand_mw"].mean()
                features["demand"]["vs_30d_avg_pct"] = _safe_pct(demand.mean(), trailing_avg)

        # ── JEPX spot prices ──────────────────────────────────────────────
        jepx_today = _query_jepx(session, target_date, target_date)
        jepx_30d = _query_jepx(session, d30, target_date - timedelta(days=1))

        if jepx_today.empty or not jepx_today["tokyo_area_price"].notna().any():
            features["jepx"] = {"status": "no_data"}
        else:
            price = jepx_today["tokyo_area_price"]
            features["jepx"] = {
                "avg_yen_kwh": round(float(price.mean()), 2),
                "max_yen_kwh": round(float(price.max()), 2),
                "min_yen_kwh": round(float(price.min()), 2),
                "peak_time": jepx_today.loc[price.idxmax(), "time"],
            }
            if not jepx_30d.empty:
                trailing_avg = jepx_30d["tokyo_area_price"].mean()
                features["jepx"]["vs_30d_avg_pct"] = _safe_pct(price.mean(), trailing_avg)

                # Percentile of today's avg within last 30 days of daily averages
                daily_avgs = jepx_30d.groupby("date")["tokyo_area_price"].mean()
                pctile = (daily_avgs < price.mean()).sum() / len(daily_avgs) * 100
                features["jepx"]["percentile_30d"] = round(pctile, 1)

        # ── Fuel prices (latest available) ────────────────────────────────
        fuels_df = _query_fuels(session, d7, target_date)
        if not fuels_df.empty:
            fuel_latest = {}
            for ticker in fuels_df["ticker"].unique():
                ticker_data = fuels_df[fuels_df["ticker"] == ticker].sort_values("date")
                if not ticker_data.empty:
                    last = ticker_data.iloc[-1]
                    fuel_latest[ticker] = {
                        "close": round(float(last["close"]), 2),
                        "date": str(last["date"]),
                        "currency": last["currency"],
                    }
            features["fuels"] = fuel_latest

        # ── News count ─────────────────────────────────────────────────────
        news_stmt = select(NewsItem).where(
            and_(
                NewsItem.published_at >= target_date.isoformat(),
                NewsItem.published_at < (target_date + timedelta(days=1)).isoformat(),
            )
        )
        news_items = session.execute(news_stmt).scalars().all()
        features["news_count"] = len(news_items)
        features["news_headlines"] = [n.title for n in news_items[:5]]

        return features
    finally:
        session.close()


def save_features(target_date: date, features: dict, db_path: str | None = None) -> None:
    """Persist computed features to the analyses table."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        existing = session.query(AnalysisRecord).filter_by(date=target_date).first()
        if existing:
            existing.features_json = json.dumps(features, ensure_ascii=False)
        else:
            record = AnalysisRecord(
                date=target_date,
                features_json=json.dumps(features, ensure_ascii=False),
            )
            session.add(record)
        session.commit()
    finally:
        session.close()


def run_analysis(
    target_date: date | None = None, db_path: str | None = None, area: str = "tepco"
) -> dict[str, Any]:
    """Compute and persist features for a date (default: yesterday)."""
    if target_date is None:
        target_date = yesterday_jst()

    features = compute_features(target_date, db_path, area=area)
    save_features(target_date, features, db_path)
    logger.info("Analysis for %s: %d keys", target_date, len(features))
    return features
