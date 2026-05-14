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
    JepxSpot30m,
    get_session,
    init_db,
)


# ── Data loaders (cached per DB session) ──────────────────────────────────

@st.cache_resource
def _db_session():
    init_db()
    return get_session()


def _ds(start: date, end: date) -> pd.DataFrame:
    session = _db_session()
    rows = session.execute(
        select(DemandSupply30m).where(
            and_(DemandSupply30m.date >= start, DemandSupply30m.date <= end)
        )
    ).scalars().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in DemandSupply30m.__table__.columns} for r in rows]
    )
    df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"])
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
    return pd.DataFrame(
        [{c.name: getattr(r, c.name) for c in FuelDaily.__table__.columns} for r in rows]
    )


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
    st.sidebar.caption(f"DB: `{DB_PATH}`")

    tab_choice = st.sidebar.radio(
        "View",
        ["Today", "Compare", "Trends", "Drivers", "Analyses"],
    )

    # ── TODAY ─────────────────────────────────────────────────────────────
    if tab_choice == "Today":
        st.header("Today's Supply & Demand")
        target = st.date_input("Date", value=date.today() - timedelta(days=1))
        df = _ds(target, target)
        jepx_df = _jepx(target, target)

        if df.empty:
            st.warning("No TEPCO data available for this date.")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric("Peak Demand", f"{int(df['area_demand_mw'].max()):,} MW")
            col2.metric("Min Demand", f"{int(df['area_demand_mw'].min()):,} MW")
            col3.metric("Avg Demand", f"{int(df['area_demand_mw'].mean()):,} MW")

            fig = px.line(df, x="datetime", y="area_demand_mw", title="Area Demand (MW)")
            fig.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

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
            st.plotly_chart(fig2, use_container_width=True)

            totals = {col: df[col].sum() for col in available}
            fig3 = px.pie(
                names=[c.replace("_", " ").title() for c in totals],
                values=list(totals.values()),
                title="Generation Mix (%)",
                hole=0.4,
            )
            fig3.update_layout(height=350)
            st.plotly_chart(fig3, use_container_width=True)

        if not jepx_df.empty:
            st.subheader("JEPX Spot Price — Tokyo Area")
            col1, col2 = st.columns(2)
            col1.metric("Avg Price", f"¥{jepx_df['tokyo_area_price'].mean():.2f}/kWh")
            col2.metric("Peak Price", f"¥{jepx_df['tokyo_area_price'].max():.2f}/kWh")
            fig4 = px.line(jepx_df, x="datetime", y="tokyo_area_price", title="Spot Price (¥/kWh)")
            fig4.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig4, use_container_width=True)

    # ── COMPARE ───────────────────────────────────────────────────────────
    elif tab_choice == "Compare":
        st.header("Compare Two Days")
        col1, col2 = st.columns(2)
        date1 = col1.date_input("Date A", value=date.today() - timedelta(days=1))
        date2 = col2.date_input("Date B", value=date.today() - timedelta(days=8))

        df1 = _ds(date1, date1)
        df2 = _ds(date2, date2)

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
            st.plotly_chart(fig, use_container_width=True)

    # ── TRENDS ────────────────────────────────────────────────────────────
    elif tab_choice == "Trends":
        st.header("Trends (Rolling)")
        days = st.slider("Days back", 7, 90, 30)
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        df = _ds(start_date, end_date)
        jepx_df = _jepx(start_date, end_date)

        if not df.empty:
            daily = df.groupby("date").agg(
                peak=("area_demand_mw", "max"),
                avg=("area_demand_mw", "mean"),
            ).reset_index()
            daily["date"] = pd.to_datetime(daily["date"])
            fig = px.line(daily, x="date", y=["peak", "avg"],
                          title="Daily Peak & Average Demand (MW)")
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

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
            st.plotly_chart(fig2, use_container_width=True)

        if not jepx_df.empty:
            daily_price = jepx_df.groupby("date").agg(
                avg_price=("tokyo_area_price", "mean"),
                max_price=("tokyo_area_price", "max"),
            ).reset_index()
            daily_price["date"] = pd.to_datetime(daily_price["date"])
            fig3 = px.line(daily_price, x="date", y=["avg_price", "max_price"],
                           title="JEPX Tokyo Daily Avg & Peak (¥/kWh)")
            fig3.update_layout(height=350)
            st.plotly_chart(fig3, use_container_width=True)

    # ── DRIVERS ───────────────────────────────────────────────────────────
    elif tab_choice == "Drivers":
        st.header("Price Drivers — Fuels & Correlations")
        days = st.slider("Days back", 7, 90, 30, key="drivers_days")
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        fuels_df = _fuels(start_date, end_date)
        jepx_df = _jepx(start_date, end_date)

        if not fuels_df.empty:
            fuels_df["date"] = pd.to_datetime(fuels_df["date"])
            fig = px.line(fuels_df, x="date", y="close", color="ticker",
                          title="Commodity Prices (Daily Close)")
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)

        if not jepx_df.empty and not fuels_df.empty:
            daily_price = jepx_df.groupby("date")["tokyo_area_price"].mean().reset_index()
            daily_price.columns = ["date", "jepx_avg"]
            daily_price["date"] = pd.to_datetime(daily_price["date"])

            brent = fuels_df[fuels_df["ticker"] == "BZ=F"][["date", "close"]].copy()
            brent.columns = ["date", "brent"]

            merged = daily_price.merge(brent, on="date", how="inner")
            if not merged.empty:
                fig2 = px.scatter(
                    merged, x="brent", y="jepx_avg",
                    title="JEPX Tokyo vs Brent Crude",
                    labels={"brent": "Brent (USD/bbl)", "jepx_avg": "JEPX Avg (¥/kWh)"},
                )
                fig2.update_layout(height=350)
                st.plotly_chart(fig2, use_container_width=True)

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
