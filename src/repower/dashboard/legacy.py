"""Streamlit dashboard logic — callable as main() from any entry point."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import and_, select

from repower.config import DB_PATH
from repower.db import (
    AnalysisRecord,
    DemandSupply30m,
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


def _ds(start: date, end: date, area: str = "tepco") -> pd.DataFrame:
    session = _db_session()
    rows = session.execute(
        select(DemandSupply30m).where(
            and_(
                DemandSupply30m.area == area,
                DemandSupply30m.date >= start,
                DemandSupply30m.date <= end,
            )
        )
    ).scalars().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in DemandSupply30m.__table__.columns} for r in rows]
    )
    # Normalize "24:00" rows (some TSOs report end-of-day this way) to next-day 00:00
    rollover = df["time"].astype(str).str.strip() == "24:00"
    if rollover.any():
        df.loc[rollover, "date"] = pd.to_datetime(df.loc[rollover, "date"]) + pd.Timedelta(days=1)
        df.loc[rollover, "date"] = df.loc[rollover, "date"].dt.date
        df.loc[rollover, "time"] = "00:00"
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"])
    # De-duplicate (date,time) keeping latest id, then sort chronologically.
    # Without this, unsorted SQLite output produces zig-zag "multiple lines" in plots.
    df = df.sort_values(["datetime", "id"]).drop_duplicates("datetime", keep="last")
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


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


def _jepx_all_areas(start: date, end: date) -> pd.DataFrame:
    """Long-format per-area prices for every region in [start, end]."""
    session = _db_session()
    rows = session.execute(
        select(JepxAreaPrice30m).where(
            and_(JepxAreaPrice30m.date >= start, JepxAreaPrice30m.date <= end)
        )
    ).scalars().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in JepxAreaPrice30m.__table__.columns} for r in rows]
    )[["area", "date", "time", "price"]]
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
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


def _data_date_bounds(area: str = "tepco") -> tuple[date, date] | None:
    """Return (min, max) date present in DemandSupply30m for the area."""
    session = _db_session()
    from sqlalchemy import func
    row = session.execute(
        select(func.min(DemandSupply30m.date), func.max(DemandSupply30m.date))
        .where(DemandSupply30m.area == area)
    ).one_or_none()
    if not row or row[0] is None:
        return None
    return row[0], row[1]


# ── Date range UI helper ──────────────────────────────────────────────────

_RANGE_PRESETS: dict[str, int | None] = {
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
    "3Y": 365 * 3,
    "All": None,
    "Custom": -1,
}


def _date_range_picker(key: str, default: str = "1M", area: str = "tepco") -> tuple[date, date]:
    """Render quick preset buttons + optional custom picker. Returns (start, end)."""
    bounds = _data_date_bounds(area)
    data_min = bounds[0] if bounds else date.today() - timedelta(days=365)
    data_max = bounds[1] if bounds else date.today()

    state_key = f"_range_{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = default

    cols = st.columns(len(_RANGE_PRESETS))
    for i, label in enumerate(_RANGE_PRESETS.keys()):
        if cols[i].button(label, key=f"{key}_btn_{label}",
                          type="primary" if st.session_state[state_key] == label else "secondary"):
            st.session_state[state_key] = label

    choice = st.session_state[state_key]
    end_date = data_max

    if choice == "Custom":
        picked = st.date_input(
            "Date range",
            value=(max(data_min, data_max - timedelta(days=30)), data_max),
            min_value=data_min, max_value=data_max,
            key=f"{key}_custom",
        )
        if isinstance(picked, tuple) and len(picked) == 2:
            return picked[0], picked[1]
        return data_min, data_max

    days = _RANGE_PRESETS[choice]
    if days is None:
        return data_min, data_max
    return max(data_min, end_date - timedelta(days=days)), end_date


def _analyses() -> pd.DataFrame:
    session = _db_session()
    rows = session.query(AnalysisRecord).order_by(AnalysisRecord.date.desc()).limit(30).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in AnalysisRecord.__table__.columns} for r in rows]
    )


# ── Main entry ─────────────────────────────────────────────────────────────

def main(show_refresh: bool = False) -> None:
    """Render the full dashboard. Call after st.set_page_config."""

    # ── Sidebar ──────────────────────────────────────────────────────────
    st.sidebar.title("⚡ RePower Tokyo")
    st.sidebar.caption("Power market analysis dashboard")

    if show_refresh:
        if st.sidebar.button("🔄 Refresh data"):
            with st.spinner("Pulling latest database from Hugging Face…"):
                try:
                    from repower.hf_sync import pull_db_from_hf
                    pull_db_from_hf()
                    st.cache_resource.clear()
                    st.session_state.pop("db_ready", None)
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Refresh failed: {e}")

    st.sidebar.markdown("---")
    from repower.scrapers.areas import AREA_NAMES
    area = st.sidebar.selectbox(
        "Area / TSO",
        options=list(AREA_NAMES.keys()),
        format_func=lambda a: AREA_NAMES[a],
        index=list(AREA_NAMES.keys()).index("tepco"),
        key="area_select",
    )
    st.sidebar.caption(f"DB: `{DB_PATH}`")

    tab_choice = st.sidebar.radio(
        "View",
        ["Today", "Compare", "Trends", "Drivers", "Areas Compare", "Analyses"],
    )

    # ── TODAY ─────────────────────────────────────────────────────────────
    if tab_choice == "Today":
        st.header(f"{AREA_NAMES[area]} \u2014 Supply & Demand")
        bounds = _data_date_bounds(area)
        latest = bounds[1] if bounds else date.today() - timedelta(days=1)
        earliest = bounds[0] if bounds else latest - timedelta(days=365)
        c1, c2, c3 = st.columns([1, 1, 3])
        if c1.button("Latest", key="today_latest"):
            st.session_state["today_date"] = latest
        if c2.button("Yesterday", key="today_yesterday"):
            st.session_state["today_date"] = min(latest, date.today() - timedelta(days=1))
        target = c3.date_input(
            "Date",
            value=st.session_state.get("today_date", latest),
            min_value=earliest, max_value=latest,
            key="today_date",
        )
        df = _ds(target, target, area=area)
        jepx_df = _jepx_area(area, target, target)

        if df.empty:
            st.warning("No TEPCO data available for this date.")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric("Peak Demand", f"{int(df['area_demand_mw'].max()):,} MW")
            col2.metric("Min Demand", f"{int(df['area_demand_mw'].min()):,} MW")
            col3.metric("Avg Demand", f"{int(df['area_demand_mw'].mean()):,} MW")

            fig = px.line(df, x="datetime", y="area_demand_mw", title="Area Demand (MW)")
            fig.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig, width="stretch")

            gen_cols = [
                "nuclear", "lng", "coal", "oil", "thermal_other",
                "hydro", "geothermal", "biomass", "solar_actual",
                "wind_actual", "pumped", "battery", "interconnect", "other",
            ]
            available = [c for c in gen_cols if c in df.columns and df[c].sum() > 0]

            fig2 = go.Figure()
            for col in available:
                fig2.add_trace(go.Scatter(
                    x=df["datetime"], y=df[col],
                    mode="lines", stackgroup="one",
                    name=col.replace("_", " ").title(),
                ))
            fig2.update_layout(title="Generation Stack (MW)", height=400, margin=dict(t=40, b=20))
            st.plotly_chart(fig2, width="stretch")

            totals = {col: df[col].sum() for col in available}
            fig3 = px.pie(
                names=[c.replace("_", " ").title() for c in totals],
                values=list(totals.values()),
                title="Generation Mix (%)",
                hole=0.4,
            )
            fig3.update_layout(height=350)
            st.plotly_chart(fig3, width="stretch")

        if not jepx_df.empty:
            st.subheader(f"JEPX Spot Price — {AREA_NAMES[area]}")
            col1, col2 = st.columns(2)
            col1.metric("Avg Price", f"¥{jepx_df['price'].mean():.2f}/kWh")
            col2.metric("Peak Price", f"¥{jepx_df['price'].max():.2f}/kWh")
            fig4 = px.line(jepx_df, x="datetime", y="price", title="Spot Price (¥/kWh)")
            fig4.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig4, width="stretch")

    # ── COMPARE ───────────────────────────────────────────────────────────
    elif tab_choice == "Compare":
        st.header(f"{AREA_NAMES[area]} \u2014 Compare Two Days")
        bounds = _data_date_bounds(area)
        latest = bounds[1] if bounds else date.today() - timedelta(days=1)
        earliest = bounds[0] if bounds else latest - timedelta(days=365)

        preset_cols = st.columns(4)
        if preset_cols[0].button("Yesterday vs week ago", key="cmp_w"):
            st.session_state["cmp_a"] = latest
            st.session_state["cmp_b"] = max(earliest, latest - timedelta(days=7))
        if preset_cols[1].button("Yesterday vs month ago", key="cmp_m"):
            st.session_state["cmp_a"] = latest
            st.session_state["cmp_b"] = max(earliest, latest - timedelta(days=30))
        if preset_cols[2].button("Yesterday vs year ago", key="cmp_y"):
            st.session_state["cmp_a"] = latest
            st.session_state["cmp_b"] = max(earliest, latest - timedelta(days=365))

        col1, col2 = st.columns(2)
        date1 = col1.date_input(
            "Date A", value=st.session_state.get("cmp_a", latest),
            min_value=earliest, max_value=latest, key="cmp_a",
        )
        date2 = col2.date_input(
            "Date B", value=st.session_state.get("cmp_b", max(earliest, latest - timedelta(days=7))),
            min_value=earliest, max_value=latest, key="cmp_b",
        )

        df1 = _ds(date1, date1, area=area)
        df2 = _ds(date2, date2, area=area)

        if df1.empty or df2.empty:
            st.warning("Data not available for one or both dates.")
        else:
            df1["time_of_day"] = pd.to_datetime(df1["time"], format="%H:%M")
            df2["time_of_day"] = pd.to_datetime(df2["time"], format="%H:%M")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df1["time_of_day"], y=df1["area_demand_mw"],
                name=str(date1), mode="lines",
            ))
            fig.add_trace(go.Scatter(
                x=df2["time_of_day"], y=df2["area_demand_mw"],
                name=str(date2), mode="lines",
            ))
            fig.update_layout(
                title="Demand Comparison (MW)", height=400, xaxis_tickformat="%H:%M"
            )
            st.plotly_chart(fig, width="stretch")

    # ── TRENDS ────────────────────────────────────────────────────────────
    elif tab_choice == "Trends":
        st.header(f"{AREA_NAMES[area]} \u2014 Trends (Rolling)")
        start_date, end_date = _date_range_picker("trends", default="1M", area=area)
        st.caption(f"Range: **{start_date}** \u2192 **{end_date}**")

        df = _ds(start_date, end_date, area=area)
        jepx_df = _jepx_area(area, start_date, end_date)

        if not df.empty:
            daily = df.groupby("date").agg(
                peak=("area_demand_mw", "max"),
                avg=("area_demand_mw", "mean"),
            ).reset_index()
            daily["date"] = pd.to_datetime(daily["date"])
            fig = px.line(daily, x="date", y=["peak", "avg"],
                          title="Daily Peak & Average Demand (MW)")
            fig.update_layout(height=350)
            st.plotly_chart(fig, width="stretch")

            re_cols = ["hydro", "geothermal", "biomass", "solar_actual", "wind_actual"]
            df["re_total"] = df[re_cols].sum(axis=1)
            daily_re = df.groupby("date").agg(
                re_sum=("re_total", "sum"),
                total=("total_supply", "sum"),
            ).reset_index()
            daily_re["re_pct"] = daily_re["re_sum"] / daily_re["total"] * 100
            daily_re["date"] = pd.to_datetime(daily_re["date"])
            fig2 = px.line(daily_re, x="date", y="re_pct",
                           title="Daily Renewable Share (%)")
            fig2.update_layout(height=300)
            st.plotly_chart(fig2, width="stretch")

        if not jepx_df.empty:
            daily_price = jepx_df.groupby("date").agg(
                avg_price=("price", "mean"),
                max_price=("price", "max"),
            ).reset_index()
            daily_price["date"] = pd.to_datetime(daily_price["date"])
            fig3 = px.line(daily_price, x="date", y=["avg_price", "max_price"],
                           title=f"JEPX {AREA_NAMES[area]} Daily Avg & Peak (¥/kWh)")
            fig3.update_layout(height=350)
            st.plotly_chart(fig3, width="stretch")

        # Demand vs price overlay (dual y-axis) when both signals are present
        if not df.empty and not jepx_df.empty:
            daily_demand = df.groupby("date").agg(
                avg_demand=("area_demand_mw", "mean"),
            ).reset_index()
            daily_demand["date"] = pd.to_datetime(daily_demand["date"])
            daily_pr = jepx_df.groupby("date")["price"].mean().reset_index()
            daily_pr["date"] = pd.to_datetime(daily_pr["date"])
            merged = daily_demand.merge(daily_pr, on="date", how="inner")
            if not merged.empty:
                fig_dp = go.Figure()
                fig_dp.add_trace(go.Scatter(
                    x=merged["date"], y=merged["avg_demand"],
                    name="Avg Demand (MW)", mode="lines", yaxis="y1",
                ))
                fig_dp.add_trace(go.Scatter(
                    x=merged["date"], y=merged["price"],
                    name="Avg Price (¥/kWh)", mode="lines", yaxis="y2",
                    line=dict(color="crimson"),
                ))
                fig_dp.update_layout(
                    title=f"Demand vs JEPX Price — {AREA_NAMES[area]} (Daily Avg)",
                    height=380,
                    yaxis=dict(title="Demand (MW)"),
                    yaxis2=dict(title="Price (¥/kWh)", overlaying="y", side="right"),
                    legend=dict(orientation="h", y=-0.2),
                )
                st.plotly_chart(fig_dp, width="stretch")

                # Scatter (demand vs price) with simple correlation
                corr = merged["avg_demand"].corr(merged["price"])
                fig_sc = px.scatter(
                    merged, x="avg_demand", y="price",
                    title=f"Demand ↔ Price scatter (Pearson r = {corr:.2f})",
                    labels={"avg_demand": "Avg Demand (MW)", "price": "Avg Price (¥/kWh)"},
                )
                fig_sc.update_layout(height=340)
                st.plotly_chart(fig_sc, width="stretch")

    # ── DRIVERS ───────────────────────────────────────────────────────────
    elif tab_choice == "Drivers":
        st.header("Price Drivers — Fuels & Correlations")
        start_date, end_date = _date_range_picker("drivers", default="3M", area=area)
        st.caption(f"Range: **{start_date}** \u2192 **{end_date}**")

        fuels_df = _fuels(start_date, end_date)
        jepx_df = _jepx_area(area, start_date, end_date)

        if not fuels_df.empty:
            fuels_df["date"] = pd.to_datetime(fuels_df["date"])
            fig = px.line(fuels_df, x="date", y="close", color="ticker",
                          title="Commodity Prices (Daily Close)")
            fig.update_layout(height=400)
            st.plotly_chart(fig, width="stretch")

        if not jepx_df.empty and not fuels_df.empty:
            daily_price = jepx_df.groupby("date")["price"].mean().reset_index()
            daily_price.columns = ["date", "jepx_avg"]
            daily_price["date"] = pd.to_datetime(daily_price["date"])

            brent = fuels_df[fuels_df["ticker"] == "BZ=F"][["date", "close"]].copy()
            brent.columns = ["date", "brent"]

            merged = daily_price.merge(brent, on="date", how="inner")
            if not merged.empty:
                fig2 = px.scatter(
                    merged, x="brent", y="jepx_avg",
                    title=f"JEPX {AREA_NAMES[area]} vs Brent Crude",
                    labels={"brent": "Brent (USD/bbl)", "jepx_avg": "JEPX Avg (¥/kWh)"},
                )
                fig2.update_layout(height=350)
                st.plotly_chart(fig2, width="stretch")

    # ── AREAS COMPARE ─────────────────────────────────────────────────────
    elif tab_choice == "Areas Compare":
        st.header("Multi-Area Comparison")
        selected = st.multiselect(
            "Areas to overlay",
            options=list(AREA_NAMES.keys()),
            default=["tepco", "kansai", "kyushu"],
            format_func=lambda a: AREA_NAMES[a],
        )
        start_date, end_date = _date_range_picker("areas_cmp", default="1M", area=area)
        st.caption(f"Range: **{start_date}** → **{end_date}**")

        if not selected:
            st.info("Select at least one area.")
        else:
            # Combined daily-peak demand overlay
            frames = []
            for a in selected:
                d = _ds(start_date, end_date, area=a)
                if d.empty:
                    continue
                daily = d.groupby("date").agg(peak=("area_demand_mw", "max"),
                                              avg=("area_demand_mw", "mean")).reset_index()
                daily["area"] = AREA_NAMES[a]
                daily["date"] = pd.to_datetime(daily["date"])
                frames.append(daily)
            if not frames:
                st.warning("No data for selected areas / range.")
            else:
                combo = pd.concat(frames, ignore_index=True)
                fig = px.line(combo, x="date", y="peak", color="area",
                              title="Daily Peak Demand by Area (MW)")
                fig.update_layout(height=400)
                st.plotly_chart(fig, width="stretch")

                fig2 = px.line(combo, x="date", y="avg", color="area",
                               title="Daily Average Demand by Area (MW)")
                fig2.update_layout(height=350)
                st.plotly_chart(fig2, width="stretch")

            # Renewable share comparison
            re_frames = []
            re_cols = ["hydro", "geothermal", "biomass", "solar_actual", "wind_actual"]
            for a in selected:
                d = _ds(start_date, end_date, area=a)
                if d.empty or "total_supply" not in d.columns:
                    continue
                avail = [c for c in re_cols if c in d.columns]
                if not avail:
                    continue
                d["re_total"] = d[avail].sum(axis=1, min_count=1)
                day = d.groupby("date").agg(re_sum=("re_total", "sum"),
                                            tot=("total_supply", "sum")).reset_index()
                day["re_pct"] = day["re_sum"] / day["tot"] * 100
                day["area"] = AREA_NAMES[a]
                day["date"] = pd.to_datetime(day["date"])
                re_frames.append(day[["date", "re_pct", "area"]])
            if re_frames:
                rcombo = pd.concat(re_frames, ignore_index=True)
                fig3 = px.line(rcombo, x="date", y="re_pct", color="area",
                               title="Daily Renewable Share by Area (%)")
                fig3.update_layout(height=350)
                st.plotly_chart(fig3, width="stretch")

            # JEPX per-area price comparison
            price_frames = []
            for a in selected:
                p = _jepx_area(a, start_date, end_date)
                if p.empty:
                    continue
                day = p.groupby("date")["price"].mean().reset_index()
                day["area"] = AREA_NAMES[a]
                day["date"] = pd.to_datetime(day["date"])
                price_frames.append(day)
            if price_frames:
                pcombo = pd.concat(price_frames, ignore_index=True)
                fig4 = px.line(pcombo, x="date", y="price", color="area",
                               title="Daily Avg JEPX Spot Price by Area (¥/kWh)")
                fig4.update_layout(height=350)
                st.plotly_chart(fig4, width="stretch")

            # Data freshness table
            st.subheader("Data freshness")
            freshness = []
            for a in AREA_NAMES:
                b = _data_date_bounds(a)
                freshness.append({
                    "Area": AREA_NAMES[a],
                    "Earliest": b[0] if b else "—",
                    "Latest": b[1] if b else "—",
                    "Days": (b[1] - b[0]).days if b else 0,
                })
            st.dataframe(pd.DataFrame(freshness), width="stretch", hide_index=True)

    # ── ANALYSES ──────────────────────────────────────────────────────────
    elif tab_choice == "Analyses":
        st.header("Daily Analysis History")
        analyses_df = _analyses()

        if analyses_df.empty:
            st.info("No analyses recorded yet. Run `repower analyze` to generate.")
        else:
            for _, row in analyses_df.iterrows():
                with st.expander(f"📊 {row['date']}"):
                    if row.get("narrative_md"):
                        st.markdown(row["narrative_md"])
                    if row.get("features_json"):
                        features = json.loads(row["features_json"])
                        st.json(features)
