"""Data loaders salvaged from the old single-page dashboard.

Only the helpers still consumed by :mod:`repower.dashboard.app_main`
(Drivers / Analyses views) remain here.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import and_, select

from repower.db import (
    AnalysisRecord,
    FuelDaily,
    JepxAreaPrice30m,
    JepxSpot30m,
    get_session,
    init_db,
)


# ── Data loaders (cached per DB session) ──────────────────────────────────

@st.cache_resource
def _db_session():
    init_db()
    return get_session()


def _jepx(start: date, end: date) -> pd.DataFrame:
    session = _db_session()
    rows = session.execute(
        select(JepxSpot30m).where(
            and_(JepxSpot30m.date >= start, JepxSpot30m.date <= end)
        )
    ).scalars().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in JepxSpot30m.__table__.columns} for r in rows]
    )
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"])
    df = df.sort_values(["datetime", "id"]).drop_duplicates("datetime", keep="last")
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def _jepx_area(area: str, start: date, end: date) -> pd.DataFrame:
    """Per-area JEPX spot price. Falls back to legacy ``tokyo_area_price`` if the
    new ``jepx_area_price_30m`` table is empty (older HF DB snapshots).

    Returns a DataFrame with columns ``date, time, price, datetime``.
    """
    session = _db_session()
    rows = session.execute(
        select(JepxAreaPrice30m).where(
            and_(
                JepxAreaPrice30m.area == area,
                JepxAreaPrice30m.date >= start,
                JepxAreaPrice30m.date <= end,
            )
        )
    ).scalars().all()
    if rows:
        df = pd.DataFrame(
            [{c.name: getattr(r, c.name) for c in JepxAreaPrice30m.__table__.columns} for r in rows]
        )[["area", "date", "time", "price"]]
    else:
        # Legacy fallback: only Tokyo lives in the wide table.
        legacy = _jepx(start, end)
        if legacy.empty or area != "tepco":
            return pd.DataFrame()
        df = legacy[["date", "time", "tokyo_area_price"]].rename(
            columns={"tokyo_area_price": "price"}
        )
    rollover = df["time"].astype(str).str.strip() == "24:00"
    if rollover.any():
        df.loc[rollover, "date"] = pd.to_datetime(df.loc[rollover, "date"]) + pd.Timedelta(days=1)
        df.loc[rollover, "date"] = df.loc[rollover, "date"].dt.date
        df.loc[rollover, "time"] = "00:00"
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"])
    df = df.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)
    return df


def _fuels(start: date, end: date) -> pd.DataFrame:
    session = _db_session()
    rows = session.execute(
        select(FuelDaily).where(
            and_(FuelDaily.date >= start, FuelDaily.date <= end)
        )
    ).scalars().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in FuelDaily.__table__.columns} for r in rows]
    )
    df = df.sort_values(["date", "ticker", "id"]).drop_duplicates(["date", "ticker"], keep="last")
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def _analyses() -> pd.DataFrame:
    session = _db_session()
    rows = session.query(AnalysisRecord).order_by(AnalysisRecord.date.desc()).limit(30).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in AnalysisRecord.__table__.columns} for r in rows]
    )
