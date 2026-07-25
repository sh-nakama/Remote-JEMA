"""Unit tests for the pure aggregate() helper in repower.dashboard.read.

Network-free and DB-free: aggregate() and the reducer inference operate on
synthetic in-memory DataFrames only. The cached load_* functions are not
exercised here (they require a DB + Streamlit runtime).
"""

from __future__ import annotations

import pandas as pd
import pytest

from repower.dashboard.read import (
    aggregate,
    build_reducer_map,
    default_reducer_for,
)

# ── Reducer inference (plan §B table) ──────────────────────────────────────

def test_default_reducer_inference():
    # MW flows / generation mix / avg price / counts -> mean
    assert default_reducer_for("area_demand_mw") == "mean"
    assert default_reducer_for("solar_actual") == "mean"
    assert default_reducer_for("contracted_mw") == "mean"
    assert default_reducer_for("bid_volume_mw") == "mean"
    assert default_reducer_for("price") == "mean"
    assert default_reducer_for("price_avg") == "mean"
    assert default_reducer_for("bids_count") == "mean"
    assert default_reducer_for("contracted_count") == "mean"
    # price_max / price_min -> max / min
    assert default_reducer_for("price_max") == "max"
    assert default_reducer_for("price_min") == "min"
    # tieline limits -> max ; reserved -> mean
    assert default_reducer_for("upper_limit_fwd") == "max"
    assert default_reducer_for("upper_limit_rev") == "max"
    assert default_reducer_for("reserved_fwd") == "mean"
    assert default_reducer_for("reserved_rev") == "mean"


def test_build_reducer_map_skips_keys():
    cols = ["datetime", "area", "price", "price_max", "id", "block_num"]
    m = build_reducer_map(cols)
    assert m == {"price": "mean", "price_max": "max"}


# ── Native passthrough ─────────────────────────────────────────────────────

def test_native_returns_unchanged():
    df = pd.DataFrame({
        "datetime": pd.to_datetime(["2025-01-01 00:00", "2025-01-01 00:30"]),
        "price": [10.0, 20.0],
    })
    out = aggregate(df, "Native")
    pd.testing.assert_frame_equal(out, df)


def test_unknown_level_raises():
    df = pd.DataFrame({"datetime": pd.to_datetime(["2025-01-01"]), "price": [1.0]})
    with pytest.raises(ValueError):
        aggregate(df, "Hourly")


# ── Daily bucketing: verify mean/max/min per column ────────────────────────

def _two_day_frame():
    # Day 1: 4 half-hour samples; Day 2: 2 samples.
    dts = pd.to_datetime([
        "2025-01-01 00:00", "2025-01-01 06:00",
        "2025-01-01 12:00", "2025-01-01 18:00",
        "2025-01-02 00:00", "2025-01-02 12:00",
    ])
    return pd.DataFrame({
        "datetime": dts,
        "area_demand_mw": [100.0, 200.0, 300.0, 400.0, 10.0, 30.0],   # mean
        "price_max":      [5.0, 9.0, 7.0, 2.0, 1.0, 8.0],             # max
        "price_min":      [5.0, 9.0, 7.0, 2.0, 1.0, 8.0],             # min
    })


def test_daily_bucketing_and_reducers():
    df = _two_day_frame()
    out = aggregate(df, "Daily")

    # Two daily buckets.
    assert len(out) == 2
    assert list(out["datetime"]) == list(pd.to_datetime(["2025-01-01", "2025-01-02"]))

    # mean for MW flow.
    assert out.loc[0, "area_demand_mw"] == pytest.approx(250.0)   # (100+200+300+400)/4
    assert out.loc[1, "area_demand_mw"] == pytest.approx(20.0)    # (10+30)/2

    # max for price_max.
    assert out.loc[0, "price_max"] == pytest.approx(9.0)
    assert out.loc[1, "price_max"] == pytest.approx(8.0)

    # min for price_min.
    assert out.loc[0, "price_min"] == pytest.approx(2.0)
    assert out.loc[1, "price_min"] == pytest.approx(1.0)


def test_explicit_reducer_override():
    df = _two_day_frame()
    # Force area_demand_mw to be summed instead of meaned.
    out = aggregate(df, "Daily", reducers={"area_demand_mw": "sum"})
    assert out.loc[0, "area_demand_mw"] == pytest.approx(1000.0)
    assert out.loc[1, "area_demand_mw"] == pytest.approx(40.0)


# ── Weekly bucketing (ISO week start = Monday) ─────────────────────────────

def test_weekly_bucketing():
    # 2025-01-01 is a Wednesday (ISO week of Mon 2024-12-30).
    # 2025-01-06 is the next Monday (new ISO week).
    dts = pd.to_datetime([
        "2025-01-01", "2025-01-02", "2025-01-05",  # week of 2024-12-30
        "2025-01-06", "2025-01-08",                # week of 2025-01-06
    ])
    df = pd.DataFrame({"datetime": dts, "price": [10.0, 20.0, 30.0, 100.0, 200.0]})
    out = aggregate(df, "Weekly")

    assert len(out) == 2
    assert list(out["datetime"]) == list(pd.to_datetime(["2024-12-30", "2025-01-06"]))
    assert out.loc[0, "price"] == pytest.approx(20.0)   # (10+20+30)/3
    assert out.loc[1, "price"] == pytest.approx(150.0)  # (100+200)/2


# ── Monthly bucketing (month start) ────────────────────────────────────────

def test_monthly_bucketing():
    dts = pd.to_datetime([
        "2025-01-05", "2025-01-20", "2025-01-31",
        "2025-02-10", "2025-02-15",
        "2025-03-01",
    ])
    df = pd.DataFrame({"datetime": dts, "area_demand_mw": [1.0, 2.0, 3.0, 10.0, 20.0, 100.0]})
    out = aggregate(df, "Monthly")

    assert len(out) == 3
    assert list(out["datetime"]) == list(
        pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"])
    )
    assert out.loc[0, "area_demand_mw"] == pytest.approx(2.0)    # (1+2+3)/3
    assert out.loc[1, "area_demand_mw"] == pytest.approx(15.0)   # (10+20)/2
    assert out.loc[2, "area_demand_mw"] == pytest.approx(100.0)


# ── Per-series grouping via group_extra ────────────────────────────────────

def test_group_extra_keeps_series_separate():
    dts = pd.to_datetime([
        "2025-01-01 00:00", "2025-01-01 12:00",
        "2025-01-01 00:00", "2025-01-01 12:00",
    ])
    df = pd.DataFrame({
        "datetime": dts,
        "pair": ["A", "A", "B", "B"],
        "upper_limit_fwd": [10.0, 30.0, 5.0, 7.0],   # max
        "reserved_fwd": [10.0, 30.0, 5.0, 7.0],      # mean
    })
    out = aggregate(df, "Daily", build_reducer_map(df.columns), group_extra=["pair"])

    assert len(out) == 2  # one per pair
    a = out[out["pair"] == "A"].iloc[0]
    b = out[out["pair"] == "B"].iloc[0]
    assert a["upper_limit_fwd"] == pytest.approx(30.0)  # max
    assert a["reserved_fwd"] == pytest.approx(20.0)     # mean (10+30)/2
    assert b["upper_limit_fwd"] == pytest.approx(7.0)
    assert b["reserved_fwd"] == pytest.approx(6.0)      # (5+7)/2


# ── missing_mw must be derived POST-aggregation ────────────────────────────

def test_missing_mw_derived_after_aggregation():
    """missing_mw = agg(demand) - agg(contracted), NOT agg(demand - contracted).

    With mean reducers these happen to coincide, so we use a reducer mix that
    makes the two orders diverge: demand summed, contracted meaned. The
    load_balancing_grid contract derives missing_mw on the aggregated frame.
    """
    dts = pd.to_datetime([
        "2025-01-01 00:00", "2025-01-01 12:00",
        "2025-01-02 00:00", "2025-01-02 12:00",
    ])
    df = pd.DataFrame({
        "datetime": dts,
        "demand_mw":     [100.0, 100.0, 50.0, 50.0],
        "contracted_mw": [60.0, 80.0, 40.0, 20.0],
    })

    # Aggregate first (the layer's contract), then derive missing_mw.
    agg = aggregate(df, "Daily", reducers={"demand_mw": "sum", "contracted_mw": "mean"})
    agg["missing_mw"] = agg["demand_mw"] - agg["contracted_mw"]

    # Day 1: demand sum=200, contracted mean=70 -> missing=130
    # Day 2: demand sum=100, contracted mean=30 -> missing=70
    assert agg.loc[0, "missing_mw"] == pytest.approx(130.0)
    assert agg.loc[1, "missing_mw"] == pytest.approx(70.0)

    # Contrast: aggregating the per-row difference would give a DIFFERENT result.
    df2 = df.copy()
    df2["row_missing"] = df2["demand_mw"] - df2["contracted_mw"]
    wrong = aggregate(df2[["datetime", "row_missing"]], "Daily",
                      reducers={"row_missing": "sum"})
    # row_missing sum day1 = (40+20)=60 != 130; confirms order matters.
    assert wrong.loc[0, "row_missing"] == pytest.approx(60.0)
    assert wrong.loc[0, "row_missing"] != pytest.approx(agg.loc[0, "missing_mw"])


def test_daily_mean_missing_mw_matches_either_order():
    """Sanity: under pure-mean reducers, both orders agree (linearity of mean)."""
    dts = pd.to_datetime(["2025-01-01 00:00", "2025-01-01 12:00"])
    df = pd.DataFrame({
        "datetime": dts,
        "demand_mw":     [100.0, 200.0],
        "contracted_mw": [60.0, 80.0],
    })
    agg = aggregate(df, "Daily", build_reducer_map(df.columns))
    agg["missing_mw"] = agg["demand_mw"] - agg["contracted_mw"]
    # mean demand=150, mean contracted=70 -> 80
    assert agg.loc[0, "missing_mw"] == pytest.approx(80.0)


def test_empty_frame_passthrough():
    empty = pd.DataFrame(columns=["datetime", "price"])
    out = aggregate(empty, "Daily")
    assert out.empty
