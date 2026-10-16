"""The `reclassify` command in the Commands pane, its report, and the "update queued"
data the Status table's filter chip reads."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repower import cli, commands
from repower.dashboard import export_web
from repower.policy import pipeline, store
from repower.policy.scraper import Material


# ── Registry entry ───────────────────────────────────────────────────────────
def _known(*keys: str):
    return lambda: set(keys)


def test_reclassify_is_report_only_unless_apply_is_ticked():
    k = _known("system_review")
    assert commands.build_argv("reclassify", {}, k) == ["policy", "reclassify"]
    assert commands.build_argv("reclassify", {"apply": False}, k) == ["policy", "reclassify"]
    assert commands.build_argv("reclassify", {"apply": True}, k) == ["policy", "reclassify", "--apply"]


def test_reclassify_sits_between_materials_and_the_summarising_steps():
    cmd = commands.BY_ID["reclassify"]
    assert cmd.group == commands.BACKFLOW and cmd.level == commands.WRITES
    assert not cmd.needs_notebooklm  # no network, no login
    assert commands.BY_ID["materials"].order < cmd.order < commands.BY_ID["auth"].order
    # The pane draws a backflow command only as a step of the selected flow, so it has to
    # be one — as an optional step of the full flow (it is a maintenance pass, not required).
    full = next(r for r in commands.RECIPES if r.id == "backflow")
    assert "reclassify" in full.steps and "reclassify" in full.optional


def test_reclassify_form_has_one_unticked_checkbox_and_no_committee_scope():
    info = next(c for c in commands.catalog()["commands"] if c["id"] == "reclassify")
    assert [(p["name"], p["kind"], p["default"]) for p in info["params"]] == [("apply", "bool", False)]


# ── CLI report ───────────────────────────────────────────────────────────────
def _change(key: str, num: int, old: str, new: str, state: str = "done") -> dict:
    return {"committee_key": key, "meeting_num": num, "pdf_id": f"{num}_x", "old": old,
            "new": new, "state": state}


def test_reclassify_report_names_the_meetings_that_would_gain_a_paper(monkeypatch):
    changes = [
        _change("chousei_jukyu", 122, "other", "handout"),
        _change("chousei_jukyu", 122, "other", "handout"),        # same meeting: listed once
        _change("chousei_jukyu", 121, "other", "handout"),
        _change("santeii", 109, "handout", "other"),              # a roster leaving: not a gain
        _change("doji_shijo", 9, "other", "handout", state="detected"),  # pending: it will use it anyway
    ]
    seen: list[bool] = []
    monkeypatch.setattr(store, "reclassify_materials",
                        lambda db_path=None, dry_run=False: (seen.append(dry_run), changes)[1])

    out = CliRunner().invoke(cli.app, ["policy", "reclassify"]).output

    assert seen == [True]  # report-only by default: nothing written
    assert "5 document(s) would change" in out
    assert "2 summarised meeting(s) gain a paper" in out
    assert "chousei_jukyu 第121回" in out and "chousei_jukyu 第122回" in out
    assert "policy run --committee chousei_jukyu --meeting 122" in out
    assert "doji_shijo" not in out and "santeii 第" not in out
    assert "re-run with --apply" in out


def test_reclassify_apply_writes_and_says_so(monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(store, "reclassify_materials",
                        lambda db_path=None, dry_run=False: (seen.append(dry_run), [
                            _change("chousei_jukyu", 122, "other", "handout")])[1])

    out = CliRunner().invoke(cli.app, ["policy", "reclassify", "--apply"]).output

    assert seen == [False]
    assert "1 document(s) re-typed" in out and "re-run with --apply" not in out


def test_reclassify_report_caps_a_long_list(monkeypatch):
    changes = [_change("saisei_kano", n, "other", "handout") for n in range(1, 101)]
    monkeypatch.setattr(store, "reclassify_materials", lambda db_path=None, dry_run=False: changes)

    out = CliRunner().invoke(cli.app, ["policy", "reclassify"]).output

    assert "100 summarised meeting(s) gain a paper" in out
    assert out.count("policy run --committee saisei_kano") == cli._RECLASSIFY_LIST_CAP
    assert f"... and {100 - cli._RECLASSIFY_LIST_CAP} more" in out


# ── Status payload for the chip ──────────────────────────────────────────────
def _done(db: str, key: str, num: int, *, flagged: bool = False) -> None:
    store.record_meeting(key, num, [Material(num, f"{num:03d}_01", f"https://x/{num}.pdf", "資料1", "handout")],
                         db_path=db)
    store.update_meeting(pipeline._meeting_id(key, num, db), db_path=db, state="done",
                         briefing_md="# 要約", resummarise_requested=flagged)


def test_status_payload_counts_queued_updates_per_committee(tmp_path: Path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    _done(db, "emissions_trading", 1, flagged=True)
    _done(db, "emissions_trading", 2, flagged=True)
    _done(db, "emissions_trading", 3)
    _done(db, "doji_shijo", 5, flagged=True)
    _done(db, "santeii", 7)

    out = export_web.build_policy_status(db)

    assert out["updateQueued"] == {"doji_shijo": 1, "emissions_trading": 2}  # none for santeii
    flagged = {(m["com"], m["num"]) for m in out["meetings"] if m["resummarise"]}
    assert flagged == {("emissions_trading", 1), ("emissions_trading", 2), ("doji_shijo", 5)}


def test_queued_updates_survive_the_per_committee_cap(tmp_path: Path):
    """A flagged meeting is pinned like an errored one: the chip would otherwise name a
    committee whose flagged meeting has been trimmed out of the list it expands to."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "emissions_trading"
    _done(db, key, 1, flagged=True)  # the oldest — first in line to be trimmed
    for n in range(2, 2 + export_web.STATUS_MEETINGS_PER_COMMITTEE + 5):
        store.record_meeting(key, n, None, db_path=db)  # quiet pending backlog

    out = export_web.build_policy_status(db)

    mine = [m for m in out["meetings"] if m["com"] == key]
    assert len(mine) == export_web.STATUS_MEETINGS_PER_COMMITTEE
    assert any(m["num"] == 1 and m["resummarise"] for m in mine)
    assert out["updateQueued"] == {key: 1}


def test_status_payload_has_an_empty_update_map_when_nothing_is_queued(tmp_path: Path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    _done(db, "emissions_trading", 1)
    assert export_web.build_policy_status(db)["updateQueued"] == {}
