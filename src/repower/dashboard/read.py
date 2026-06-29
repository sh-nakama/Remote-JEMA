"""Read / aggregation layer for the dashboard.

Pure helpers (``aggregate``, reducer inference) are uncached and unit-testable.
The ``load_*`` functions hit the DB, pivot long→wide, and run ``aggregate``;
they are wrapped with ``@st.cache_data`` and take a trailing cache-buster int
to mirror the legacy loader patterns.

Output frames always carry a ``datetime`` column equal to the bucket start
(the original datetime for ``Native``), so the D3 components — which parse
``new Date(d.datetime)`` — render aggregated buckets through the same code.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Mapping

import pandas as pd
import streamlit as st
from sqlalchemy import and_, select

from repower.db import (
    DemandSupply30m,
    EprxBalancing,
    EprxTieline,
    JepxAreaPrice30m,
    get_session,
    init_db,
)
from sqlalchemy import func


# ── Reducer inference ──────────────────────────────────────────────────────
# Authoritative per-column reducers (plan §B):
#   MW flows (demand, generation mix, contracted, bid volume) -> mean
#   avg price (wholesale `price`, balancing `price_avg`)       -> mean
#   price_max / price_min                                      -> max / min
#   counts (bids_count, contracted_count)                      -> mean
#   tieline upper_limit_* -> max ; reserved_* -> mean

# Generation-mix / supply columns from DemandSupply30m.
MIX_COLUMNS: list[str] = [
    "nuclear", "lng", "coal", "oil", "thermal_other",
    "hydro", "geothermal", "biomass", "solar_actual", "wind_actual",
    "pumped", "battery", "interconnect", "other", "total_supply",
]

# Balancing metric columns produced by load_balancing_grid (pre-derive).
BALANCING_VOLUME_COLUMNS: list[str] = [
    "demand_mw", "bid_volume_mw", "contracted_mw",
    "bids_count", "contracted_count",
]
BALANCING_PRICE_COLUMNS: list[str] = ["price_max", "price_avg", "price_min"]

# Tieline metric columns produced by load_tieline.
TIELINE_LIMIT_COLUMNS: list[str] = ["upper_limit_fwd", "upper_limit_rev"]
TIELINE_RESERVED_COLUMNS: list[str] = ["reserved_fwd", "reserved_rev"]


def default_reducer_for(col: str) -> str:
    """Infer a pandas-groupby reducer name for *col* from the plan §B table.

    Falls back to ``mean`` for unknown columns (MW-flow default).
    """
    c = col.lower()
    # price_max / price_min are special-cased before the generic "price" rule.
    if c == "price_max" or c.endswith("_max"):
        return "max"
    if c == "price_min" or c.endswith("_min"):
        return "min"
    # Tieline limits -> max ; reserved -> mean.
    if c.startswith("upper_limit"):
        return "max"
    if c.startswith("reserved"):
        return "mean"
    # avg price, counts, MW flows, generation mix -> mean.
    return "mean"


def build_reducer_map(columns) -> dict[str, str]:
    """Build a {column -> reducer} map from inferred defaults for *columns*.

    ``datetime``/``date``/``time`` and other non-numeric keys are skipped.
    """
    skip = {"datetime", "date", "time", "area", "pair", "market",
            "product", "product_code", "block_num", "blocks_per_day", "id"}
    return {c: default_reducer_for(c) for c in columns if c not in skip}


# ── Bucketing helpers ──────────────────────────────────────────────────────

def _bucket_start(dt: pd.Series, level: str) -> pd.Series:
    """Map a datetime series to its bucket-start datetime for *level*."""
    dt = pd.to_datetime(dt)
    if level == "Daily":
        return dt.dt.normalize()
    if level == "Weekly":
        # ISO-week start (Monday 00:00).
        return dt.dt.to_period("W").dt.start_time
    if level == "Monthly":
        return dt.dt.to_period("M").dt.start_time
    raise ValueError(f"Unknown aggregation level: {level!r}")


# ── Core aggregation (pure, uncached, unit-testable) ───────────────────────

def aggregate(
    df: pd.DataFrame,
    level: str,
    reducers: Mapping[str, str | Callable] | None = None,
    group_extra: list[str] | None = None,
) -> pd.DataFrame:
    """Aggregate a tidy, datetime-keyed frame to *level*.

    Parameters
    ----------
    df
        Frame with a ``datetime`` column (and optionally value columns).
    level
        One of ``Native`` / ``Daily`` / ``Weekly`` / ``Monthly``.
        ``Native`` returns *df* unchanged (still keyed on its datetime).
    reducers
        Explicit ``{column: func}`` mapping (func is a pandas reducer name or
        callable). Columns absent from the map fall back to an inferred default
        from the column name (plan §B).
    group_extra
        Extra grouping keys carried through aggregation (e.g. ``["area"]`` or
        ``["pair"]``) so per-series rows stay separate.

    Returns a tidy frame whose ``datetime`` column is the bucket start.
    """
    if level == "Native":
        return df
    if level not in ("Daily", "Weekly", "Monthly"):
        raise ValueError(f"Unknown aggregation level: {level!r}")
    if df.empty:
        return df

    reducers = dict(reducers or {})
    group_extra = list(group_extra or [])

    work = df.copy()
    work["datetime"] = _bucket_start(work["datetime"], level)

    value_cols = [
        c for c in work.columns
        if c not in ("datetime", *group_extra)
    ]

    agg_spec: dict[str, str | Callable] = {}
    for c in value_cols:
        func = reducers.get(c)
        if func is None:
            func = default_reducer_for(c)
        agg_spec[c] = func

    # Drop non-numeric carry-through columns that have no usable reducer
    # (e.g. stray "date"/"time" strings). Keep only columns we can aggregate.
    keep_cols = []
    for c in value_cols:
        if c in ("date", "time"):
            continue
        keep_cols.append(c)
    agg_spec = {c: agg_spec[c] for c in keep_cols}

    group_keys = ["datetime", *group_extra]
    out = (
        work.groupby(group_keys, as_index=False)
        .agg(agg_spec)
    )
    return out.sort_values(group_keys).reset_index(drop=True)


# ── DB session (cached like legacy) ────────────────────────────────────────

@st.cache_resource
def _db_session():
    init_db()
    return get_session()


def _rollover_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the '24:00' end-of-day rollover and build a ``datetime`` column.

    Ported from legacy.py: rows reported at 24:00 roll over to next-day 00:00.
    """
    rollover = df["time"].astype(str).str.strip() == "24:00"
    if rollover.any():
        df.loc[rollover, "date"] = (
            pd.to_datetime(df.loc[rollover, "date"]) + pd.Timedelta(days=1)
        )
        df.loc[rollover, "date"] = df.loc[rollover, "date"].dt.date
        df.loc[rollover, "time"] = "00:00"
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    return df


# ── Wholesale (JEPX + supply) ──────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_wholesale_grid(
    area: str,
    start: date,
    end: date,
    level: str = "Daily",
    _cache_buster: int = 0,
) -> dict[str, list[dict]]:
    """Area demand + generation mix (left) and JEPX area price (right).

    Returns ``{"supply": [...records...], "price": [...records...]}`` where each
    record list is aggregated to *level* and carries a ``datetime`` column.
    """
    session = _db_session()

    # ── Supply: demand + generation mix ──
    ds_rows = session.execute(
        select(DemandSupply30m).where(
            and_(
                DemandSupply30m.area == area,
                DemandSupply30m.date >= start,
                DemandSupply30m.date <= end,
            )
        )
    ).scalars().all()
    if ds_rows:
        supply = pd.DataFrame(
            [{c.name: getattr(r, c.name) for c in DemandSupply30m.__table__.columns}
             for r in ds_rows]
        )
        supply = _rollover_datetime(supply)
        supply = (
            supply.sort_values(["datetime", "id"])
            .drop_duplicates("datetime", keep="last")
            .sort_values("datetime")
            .reset_index(drop=True)
        )
        keep = ["datetime", "area_demand_mw", *MIX_COLUMNS]
        keep = [c for c in keep if c in supply.columns]
        supply = supply[keep]
        supply = aggregate(supply, level, build_reducer_map(supply.columns))
    else:
        supply = pd.DataFrame()

    # ── Price: JEPX per-area ──
    price_rows = session.execute(
        select(JepxAreaPrice30m).where(
            and_(
                JepxAreaPrice30m.area == area,
                JepxAreaPrice30m.date >= start,
                JepxAreaPrice30m.date <= end,
            )
        )
    ).scalars().all()
    if price_rows:
        price = pd.DataFrame(
            [{c.name: getattr(r, c.name) for c in JepxAreaPrice30m.__table__.columns}
             for r in price_rows]
        )[["date", "time", "price"]]
        price = _rollover_datetime(price)
        price = (
            price.sort_values("datetime")
            .drop_duplicates("datetime", keep="last")
            .reset_index(drop=True)
        )
        # Reuse price_chart's max/avg/min band for wholesale too: derive three
        # series from the single JEPX price. At Native granularity there is one
        # price per slot, so the three collapse to a single line.
        price = price[["datetime", "price"]].copy()
        price["price_avg"] = price["price"]
        price["price_max"] = price["price"]
        price["price_min"] = price["price"]
        price = price[["datetime", "price_avg", "price_max", "price_min"]]
        price = aggregate(
            price, level,
            {"price_avg": "mean", "price_max": "max", "price_min": "min"},
        )
    else:
        price = pd.DataFrame()

    return {
        "supply": _records(supply),
        "price": _records(price),
    }


# ── Balancing (EPRX) ───────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_balancing_grid(
    product: str,
    area: str,
    start: date,
    end: date,
    level: str = "Daily",
    _cache_buster: int = 0,
) -> dict[str, list[dict]]:
    """EPRX balancing volume (left) + clearing price (right) for product/area.

    ``missing_mw`` is derived **after** aggregation as agg(demand) - agg(contracted).
    Returns ``{"volume": [...], "price": [...]}``.
    """
    session = _db_session()
    rows = session.execute(
        select(EprxBalancing).where(
            and_(
                EprxBalancing.product == product,
                EprxBalancing.area == area,
                EprxBalancing.date >= start,
                EprxBalancing.date <= end,
            )
        )
    ).scalars().all()
    if not rows:
        return {"volume": [], "price": []}

    long_df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in EprxBalancing.__table__.columns}
         for r in rows]
    )
    long_df = _rollover_datetime(long_df)

    wide = long_df.pivot_table(
        index="datetime",
        columns="metric",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # ── Volume side: demand / bid / contracted / counts -> aggregate, then derive missing_mw ──
    vol_cols = [c for c in (["datetime"] + BALANCING_VOLUME_COLUMNS) if c in wide.columns]
    volume = wide[vol_cols].copy()
    volume = aggregate(volume, level, build_reducer_map(volume.columns))
    if "demand_mw" in volume.columns and "contracted_mw" in volume.columns:
        volume["missing_mw"] = volume["demand_mw"] - volume["contracted_mw"]

    # ── Price side: max / avg / min ──
    price_cols = [c for c in (["datetime"] + BALANCING_PRICE_COLUMNS) if c in wide.columns]
    price = wide[price_cols].copy()
    price = aggregate(price, level, build_reducer_map(price.columns))

    return {
        "volume": _records(volume),
        "price": _records(price),
    }


# ── Tieline (interconnector) ───────────────────────────────────────────────

# Mapping of old (pre-March-14-2026) pairs to combined-zone pairs.
# Old pairs are summed per block to produce the merged series.
# Ported from Reference/dashboard_hh/data_loader.py (_OLD_TO_NEW_ZONE).
_OLD_TO_NEW_ZONE: dict[str, list[str]] = {
    "Chubu-Hokuriku → Kansai": ["Hokuriku → Kansai", "Chubu → Kansai"],
    "Chubu-Kansai → Hokuriku": ["Chubu → Hokuriku"],
    # "Chubu → Hokuriku-Kansai" has no old equivalent — data starts Mar 14.
}

_TIELINE_METRIC_COLUMNS: list[str] = [
    "upper_limit_fwd", "upper_limit_rev", "reserved_fwd", "reserved_rev",
]


def _merge_combined_zones(wide: pd.DataFrame) -> pd.DataFrame:
    """Replace pre-March-14 individual pairs with combined-zone equivalents.

    Old constituent pairs are summed per block (datetime). Post-March-14 rows
    already use the new names and are kept unchanged. Ported from the reference
    loader's ``_merge_combined_zones``.
    """
    if wide.empty:
        return wide

    metric_cols = [c for c in wide.columns if c in _TIELINE_METRIC_COLUMNS]

    all_old_pairs: set[str] = set()
    for old_list in _OLD_TO_NEW_ZONE.values():
        all_old_pairs.update(old_list)

    keep = wide[~wide["pair"].isin(all_old_pairs)]

    merged_parts = []
    for new_name, old_names in _OLD_TO_NEW_ZONE.items():
        old_rows = wide[wide["pair"].isin(old_names)]
        if old_rows.empty:
            continue
        agg = old_rows.groupby("datetime", as_index=False)[metric_cols].sum()
        agg["pair"] = new_name
        merged_parts.append(agg)

    if merged_parts:
        result = pd.concat([keep] + merged_parts, ignore_index=True)
    else:
        result = keep

    return result.sort_values(["datetime", "pair"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_tieline(
    market: str,
    start: date,
    end: date,
    level: str = "Daily",
    _cache_buster: int = 0,
) -> list[dict]:
    """EPRX tieline per interconnector pair, aggregated to *level*.

    Pivots metric->columns, applies the Mar-14 combined-zone merge on read,
    then aggregates per pair. Returns a list of records (one per pair/bucket).
    """
    session = _db_session()
    rows = session.execute(
        select(EprxTieline).where(
            and_(
                EprxTieline.market == market,
                EprxTieline.date >= start,
                EprxTieline.date <= end,
            )
        )
    ).scalars().all()
    if not rows:
        return []

    long_df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in EprxTieline.__table__.columns}
         for r in rows]
    )
    long_df = _rollover_datetime(long_df)

    wide = long_df.pivot_table(
        index=["datetime", "pair"],
        columns="metric",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # Mar-14 combined-zone merge on read (raw stays lossless).
    wide = _merge_combined_zones(wide)

    # Aggregate per pair (limits -> max, reserved -> mean via inference).
    reducers = build_reducer_map(wide.columns)
    agg = aggregate(wide, level, reducers, group_extra=["pair"])
    return _records(agg)


# ── Period-comparison stats (pure, uncached, unit-testable) ─────────────────
# These query the raw 30-min / block rows directly over a date window and reduce
# with plain means / max — independent of the aggregation-level radio. They take
# an optional db_path so they can run against a temporary test database.


def _mean(value) -> float | None:
    """Coerce a SQL aggregate (possibly None) to a float or None."""
    return float(value) if value is not None else None


def wholesale_period_stats(
    area: str,
    start: date,
    end: date,
    db_path: str | None = None,
) -> dict[str, float | None]:
    """Mean wholesale stats for *area* over ``[start, end]`` (inclusive).

    Computed over the raw 30-min rows in the window — NOT the aggregation level.

    Returns ``{"avg_demand_mw", "peak_demand_mw", "avg_price"}`` where each value
    is a float, or ``None`` if no rows contributed to that metric.

    * ``avg_demand_mw``  — mean of ``DemandSupply30m.area_demand_mw``
    * ``peak_demand_mw`` — max of ``DemandSupply30m.area_demand_mw``
    * ``avg_price``      — mean of ``JepxAreaPrice30m.price`` (¥/kWh)
    """
    session = get_session(db_path)
    try:
        demand_row = session.execute(
            select(
                func.avg(DemandSupply30m.area_demand_mw),
                func.max(DemandSupply30m.area_demand_mw),
            ).where(
                and_(
                    DemandSupply30m.area == area,
                    DemandSupply30m.date >= start,
                    DemandSupply30m.date <= end,
                )
            )
        ).one()
        price_row = session.execute(
            select(func.avg(JepxAreaPrice30m.price)).where(
                and_(
                    JepxAreaPrice30m.area == area,
                    JepxAreaPrice30m.date >= start,
                    JepxAreaPrice30m.date <= end,
                )
            )
        ).one()
    finally:
        session.close()

    return {
        "avg_demand_mw": _mean(demand_row[0]),
        "peak_demand_mw": _mean(demand_row[1]),
        "avg_price": _mean(price_row[0]),
    }


def balancing_period_stats(
    product: str,
    area: str,
    start: date,
    end: date,
    db_path: str | None = None,
) -> dict[str, float | None]:
    """Mean balancing stats for *product* / *area* over ``[start, end]``.

    Computed over the raw block rows in the window — NOT the aggregation level.
    EprxBalancing is long-format (one row per metric), so each metric is reduced
    independently and ``avg_unprocured_mw`` is derived as
    ``avg_demand_mw - avg_contracted_mw``.

    Returns ``{"avg_demand_mw", "avg_contracted_mw", "avg_unprocured_mw",
    "avg_price", "avg_max_price"}`` (floats, or ``None`` where no data).
    """
    session = get_session(db_path)
    try:
        rows = session.execute(
            select(
                EprxBalancing.metric,
                func.avg(EprxBalancing.value),
            )
            .where(
                and_(
                    EprxBalancing.product == product,
                    EprxBalancing.area == area,
                    EprxBalancing.date >= start,
                    EprxBalancing.date <= end,
                )
            )
            .group_by(EprxBalancing.metric)
        ).all()
    finally:
        session.close()

    means = {metric: _mean(avg) for metric, avg in rows}

    avg_demand = means.get("demand_mw")
    avg_contracted = means.get("contracted_mw")
    if avg_demand is not None and avg_contracted is not None:
        avg_unprocured: float | None = avg_demand - avg_contracted
    else:
        avg_unprocured = None

    return {
        "avg_demand_mw": avg_demand,
        "avg_contracted_mw": avg_contracted,
        "avg_unprocured_mw": avg_unprocured,
        "avg_price": means.get("price_avg"),
        "avg_max_price": means.get("price_max"),
    }


# Thin cached wrappers (Streamlit) so the comparison UI re-renders instantly.

@st.cache_data(show_spinner=False)
def wholesale_period_stats_cached(
    area: str,
    start: date,
    end: date,
    _cache_buster: int = 0,
) -> dict[str, float | None]:
    """Cached wrapper around :func:`wholesale_period_stats` (default DB)."""
    return wholesale_period_stats(area, start, end)


@st.cache_data(show_spinner=False)
def balancing_period_stats_cached(
    product: str,
    area: str,
    start: date,
    end: date,
    _cache_buster: int = 0,
) -> dict[str, float | None]:
    """Cached wrapper around :func:`balancing_period_stats` (default DB)."""
    return balancing_period_stats(product, area, start, end)


# ── Export frame builders (pure, uncached) ──────────────────────────────────
# Build the wide, datetime-keyed frames the Excel/PDF exporters consume. They
# query the raw rows directly (so direct callers / tests need no Streamlit) and
# merge supply+price / volume+price on datetime.


def wholesale_export_frame(
    area: str,
    start: date,
    end: date,
    db_path: str | None = None,
) -> pd.DataFrame:
    """Merged demand + JEPX price frame for *area* (datetime-keyed, raw 30-min).

    Columns: ``datetime, area_demand_mw, price``. Empty frame if no data.
    """
    session = get_session(db_path)
    try:
        ds_rows = session.execute(
            select(DemandSupply30m).where(
                and_(
                    DemandSupply30m.area == area,
                    DemandSupply30m.date >= start,
                    DemandSupply30m.date <= end,
                )
            )
        ).scalars().all()
        price_rows = session.execute(
            select(JepxAreaPrice30m).where(
                and_(
                    JepxAreaPrice30m.area == area,
                    JepxAreaPrice30m.date >= start,
                    JepxAreaPrice30m.date <= end,
                )
            )
        ).scalars().all()
    finally:
        session.close()

    if ds_rows:
        supply = pd.DataFrame(
            [{c.name: getattr(r, c.name) for c in DemandSupply30m.__table__.columns}
             for r in ds_rows]
        )
        supply = _rollover_datetime(supply)
        supply = (
            supply.sort_values(["datetime", "id"])
            .drop_duplicates("datetime", keep="last")
            .reset_index(drop=True)
        )
        keep = [c for c in (["datetime", "area_demand_mw", *MIX_COLUMNS]) if c in supply.columns]
        supply = supply[keep]
    else:
        supply = pd.DataFrame(columns=["datetime", "area_demand_mw"])

    if price_rows:
        price = pd.DataFrame(
            [{c.name: getattr(r, c.name) for c in JepxAreaPrice30m.__table__.columns}
             for r in price_rows]
        )[["date", "time", "price"]]
        price = _rollover_datetime(price)
        price = (
            price.sort_values("datetime")
            .drop_duplicates("datetime", keep="last")
            .reset_index(drop=True)
        )[["datetime", "price"]]
    else:
        price = pd.DataFrame(columns=["datetime", "price"])

    if supply.empty and price.empty:
        return pd.DataFrame(columns=["datetime", "area_demand_mw", "price"])

    merged = pd.merge(supply, price, on="datetime", how="outer")
    return merged.sort_values("datetime").reset_index(drop=True)


def balancing_export_frame(
    product: str,
    area: str,
    start: date,
    end: date,
    db_path: str | None = None,
) -> pd.DataFrame:
    """Merged balancing volume + price frame for *product*/*area* (datetime-keyed).

    Pivots the long EprxBalancing rows to wide, derives ``missing_mw`` and keeps
    the volume + price columns. Empty frame if no data.
    """
    session = get_session(db_path)
    try:
        rows = session.execute(
            select(EprxBalancing).where(
                and_(
                    EprxBalancing.product == product,
                    EprxBalancing.area == area,
                    EprxBalancing.date >= start,
                    EprxBalancing.date <= end,
                )
            )
        ).scalars().all()
    finally:
        session.close()

    if not rows:
        return pd.DataFrame()

    long_df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in EprxBalancing.__table__.columns}
         for r in rows]
    )
    long_df = _rollover_datetime(long_df)

    wide = long_df.pivot_table(
        index="datetime",
        columns="metric",
        values="value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    if "demand_mw" in wide.columns and "contracted_mw" in wide.columns:
        wide["missing_mw"] = wide["demand_mw"] - wide["contracted_mw"]

    return wide.sort_values("datetime").reset_index(drop=True)


# ── Serialization helper ───────────────────────────────────────────────────

def _records(df: pd.DataFrame) -> list[dict]:
    """Convert a frame to JSON-friendly records with ISO datetime strings."""
    if df is None or df.empty:
        return []
    out = df.copy()
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    return out.to_dict("records")
