"""Unit tests for the web-snapshot exporter (pure helpers only — no DB/network,
so they run in CI without the data files)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from repower.dashboard.export_web import (
    AREAS,
    BALANCING_PRODUCTS,
    LEVELS,
    PAIR_TO_IC,
    SLOTS,
    _anchor_date,
    _doc_name,
    _doc_size,
    _norm_pair,
    _slot_col,
    _write_json,
    parse_briefing,
    parse_digest_answer,
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


def test_balancing_products_are_five_coded():
    codes = [c for c, _ in BALANCING_PRODUCTS]
    assert codes == ["1-0", "2-1", "2-2", "3-1", "3-2"]
    assert ("1-0", "Primary") in BALANCING_PRODUCTS


def test_norm_pair_and_interconnector_mapping():
    # arrow " → " pairs normalise, and the 7 clean lines map to icDef keys
    assert _norm_pair("Hokkaido → Tohoku") == "Hokkaido->Tohoku"
    assert PAIR_TO_IC[_norm_pair("Tokyo → Chubu")] == "fc"
    assert PAIR_TO_IC[_norm_pair("Chugoku → Kyushu")] == "kq"
    # combined-zone pairs have no clean 1:1 line → not mapped (fixture fallback)
    assert _norm_pair("Chubu-Hokuriku → Kansai") not in PAIR_TO_IC


def test_parse_digest_answer_splits_sections_and_strips_markdown():
    answer = (
        "Lead paragraph summarising the meeting [1].\n\n"
        "### Key Decisions\n"
        "*   **Bold label:** decided something with a $\\geq$6h rule [2].\n"
        "*   Second decision.\n\n"
        "### Action Items\n"
        "*   Do the thing [3]."
    )
    secs, lead = parse_digest_answer(answer)
    heads = [s["h"] for s in secs]
    assert heads == ["Summary", "Key Decisions", "Action Items"]
    assert lead.startswith("Lead paragraph")
    # bold markers stripped, LaTeX \geq rendered
    assert "**" not in secs[1]["items"][0]
    assert "≥6h" in secs[1]["items"][0]
    assert len(secs[1]["items"]) == 2


def test_parse_briefing_keeps_title_and_sections():
    md = "# 第100回 テスト委員会\n\n本会合の概要。\n\n## 1. 主要な論点\n・論点A\n・論点B\n\n## 2. 結論\n決定事項。"
    secs, title, lead = parse_briefing(md)
    assert title == "第100回 テスト委員会"
    heads = [s["h"] for s in secs]
    assert "1. 主要な論点" in heads and "2. 結論" in heads
    assert lead  # non-empty preview


def test_doc_size_and_name():
    assert _doc_size("資料1 議事次第（PDF形式：58KB）") == "58 KB"
    assert _doc_size("資料3-1 約定結果（PDF形式：6,197KB）") == "6.1 MB"
    assert _doc_size("no size here") == "—"
    assert _doc_name("資料1　議事次第（PDF形式：58KB）") == "資料1　議事次第"


def test_slot_col_fills_missing_slots_with_none():
    # pivot with a couple of the 48 slots present; the rest must come back None
    piv = pd.DataFrame({"2026-07-04": [10.0, 12.5]}, index=["00:00", "14:30"])
    col = _slot_col(piv, "2026-07-04")
    assert len(col) == 48
    assert col[0] == 10.0
    assert col[29] == 12.5
    assert col[1] is None  # 00:30 absent
    assert _slot_col(piv, "2099-01-01") == [None] * 48  # unknown day
