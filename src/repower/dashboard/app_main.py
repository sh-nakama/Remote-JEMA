"""Main dashboard app — 9-area x 2-column grid for wholesale + balancing markets.

Entry points (``dashboard/app.py``, ``space/app.py``) call ``st.set_page_config``
and then ``main()``; therefore ``main()`` must NOT call ``set_page_config``. It
injects :data:`repower.dashboard.theme.GLOBAL_CSS` and renders four top-level
views (Wholesale, Balancing, Drivers, Analyses) selected via a radio — only the
active view is rendered, so the D3 chart iframes always draw at full width.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select

from repower.config import DB_PATH, EPRX_BALANCING_PARQUET
from repower.db import DemandSupply30m, PolicyCommittee, PolicyMeeting
from repower.scrapers.areas import AREA_NAMES

import repower.dashboard.theme as theme
from repower.dashboard.i18n import (
    DEFAULT_LANG,
    LANG_OPTIONS,
    T,
    metric_labels,
)
from repower.dashboard.read import (
    MIX_COLUMNS,
    balancing_export_frame,
    balancing_period_stats_cached,
    load_balancing_grid,
    load_tieline,
    load_wholesale_grid,
    wholesale_export_frame,
    wholesale_period_stats_cached,
)
from repower.dashboard.components.excel_export import build_excel_workbook
from repower.dashboard.components.generation_chart import render_generation_chart
from repower.dashboard.components.pdf_export import (
    generate_pdf,
    generate_wholesale_pdf,
)
from repower.dashboard.components.price_chart import render_price_chart
from repower.dashboard.components.volume_chart import render_volume_chart
from repower.dashboard.components.tieline_chart import render_tieline_chart

# Salvaged legacy helpers + views (Drivers / Analyses).
from repower.dashboard.legacy import (
    _analyses,
    _db_session,
    _fuels,
    _jepx_area,
)

# Area order from the plan / scrapers.
AREA_ORDER: list[str] = [
    "hokkaido", "tohoku", "tepco", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu",
]

AGG_LEVELS = ["Native", "Daily", "Weekly", "Monthly"]
DEFAULT_AGG_INDEX = AGG_LEVELS.index("Daily")

# Generation-mix stack keys: every MIX column except the `total_supply` overlay.
STACK_KEYS: list[str] = [c for c in MIX_COLUMNS if c != "total_supply"]

# Wholesale + balancing share these three price metrics.
PRICE_METRICS = ["price_max", "price_avg", "price_min"]
BALANCING_VOLUME_METRICS = ["demand_mw", "contracted_mw", "missing_mw"]
TIELINE_MARKETS = ["DCM", "DAM"]


# ── Available-data date bounds (overall, across all areas) ──────────────────

@st.cache_data(show_spinner=False)
def _overall_date_bounds(_cache_buster: int = 0) -> tuple[date, date] | None:
    """Overall (min, max) date across supply/demand (SQLite) and EPRX (Parquet)."""
    mins: list[date] = []
    maxs: list[date] = []

    # Supply/demand lives in SQLite.
    session = _db_session()
    row = session.execute(
        select(func.min(DemandSupply30m.date), func.max(DemandSupply30m.date))
    ).one_or_none()
    if row and row[0] is not None:
        mins.append(row[0])
        maxs.append(row[1])

    # EPRX balancing lives in Parquet (date stored as ISO 'YYYY-MM-DD' string).
    p = Path(EPRX_BALANCING_PARQUET)
    if p.exists():
        dser = pd.read_parquet(p, columns=["date"])["date"]
        if not dser.empty:
            mins.append(date.fromisoformat(str(dser.min())))
            maxs.append(date.fromisoformat(str(dser.max())))

    if not mins:
        return None
    return min(mins), max(maxs)


# ── Period-comparison helpers ───────────────────────────────────────────────

# Default comparison windows: Period A = last 7 days of data, Period B = the
# 7 days immediately before that.
_PERIOD_LEN = 7


def _default_periods(
    data_min: date, data_max: date,
) -> tuple[tuple[date, date], tuple[date, date]]:
    """Return ((a_start, a_end), (b_start, b_end)) defaults from the bounds."""
    a_end = data_max
    a_start = max(data_min, a_end - timedelta(days=_PERIOD_LEN - 1))
    b_end = a_start - timedelta(days=1)
    if b_end < data_min:
        b_end = a_start
    b_start = max(data_min, b_end - timedelta(days=_PERIOD_LEN - 1))
    return (a_start, a_end), (b_start, b_end)


def _period_range_picker(label: str, default: tuple[date, date],
                         data_min: date, data_max: date, key: str) -> tuple[date, date]:
    """A date-range picker bounded to the data window; returns (start, end)."""
    picked = st.date_input(
        label,
        value=default,
        min_value=data_min,
        max_value=data_max,
        key=key,
    )
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        return picked[0], picked[1]
    return default


def _fmt(value) -> float | None:
    """Round a metric for display, passing through None."""
    return round(value, 2) if value is not None else None


def _delta(a, b):
    """A − B, or None if either side is missing."""
    if a is None or b is None:
        return None
    return round(a - b, 2)


# ── Cached export builders ──────────────────────────────────────────────────
# Keyed on (market, product, dates, areas, cache_buster) so repeated clicks of
# the download buttons return instantly (mirrors the reference's cached PDFs).


@st.cache_data(show_spinner=False)
def _wholesale_excel_bytes(
    areas: tuple[str, ...], start: date, end: date, _cache_buster: int = 0,
) -> bytes | None:
    """One sheet per area: merged demand + JEPX price. None if all empty."""
    sheets: dict[str, pd.DataFrame] = {}
    for area in areas:
        df = wholesale_export_frame(area, start, end)
        if not df.empty:
            sheets[AREA_NAMES.get(area, area)] = df
    if not sheets:
        return None
    return build_excel_workbook(sheets)


@st.cache_data(show_spinner=False)
def _wholesale_pdf_bytes(
    areas: tuple[str, ...], start: date, end: date, _cache_buster: int = 0,
) -> bytes | None:
    """A4 PDF, one row per area (demand | JEPX price). None if all empty."""
    area_data: dict[str, pd.DataFrame] = {}
    for area in areas:
        df = wholesale_export_frame(area, start, end)
        if not df.empty:
            area_data[AREA_NAMES.get(area, area)] = df
    if not area_data:
        return None
    return generate_wholesale_pdf(
        area_data, start, end,
        demand_color=theme.METRIC_COLORS["demand_mw"],
        price_color=theme.BRAND_TEAL,
    )


@st.cache_data(show_spinner=False)
def _balancing_excel_bytes(
    product: str, areas: tuple[str, ...], start: date, end: date,
    _cache_buster: int = 0,
) -> bytes | None:
    """One sheet per area: merged volume + price for *product*. None if empty."""
    sheets: dict[str, pd.DataFrame] = {}
    for area in areas:
        df = balancing_export_frame(product, area, start, end)
        if not df.empty:
            sheets[AREA_NAMES.get(area, area)] = df
    if not sheets:
        return None
    return build_excel_workbook(sheets)


@st.cache_data(show_spinner=False)
def _balancing_pdf_bytes(
    product: str, areas: tuple[str, ...], start: date, end: date,
    labels: dict[str, str] | None = None, _cache_buster: int = 0,
) -> bytes | None:
    """Reuse the balancing ``generate_pdf`` for the selected product.

    Builds the long-form ``{product: frame}`` with a ``region`` column the
    reference exporter expects. None if no area has data.
    """
    labels = labels or theme.METRIC_LABELS
    frames: list[pd.DataFrame] = []
    for area in areas:
        df = balancing_export_frame(product, area, start, end)
        if df.empty:
            continue
        df = df.copy()
        df["region"] = AREA_NAMES.get(area, area)
        frames.append(df)
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    regions = [AREA_NAMES.get(a, a) for a in areas
               if AREA_NAMES.get(a, a) in set(combined["region"])]
    return generate_pdf(
        product_data={product: combined},
        regions=regions,
        vol_metrics=BALANCING_VOLUME_METRICS,
        price_metrics=PRICE_METRICS,
        color_map=theme.METRIC_COLORS,
        label_map=labels,
        view_start=start,
        view_end=end,
    )


# ── Sidebar ─────────────────────────────────────────────────────────────────

def _render_sidebar(show_refresh: bool) -> dict:
    """Render global controls. Returns selected lang / dates / areas."""
    st.sidebar.title("Japan Power Markets")

    if show_refresh:
        if st.sidebar.button(
            "🔄 Refresh data",
            help="Pull the latest DB + Parquet from Hugging Face (if configured), then reload.",
        ):
            from repower.config import HF_DATASET_REPO, HF_TOKEN
            hf_ready = bool(HF_TOKEN and HF_DATASET_REPO)
            if hf_ready:
                try:
                    with st.spinner("Pulling latest data from Hugging Face…"):
                        from repower.hf_sync import pull_db_from_hf
                        pull_db_from_hf()
                except Exception as exc:  # noqa: BLE001
                    st.sidebar.error(f"HF pull failed (reloading local data): {exc}")
            # ALWAYS clear caches + reload, so a fresh local scrape is picked up
            # even when Hugging Face is not configured.
            st.cache_resource.clear()
            st.cache_data.clear()
            st.session_state["cache_buster"] = st.session_state.get("cache_buster", 0) + 1
            st.session_state.pop("db_ready", None)
            if not hf_ready:
                st.sidebar.info("Hugging Face not configured — reloaded local data only.")
            st.rerun()

    st.sidebar.markdown("---")

    # Language.
    lang_codes = list(LANG_OPTIONS.keys())
    lang = st.sidebar.selectbox(
        "Language",
        options=lang_codes,
        format_func=lambda c: LANG_OPTIONS[c],
        index=lang_codes.index(DEFAULT_LANG),
        key="lang_select",
    )

    # Date range — default to the last 60 days of available data. 60 (not 30) so
    # the window still overlaps a market whose latest data lags the others (e.g.
    # JEPX publishing behind balancing), avoiding an empty default view.
    cache_buster = st.session_state.get("cache_buster", 0)
    bounds = _overall_date_bounds(cache_buster)
    if bounds:
        data_min, data_max = bounds
    else:
        data_max = date.today()
        data_min = data_max - timedelta(days=365)
    default_start = max(data_min, data_max - timedelta(days=60))

    picked = st.sidebar.date_input(
        "Date range",
        value=(default_start, data_max),
        min_value=data_min,
        max_value=data_max,
        key="date_range",
    )
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        start, end = picked[0], picked[1]
    else:
        # date_input may return a single date mid-edit; fall back gracefully.
        start, end = default_start, data_max

    # Area subset — default all 9, in canonical order.
    areas = st.sidebar.multiselect(
        "Areas",
        options=AREA_ORDER,
        default=AREA_ORDER,
        format_func=lambda a: AREA_NAMES[a],
        key="area_subset",
    )

    st.sidebar.caption(f"DB: `{DB_PATH}`")

    return {
        "lang": lang,
        "start": start,
        "end": end,
        "areas": areas,
        "cache_buster": cache_buster,
    }


# ── Wholesale: period comparison + export ────────────────────────────────────

def _render_wholesale_comparison(cfg: dict) -> None:
    """Period A vs Period B mean stats, one row per selected area."""
    areas = [a for a in AREA_ORDER if a in cfg["areas"]]
    bounds = _overall_date_bounds(cfg["cache_buster"])
    if bounds:
        data_min, data_max = bounds
    else:
        data_max = date.today()
        data_min = data_max - timedelta(days=30)
    (a_def, b_def) = _default_periods(data_min, data_max)

    col_a, col_b = st.columns(2)
    with col_a:
        a_start, a_end = _period_range_picker(
            "Period A", a_def, data_min, data_max, "wholesale_period_a")
    with col_b:
        b_start, b_end = _period_range_picker(
            "Period B", b_def, data_min, data_max, "wholesale_period_b")

    rows: list[dict] = []
    for area in areas:
        a = wholesale_period_stats_cached(area, a_start, a_end, cfg["cache_buster"])
        b = wholesale_period_stats_cached(area, b_start, b_end, cfg["cache_buster"])
        rows.append({
            "Area": AREA_NAMES[area],
            "A Avg Demand (MW)": _fmt(a["avg_demand_mw"]),
            "B Avg Demand (MW)": _fmt(b["avg_demand_mw"]),
            "Δ Avg Demand (MW)": _delta(a["avg_demand_mw"], b["avg_demand_mw"]),
            "A Peak Demand (MW)": _fmt(a["peak_demand_mw"]),
            "B Peak Demand (MW)": _fmt(b["peak_demand_mw"]),
            "Δ Peak Demand (MW)": _delta(a["peak_demand_mw"], b["peak_demand_mw"]),
            "A Avg Price (¥/kWh)": _fmt(a["avg_price"]),
            "B Avg Price (¥/kWh)": _fmt(b["avg_price"]),
            "Δ Avg Price (¥/kWh)": _delta(a["avg_price"], b["avg_price"]),
        })

    df = pd.DataFrame(rows)
    st.caption(
        f"A: {a_start} → {a_end}  ·  B: {b_start} → {b_end}  (means over raw 30-min rows)"
    )
    st.dataframe(df, width="stretch", hide_index=True)


def _render_wholesale_export(cfg: dict) -> None:
    """Export row (Excel + PDF) for the wholesale grid view."""
    areas = tuple(a for a in AREA_ORDER if a in cfg["areas"])
    start, end, cb = cfg["start"], cfg["end"], cfg["cache_buster"]

    xlsx = _wholesale_excel_bytes(areas, start, end, cb)
    pdf = _wholesale_pdf_bytes(areas, start, end, cb)

    c1, c2 = st.columns(2)
    with c1:
        if xlsx:
            st.download_button(
                "Export Excel", data=xlsx,
                file_name=f"wholesale_{start}_{end}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="wholesale_xlsx",
            )
        else:
            st.caption("No data to export.")
    with c2:
        if pdf:
            st.download_button(
                "Export PDF", data=pdf,
                file_name=f"wholesale_{start}_{end}.pdf",
                mime="application/pdf",
                key="wholesale_pdf",
            )
        else:
            st.caption("No data to export.")


# ── Wholesale tab ────────────────────────────────────────────────────────────

def _render_wholesale_tab(cfg: dict) -> None:
    lang = cfg["lang"]
    labels = metric_labels(lang)

    view = st.radio(
        "View",
        ["Grid", "Period comparison"],
        horizontal=True,
        key="wholesale_view",
    )

    if not cfg["areas"]:
        st.info("Select at least one area in the sidebar.")
        return

    if view == "Period comparison":
        _render_wholesale_comparison(cfg)
        return

    level = st.radio(
        "Aggregation",
        AGG_LEVELS,
        index=DEFAULT_AGG_INDEX,
        horizontal=True,
        key="wholesale_agg",
    )

    _render_wholesale_export(cfg)

    for area in [a for a in AREA_ORDER if a in cfg["areas"]]:
        grid = load_wholesale_grid(
            area, cfg["start"], cfg["end"], level, cfg["cache_buster"],
        )
        supply = grid.get("supply") or []
        price = grid.get("price") or []
        title = AREA_NAMES[area]

        if not supply and not price:
            st.caption(f"{title}: no data in the selected range.")
            continue

        left, right = st.columns(2)
        with left:
            if supply:
                render_generation_chart(
                    data=supply,
                    stack_keys=STACK_KEYS,
                    color_map=theme.GENERATION_COLORS,
                    label_map=theme.GENERATION_LABELS,
                    demand_key="area_demand_mw",
                    title=title,
                    height=300,
                )
            else:
                st.caption(f"{title}: no supply data.")
        with right:
            if price:
                render_price_chart(
                    data=price,
                    active_metrics=PRICE_METRICS,
                    color_map=theme.METRIC_COLORS,
                    label_map=labels,
                    title=title,
                    height=300,
                    subtitle="¥/kWh",
                    y_label="¥/kWh",
                )
            else:
                st.caption(f"{title}: no price data.")


# ── Balancing: period comparison + export ─────────────────────────────────────

def _render_balancing_comparison(cfg: dict, product: str) -> None:
    """Period A vs Period B mean stats for *product*, one row per area."""
    areas = [a for a in AREA_ORDER if a in cfg["areas"]]
    bounds = _overall_date_bounds(cfg["cache_buster"])
    if bounds:
        data_min, data_max = bounds
    else:
        data_max = date.today()
        data_min = data_max - timedelta(days=30)
    (a_def, b_def) = _default_periods(data_min, data_max)

    col_a, col_b = st.columns(2)
    with col_a:
        a_start, a_end = _period_range_picker(
            "Period A", a_def, data_min, data_max, "balancing_period_a")
    with col_b:
        b_start, b_end = _period_range_picker(
            "Period B", b_def, data_min, data_max, "balancing_period_b")

    rows: list[dict] = []
    for area in areas:
        a = balancing_period_stats_cached(product, area, a_start, a_end, cfg["cache_buster"])
        b = balancing_period_stats_cached(product, area, b_start, b_end, cfg["cache_buster"])
        rows.append({
            "Area": AREA_NAMES[area],
            "A Avg Demand (MW)": _fmt(a["avg_demand_mw"]),
            "B Avg Demand (MW)": _fmt(b["avg_demand_mw"]),
            "Δ Avg Demand (MW)": _delta(a["avg_demand_mw"], b["avg_demand_mw"]),
            "A Avg Contracted (MW)": _fmt(a["avg_contracted_mw"]),
            "B Avg Contracted (MW)": _fmt(b["avg_contracted_mw"]),
            "Δ Avg Contracted (MW)": _delta(a["avg_contracted_mw"], b["avg_contracted_mw"]),
            "A Avg Unprocured (MW)": _fmt(a["avg_unprocured_mw"]),
            "B Avg Unprocured (MW)": _fmt(b["avg_unprocured_mw"]),
            "Δ Avg Unprocured (MW)": _delta(a["avg_unprocured_mw"], b["avg_unprocured_mw"]),
            "A Avg Price (¥/kW·30min)": _fmt(a["avg_price"]),
            "B Avg Price (¥/kW·30min)": _fmt(b["avg_price"]),
            "Δ Avg Price (¥/kW·30min)": _delta(a["avg_price"], b["avg_price"]),
            "A Avg Max Price": _fmt(a["avg_max_price"]),
            "B Avg Max Price": _fmt(b["avg_max_price"]),
            "Δ Avg Max Price": _delta(a["avg_max_price"], b["avg_max_price"]),
        })

    df = pd.DataFrame(rows)
    st.caption(
        f"A: {a_start} → {a_end}  ·  B: {b_start} → {b_end}  (means over raw block rows)"
    )
    st.dataframe(df, width="stretch", hide_index=True)


def _render_balancing_export(cfg: dict, product: str, labels: dict[str, str]) -> None:
    """Export row (Excel + PDF) for the balancing grid view."""
    areas = tuple(a for a in AREA_ORDER if a in cfg["areas"])
    start, end, cb = cfg["start"], cfg["end"], cfg["cache_buster"]

    xlsx = _balancing_excel_bytes(product, areas, start, end, cb)
    pdf = _balancing_pdf_bytes(product, areas, start, end, labels, cb)

    c1, c2 = st.columns(2)
    with c1:
        if xlsx:
            st.download_button(
                "Export Excel", data=xlsx,
                file_name=f"balancing_{product}_{start}_{end}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="balancing_xlsx",
            )
        else:
            st.caption("No data to export.")
    with c2:
        if pdf:
            st.download_button(
                "Export PDF", data=pdf,
                file_name=f"balancing_{product}_{start}_{end}.pdf",
                mime="application/pdf",
                key="balancing_pdf",
            )
        else:
            st.caption("No data to export.")


# ── Balancing tab ────────────────────────────────────────────────────────────

def _render_balancing_tab(cfg: dict) -> None:
    lang = cfg["lang"]
    labels = metric_labels(lang)

    view = st.radio(
        "View",
        ["Grid", "Period comparison"],
        horizontal=True,
        key="balancing_view",
    )

    product = st.selectbox(
        "Product",
        options=theme.PRODUCT_ORDER,
        index=theme.PRODUCT_ORDER.index("Primary"),
        key="balancing_product",
    )

    if not cfg["areas"]:
        st.info("Select at least one area in the sidebar.")
        return

    if view == "Period comparison":
        _render_balancing_comparison(cfg, product)
        return

    level = st.radio(
        "Aggregation",
        AGG_LEVELS,
        index=DEFAULT_AGG_INDEX,
        horizontal=True,
        key="balancing_agg",
    )

    _render_balancing_export(cfg, product, labels)

    for area in [a for a in AREA_ORDER if a in cfg["areas"]]:
        grid = load_balancing_grid(
            product, area, cfg["start"], cfg["end"], level, cfg["cache_buster"],
        )
        volume = grid.get("volume") or []
        price = grid.get("price") or []
        title = AREA_NAMES[area]

        if not volume and not price:
            st.caption(f"{title}: no {product} data in the selected range.")
            continue

        left, right = st.columns(2)
        with left:
            if volume:
                render_volume_chart(
                    data=volume,
                    active_metrics=BALANCING_VOLUME_METRICS,
                    color_map=theme.METRIC_COLORS,
                    label_map=labels,
                    title=title,
                    height=300,
                )
            else:
                st.caption(f"{title}: no volume data.")
        with right:
            if price:
                render_price_chart(
                    data=price,
                    active_metrics=PRICE_METRICS,
                    color_map=theme.METRIC_COLORS,
                    label_map=labels,
                    title=title,
                    height=300,
                )
            else:
                st.caption(f"{title}: no price data.")

    # ── Interconnector panel (full-width) ──
    st.markdown("---")
    st.subheader("Interconnectors")
    market = st.selectbox(
        "Market",
        options=TIELINE_MARKETS,
        index=0,
        key="tieline_market_select",
    )
    tielines = load_tieline(
        market, cfg["start"], cfg["end"], level, cfg["cache_buster"],
    )
    if not tielines:
        st.caption("No interconnector data in the selected range.")
        return

    tl_df = pd.DataFrame(tielines)
    tl_labels = labels  # tieline metric labels live in METRIC_LABELS / met_ keys
    for pair in sorted(tl_df["pair"].dropna().unique()):
        pair_records = tl_df[tl_df["pair"] == pair].to_dict("records")
        if not pair_records:
            continue
        render_tieline_chart(
            data=pair_records,
            active_metrics=theme.TIELINE_METRICS,
            color_map=theme.METRIC_COLORS,
            label_map=tl_labels,
            title=str(pair),
            height=320,
            lang=lang,
        )


# ── Drivers tab (salvaged from legacy) ───────────────────────────────────────

def render_drivers(cfg: dict) -> None:
    """Fuels + JEPX-vs-Brent correlation view (area-aware)."""
    st.header("Price Drivers — Fuels & Correlations")

    area_choices = [a for a in AREA_ORDER if a in cfg["areas"]] or AREA_ORDER
    area = st.selectbox(
        "Area",
        options=area_choices,
        format_func=lambda a: AREA_NAMES[a],
        key="drivers_area",
    )
    start_date, end_date = cfg["start"], cfg["end"]
    st.caption(f"Range: **{start_date}** → **{end_date}**")

    fuels_df = _fuels(start_date, end_date)
    jepx_df = _jepx_area(area, start_date, end_date)

    if not fuels_df.empty:
        fuels_df = fuels_df.copy()
        fuels_df["date"] = pd.to_datetime(fuels_df["date"])
        fig = px.line(
            fuels_df, x="date", y="close", color="ticker",
            title="Commodity Prices (Daily Close)",
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No fuel/commodity data in the selected range.")

    if not jepx_df.empty and not fuels_df.empty:
        daily_price = jepx_df.groupby("date")["price"].mean().reset_index()
        daily_price.columns = ["date", "jepx_avg"]
        daily_price["date"] = pd.to_datetime(daily_price["date"])

        brent = fuels_df[fuels_df["ticker"] == "BZ=F"][["date", "close"]].copy()
        brent.columns = ["date", "brent"]

        merged = daily_price.merge(brent, on="date", how="inner")
        if not merged.empty:
            corr = merged["brent"].corr(merged["jepx_avg"])
            fig2 = px.scatter(
                merged, x="brent", y="jepx_avg",
                title=f"{AREA_NAMES[area]} JEPX vs Brent Crude (Pearson r = {corr:.2f})",
                labels={"brent": "Brent (USD/bbl)", "jepx_avg": "JEPX Avg (¥/kWh)"},
            )
            fig2.update_layout(height=350)
            st.plotly_chart(fig2, width="stretch")
        else:
            st.caption("No overlapping JEPX/Brent dates to correlate.")
    elif jepx_df.empty:
        st.caption(f"No JEPX price data for {AREA_NAMES[area]} in this range.")


# ── Analyses tab (salvaged from legacy) ──────────────────────────────────────

def render_analyses() -> None:
    """Daily analysis-history view."""
    st.header("Daily Analysis History")
    analyses_df = _analyses()

    if analyses_df.empty:
        st.info("No analyses recorded yet. Run `repower analyze` to generate.")
        return

    for _, row in analyses_df.iterrows():
        with st.expander(f"{row['date']}"):
            if row.get("narrative_md"):
                st.markdown(row["narrative_md"])
            if row.get("features_json"):
                try:
                    features = json.loads(row["features_json"])
                    st.json(features)
                except (ValueError, TypeError):
                    st.caption("Could not parse analysis features.")


# ── Policy observer tab ──────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _policy_committees(_cache_buster: int) -> list[dict]:
    session = _db_session()
    try:
        rows = (
            session.query(PolicyCommittee)
            .order_by(PolicyCommittee.source, PolicyCommittee.committee_key)
            .all()
        )
        return [
            {
                "committee_key": r.committee_key,
                "name_ja": r.name_ja or r.committee_key,
                "name_en": r.name_en or r.committee_key,
                "url": r.url,
                "source": r.source,
                "latest_meeting": r.latest_meeting,
                "running_summary_md": r.running_summary_md,
                "running_digest_en_md": r.running_digest_en_md,
            }
            for r in rows
        ]
    finally:
        session.close()


@st.cache_data(show_spinner=False)
def _policy_meetings(key: str, _cache_buster: int) -> list[dict]:
    session = _db_session()
    try:
        rows = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key)
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
        return [
            {
                "meeting_num": r.meeting_num,
                "meeting_date": str(r.meeting_date) if r.meeting_date else None,
                "state": r.state,
                "has_torimatome": bool(r.has_torimatome),
                "briefing_md": r.briefing_md,
                "digest_en_json": r.digest_en_json,
            }
            for r in rows
        ]
    finally:
        session.close()


def _policy_digest_answer(blob: str | None) -> str | None:
    if not blob:
        return None
    try:
        return (json.loads(blob) or {}).get("answer")
    except (ValueError, TypeError):
        return None


def render_policy(cfg: dict) -> None:
    """Policy observer view: per-committee running document + per-meeting briefings."""
    lang = cfg.get("lang", DEFAULT_LANG)
    st.header(T("policy_header", lang))

    committees = _policy_committees(cfg["cache_buster"])
    if not committees:
        st.info(T("policy_no_data", lang))
        return

    labels = {c["committee_key"]: f"{c['name_en']} — {c['name_ja']}" for c in committees}
    key = st.selectbox(
        T("policy_committee", lang),
        options=[c["committee_key"] for c in committees],
        format_func=lambda k: labels.get(k, k),
    )
    row = next(c for c in committees if c["committee_key"] == key)
    latest = f"第{row['latest_meeting']}回" if row["latest_meeting"] else "—"
    st.caption(f"{row['source']} · {T('policy_latest', lang)}: {latest} · {row['url']}")

    # Download the full running document (regenerated from the DB).
    try:
        from repower.policy.store import build_running_doc

        st.download_button(
            T("policy_download_doc", lang),
            data=build_running_doc(key),
            file_name=f"{key}.md",
            mime="text/markdown",
        )
    except Exception:  # noqa: BLE001 — download is a convenience, never block the view
        pass

    if row.get("running_digest_en_md"):
        st.subheader(T("policy_overview_en", lang))
        st.markdown(row["running_digest_en_md"])
    if row.get("running_summary_md"):
        with st.expander(T("policy_synthesis_ja", lang), expanded=False):
            st.markdown(row["running_summary_md"])

    meetings = _policy_meetings(key, cfg["cache_buster"])
    if not meetings:
        st.caption(T("policy_no_meetings", lang))
        return

    st.subheader(T("policy_meetings", lang))
    for m in meetings:
        title = f"第{m['meeting_num']}回"
        if m["meeting_date"]:
            title += f" — {m['meeting_date']}"
        if m["has_torimatome"]:
            title += " 🏁"
        if m["state"] != "done":
            title += f"  ·  {m['state']}"
        with st.expander(title, expanded=False):
            en = _policy_digest_answer(m["digest_en_json"])
            if en:
                st.markdown(f"**{T('policy_english_digest', lang)}**")
                st.markdown(en)
            if m["briefing_md"]:
                st.markdown(m["briefing_md"])
            elif not en:
                st.caption(f"({m['state']}; not yet summarised)")


# ── Main entry ───────────────────────────────────────────────────────────────

def main(show_refresh: bool = False) -> None:
    """Render the full dashboard. Call AFTER st.set_page_config."""
    st.markdown(theme.GLOBAL_CSS, unsafe_allow_html=True)

    # Cache buster passed to every load_* call; bumped by the Refresh button.
    if "cache_buster" not in st.session_state:
        st.session_state["cache_buster"] = 0

    cfg = _render_sidebar(show_refresh)

    # Top-level navigation via a radio, NOT st.tabs. st.tabs renders every panel
    # on every run; the D3 chart iframes inside hidden panels draw at width 0 and
    # collapse to ~4px, so non-active tabs appear blank. Rendering ONLY the
    # selected view guarantees every chart draws at full width (and is faster).
    view = st.radio(
        "Market view",
        ["Wholesale", "Balancing", "Drivers", "Analyses", "Policy"],
        horizontal=True,
        label_visibility="collapsed",
        key="top_view",
    )
    st.markdown("")

    # One view's failure must never blank or crash the whole app.
    try:
        if view == "Wholesale":
            _render_wholesale_tab(cfg)
        elif view == "Balancing":
            _render_balancing_tab(cfg)
        elif view == "Drivers":
            render_drivers(cfg)
        elif view == "Policy":
            render_policy(cfg)
        else:
            render_analyses()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception("View %r failed to render", view)
        st.error(f"⚠️ The **{view}** view hit an error and couldn't render: {exc}")
        st.caption("This has been logged. Try a different date range, or use Refresh data in the sidebar.")
