"""Unit tests for repower.scrapers.area_base pure parsing logic.

No network access: all inputs are synthetic pandas DataFrames built in-memory.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from repower.scrapers.area_base import (
    BaseAreaScraper,
    _normalize_hhmm,
    hourly_to_30min,
)


# ---------------------------------------------------------------------------
# _normalize_hhmm
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("9:00", "09:00"),
        ("09:00", "09:00"),
        ("0900", "09:00"),
        ("24:00", "24:00"),
        ("", None),
        ("nan", None),
    ],
)
def test_normalize_hhmm(raw, expected):
    assert _normalize_hhmm(raw) == expected


# ---------------------------------------------------------------------------
# hourly_to_30min
# ---------------------------------------------------------------------------
def test_hourly_to_30min_expands_and_sorts():
    df = pd.DataFrame(
        {
            "date": [date(2024, 1, 1), date(2024, 1, 1)],
            "time": ["09:00", "10:00"],
            "area_demand_mw": [100.0, 200.0],
        }
    )
    out = hourly_to_30min(df)

    # 2 hourly rows -> 4 half-hourly rows
    assert len(out) == 4
    # Sorted by (date, time) with the new :30 slots interleaved
    assert list(out["time"]) == ["09:00", "09:30", "10:00", "10:30"]
    # Values are duplicated from their source hour
    by_time = dict(zip(out["time"], out["area_demand_mw"]))
    assert by_time["09:00"] == 100.0
    assert by_time["09:30"] == 100.0
    assert by_time["10:00"] == 200.0
    assert by_time["10:30"] == 200.0


def test_hourly_to_30min_empty():
    df = pd.DataFrame({"date": [], "time": [], "area_demand_mw": []})
    out = hourly_to_30min(df)
    assert out.empty


# ---------------------------------------------------------------------------
# BaseAreaScraper.parse — 24:00 rollover
# ---------------------------------------------------------------------------
class _ThreeColScraper(BaseAreaScraper):
    AREA = "test3"
    COLUMN_ORDERS_BY_NCOLS = {3: ["date", "time", "area_demand_mw"]}


def test_parse_2400_rollover_to_next_day():
    df = pd.DataFrame(
        [
            ["2024/1/1", "23:00", 100],
            ["2024/1/1", "24:00", 150],
        ],
        columns=["c0", "c1", "c2"],
    )
    out = _ThreeColScraper().parse(df)

    # Both rows survive
    assert len(out) == 2
    rows = {(r["date"], r["time"]): r["area_demand_mw"] for _, r in out.iterrows()}

    # The 23:00 row stays on the original day
    assert rows[(date(2024, 1, 1), "23:00")] == 100.0
    # The 24:00 row rolls over to 00:00 of the next day
    assert (date(2024, 1, 2), "00:00") in rows
    assert rows[(date(2024, 1, 2), "00:00")] == 150.0
    # And there is no leftover "24:00" time anywhere
    assert "24:00" not in set(out["time"])


# ---------------------------------------------------------------------------
# BaseAreaScraper.parse — column-count selection
# ---------------------------------------------------------------------------
class _MultiFormatScraper(BaseAreaScraper):
    AREA = "testmulti"
    COLUMN_ORDERS_BY_NCOLS = {
        3: ["date", "time", "area_demand_mw"],
        4: ["date", "time", "skip", "area_demand_mw"],
    }


def test_parse_selects_3col_order():
    df = pd.DataFrame(
        [["2024/1/1", "09:00", 100]],
        columns=["a", "b", "c"],
    )
    out = _MultiFormatScraper().parse(df)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["date"] == date(2024, 1, 1)
    assert row["time"] == "09:00"
    assert row["area_demand_mw"] == 100.0


def test_parse_selects_4col_order_with_skip():
    # 4-column layout: the third column is "skip" and must be ignored, while the
    # 4th column carries area_demand_mw.
    df = pd.DataFrame(
        [["2024/1/1", "09:00", "GARBAGE", 250]],
        columns=["a", "b", "c", "d"],
    )
    out = _MultiFormatScraper().parse(df)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["date"] == date(2024, 1, 1)
    assert row["time"] == "09:00"
    # The 4th column maps to demand; the skipped 3rd column must not leak in.
    assert row["area_demand_mw"] == 250.0
    assert "GARBAGE" not in set(out.columns)
