"""Unit tests for the web-snapshot exporter (pure helpers only — no DB/network,
so they run in CI without the data files)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from repower.dashboard.export_web import (
    AREAS,
    LEVELS,
    SLOTS,
    _anchor_date,
    _slot_col,
    _write_json,
)


def test_anchor_date_picks_latest():
    assert _anchor_date({"supply": "2026-07-31", "area_price": "2026-07-04"}) == date(2026, 7, 31)


def test_anchor_date_ignores_none():
    assert _anchor_date({"supply": None, "area_price": "2026-06-01"}) == date(2026, 6, 1)


def test_anchor_date_all_none_falls_back_to_today():
    assert _anchor_date({"supply": None, "area_price": None}) == date.today()


def test_write_json_roundtrip_utf8(tmp_path: Path):
    p = tmp_path / "sub" / "b.json"
    n = _write_json(p, {"x": 1, "ja": "東京"})
    assert p.exists()
    assert n > 0
    assert json.loads(p.read_text(encoding="utf-8")) == {"x": 1, "ja": "東京"}


def test_area_and_level_shape():
    assert len(AREAS) == 9
    assert "tepco" in AREAS  # Tokyo slug
    assert set(LEVELS) == {"Native", "Daily", "Weekly", "Monthly"}


def test_slots_are_48_halfhour_labels():
    assert len(SLOTS) == 48
    assert SLOTS[0] == "00:00"
    assert SLOTS[29] == "14:30"
    assert SLOTS[-1] == "23:30"


def test_slot_col_fills_missing_slots_with_none():
    # pivot with a couple of the 48 slots present; the rest must come back None
    piv = pd.DataFrame({"2026-07-04": [10.0, 12.5]}, index=["00:00", "14:30"])
    col = _slot_col(piv, "2026-07-04")
    assert len(col) == 48
    assert col[0] == 10.0
    assert col[29] == 12.5
    assert col[1] is None  # 00:30 absent
    assert _slot_col(piv, "2099-01-01") == [None] * 48  # unknown day
