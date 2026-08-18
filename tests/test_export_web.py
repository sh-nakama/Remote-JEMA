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
from repower.timeutil import today_jst


def test_anchor_date_picks_latest():
    assert _anchor_date({"supply": "2026-07-31", "area_price": "2026-07-04"}) == date(2026, 7, 31)


def test_anchor_date_ignores_none():
    assert _anchor_date({"supply": None, "area_price": "2026-06-01"}) == date(2026, 6, 1)


def test_anchor_date_all_none_falls_back_to_today():
    # today_jst(), not date.today(): the exporter anchors on the Japanese market
    # day, so on a UTC runner the two differ for the whole JST 00:00-09:00 window.
    assert _anchor_date({"supply": None, "area_price": None}) == today_jst()


def test_write_json_roundtrip_utf8(tmp_path: Path):
    p = tmp_path / "sub" / "b.json"
    n = _write_json(p, {"x": 1, "ja": "東京"})
    assert p.exists()
    assert n > 0
    assert json.loads(p.read_text(encoding="utf-8")) == {"x": 1, "ja": "東京"}


def test_write_json_nan_becomes_null(tmp_path: Path):
    """Pandas NaN/Inf must serialize as null — a literal ``NaN`` token is invalid
    strict JSON and makes the browser's res.json() throw (silent fixture fallback)."""
    p = tmp_path / "nan.json"
    _write_json(p, {"rows": [{"v": float("nan")}, {"v": float("inf")}, {"v": 1.5}], "t": ("a", float("nan"))})
    text = p.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text) == {"rows": [{"v": None}, {"v": None}, {"v": 1.5}], "t": ["a", None]}


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


def test_build_policy_snapshot_synthesis_rollup_and_discovered(tmp_path: Path):
    """The Policy Deep Dive payload carries committee-level synthesis + a done/pending/
    error rollup, exports done meetings with a digest, and includes a discovered
    committee that flips to tracked once enabled."""
    from repower.dashboard.export_web import build_policy_snapshot
    from repower.policy import store
    from repower.policy.scraper import Material

    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)  # config committees, tracked by default

    # A config committee with one summarised meeting + a committee-level synthesis.
    store.record_meeting(
        "emissions_trading", 5,
        [Material(5, "005_min", "https://x/5_gijiroku.pdf", "議事録", "minutes")],
        db_path=db,
    )
    pend = store.pending_meetings("emissions_trading", db_path=db)
    store.update_meeting(
        pend[0]["id"], db_path=db, state="done", briefing_md="## 論点\n概要。",
        digest_en_json='{"answer": "Lead paragraph [1].\\n\\n### Key\\n* a decision [2]."}',
    )
    store.update_committee(
        "emissions_trading", db_path=db,
        running_digest_en_md="# Overview\n\n- point one", running_summary_md="## 総括\n・要点",
        last_synth_meeting=5,
    )

    # A discovered committee (not in config), left untracked.
    store.upsert_discovered_committees(
        [{"key": "gx_demand", "name_ja": "GX需要創出に向けた研究会", "source": "METI",
          "url": "https://www.meti.go.jp/shingikai/energy_environment/gx_demand/"}],
        db_path=db,
    )

    snap = build_policy_snapshot(db)
    assert set(snap) == {"committees", "meetings", "upcoming"}
    by = {c["key"]: c for c in snap["committees"]}

    et = by["emissions_trading"]
    assert et["tracked"] is True and et["done"] == 1 and et["pending"] == 0
    assert et["synthesisEn"].startswith("# Overview")
    assert et["synthesisJa"] and et["lastSynth"] == 5

    gx = by["gx_demand"]
    assert gx["discovered"] is True and gx["tracked"] is False
    assert gx["synthesisEn"] is None and gx["done"] == 0

    # the summarised meeting is exported with a parsed digest
    et_meetings = [m for m in snap["meetings"] if m["com"] == "emissions_trading"]
    assert any(m["status"] == "done" and m.get("digest") for m in et_meetings)

    # tracking the discovered committee flips its exported flag
    store.set_committee_enabled("gx_demand", True, db_path=db)
    assert {c["key"]: c for c in build_policy_snapshot(db)["committees"]}["gx_demand"]["tracked"] is True


def test_build_policy_status_keeps_failures_and_trims_quiet_backlog(tmp_path: Path):
    """The status payload keeps every errored/mid-flight meeting whatever the cap,
    trims only the quiet `detected` backlog (reporting how much it dropped), and
    carries the recorded failure message through to the UI."""
    from repower.dashboard import export_web
    from repower.dashboard.export_web import build_policy_status
    from repower.policy import store
    from repower.policy.scraper import Material

    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)

    # One failure, one meeting stranded mid-pipeline, and a pending backlog that
    # overflows the cap.
    store.record_meeting("emissions_trading", 1, [
        Material(1, "001_min", "https://x/1.pdf", "議事録", "minutes")], db_path=db)
    store.record_meeting("emissions_trading", 2, None, db_path=db)
    for n in range(3, 3 + export_web.STATUS_MEETINGS_PER_COMMITTEE + 4):
        store.record_meeting("emissions_trading", n, None, db_path=db)

    by_num = {m["meeting_num"]: m["id"] for m in store.pending_meetings("emissions_trading", db_path=db)}
    store.update_meeting(by_num[1], db_path=db, state="error", quality_flag="download_blocked",
                         last_error="2 document(s) could not be downloaded (blocked_403)")
    store.update_meeting(by_num[2], db_path=db, state="generating")

    out = build_policy_status(db)
    mine = [m for m in out["meetings"] if m["com"] == "emissions_trading"]
    assert len(mine) == export_web.STATUS_MEETINGS_PER_COMMITTEE

    err = next(m for m in mine if m["num"] == 1)
    assert err["state"] == "error" and err["flag"] == "download_blocked"
    assert "blocked_403" in err["error"]
    # The raw lifecycle state survives — the Deep Dive payload would say "pending".
    assert next(m for m in mine if m["num"] == 2)["state"] == "generating"
    # …and what was trimmed is reported rather than silently dropped: CAP+4
    # detected meetings competing for the CAP-2 slots the two pinned rows leave.
    assert out["truncated"]["emissions_trading"] == 6
    assert all(m["state"] == "detected" for m in mine if m["num"] not in (1, 2))


def test_committees_payload_reports_last_pipeline_event(tmp_path: Path):
    """Each committee row carries its newest meeting-level event — the field the
    status table sorts on — and a committee nothing has run for reports None."""
    from repower.dashboard.export_web import build_policy_catalog
    from repower.policy import store

    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.record_meeting("emissions_trading", 4, None, db_path=db)
    store.record_meeting("emissions_trading", 5, None, db_path=db)
    by_num = {m["meeting_num"]: m["id"] for m in store.pending_meetings("emissions_trading", db_path=db)}
    store.update_meeting(by_num[4], db_path=db, state="done")
    # Touched last, so this is the event the row must report — not the higher number.
    store.update_meeting(by_num[5], db_path=db, state="error", quality_flag="no_sources",
                         last_error="No usable source documents")

    by = {c["key"]: c for c in build_policy_catalog(db)}
    et = by["emissions_trading"]
    assert et["lastUpdateNum"] == 5
    assert et["lastUpdateState"] == "error" and et["lastUpdateFlag"] == "no_sources"
    assert et["lastUpdateError"] == "No usable source documents"
    assert et["lastUpdateAt"]

    quiet = next(c for c in by.values() if c["key"] != "emissions_trading")
    assert quiet["lastUpdateAt"] is None and quiet["lastUpdateState"] is None


def test_slot_col_fills_missing_slots_with_none():
    # pivot with a couple of the 48 slots present; the rest must come back None
    piv = pd.DataFrame({"2026-07-04": [10.0, 12.5]}, index=["00:00", "14:30"])
    col = _slot_col(piv, "2026-07-04")
    assert len(col) == 48
    assert col[0] == 10.0
    assert col[29] == 12.5
    assert col[1] is None  # 00:30 absent
    assert _slot_col(piv, "2099-01-01") == [None] * 48  # unknown day
