"""`policy reclassify`: the per-committee breakdown in its report, and `--queue`.

The report used to end with an alphabetical list of the summarised meetings that gain a
paper, capped at 60. One committee filled it, so a run that re-typed documents in 66
committees read as touching one. `--queue` flags those meetings for a new briefing, but
only on the run that re-types the documents: afterwards the old kinds are gone and there
is nothing left to diff.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repower import cli
from repower.db import PolicyMeeting
from repower.policy import pipeline, store
from repower.policy.scraper import Material


def _change(key: str, num: int, old: str, new: str, state: str = "done") -> dict:
    return {"committee_key": key, "meeting_num": num, "pdf_id": f"{num}_x", "old": old,
            "new": new, "state": state}


def _run(monkeypatch, changes, *args, queue_result=None):
    """Invoke the command with the store faked; returns (output, exit_code, queue calls)."""
    calls: list = []
    monkeypatch.setattr(store, "reclassify_materials", lambda db_path=None, dry_run=False: changes)

    def fake_queue(meetings, db_path=None):
        calls.append(list(meetings))
        return queue_result if queue_result is not None else {"queued": list(meetings), "untracked": []}

    monkeypatch.setattr(store, "queue_resummarise", fake_queue)
    result = CliRunner().invoke(cli.app, ["policy", "reclassify", *args])
    return result.output, result.exit_code, calls


# ── Per-committee breakdown ──────────────────────────────────────────────────
def test_report_breaks_the_changes_down_by_committee(monkeypatch):
    """The meeting list is capped and alphabetical, so one big committee fills it; the
    breakdown is what shows how far a run actually reached."""
    changes = (
        [_change("chousei_jukyu", n, "other", "handout") for n in range(1, 61)]
        + [_change("jukyuchousei", 5, "handout", "other")] * 3
        + [_change("jisedai_kiban", 2, "other", "handout")]
    )
    out, _, _ = _run(monkeypatch, changes)

    assert "64 document(s) would change across 3 committee(s)" in out
    assert "documents by committee: chousei_jukyu 60, jukyuchousei 3, jisedai_kiban 1" in out
    assert "meetings gaining a paper: chousei_jukyu 60, jisedai_kiban 1" in out  # biggest first


def test_breakdown_caps_the_committee_list(monkeypatch):
    changes = [_change(f"com_{i:02d}", 1, "other", "handout", state="detected") for i in range(20)]
    out, _, _ = _run(monkeypatch, changes)

    assert "across 20 committee(s)" in out
    assert f"(+{20 - cli._RECLASSIFY_TOP_COMMITTEES} more committee(s))" in out
    assert "meetings gaining a paper" not in out  # pending meetings gain nothing worth naming


def test_nothing_to_change_prints_no_breakdown(monkeypatch):
    out, code, _ = _run(monkeypatch, [])
    assert code == 0 and "0 document(s) would change across 0 committee(s)" in out
    assert "documents by committee" not in out and "re-run with --apply" not in out


# ── --queue ──────────────────────────────────────────────────────────────────
def test_queue_needs_apply_and_runs_nothing_without_it(monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(store, "reclassify_materials",
                        lambda db_path=None, dry_run=False: ran.append("reclassify") or [])
    monkeypatch.setattr(store, "queue_resummarise", lambda *a, **k: ran.append("queue"))

    result = CliRunner().invoke(cli.app, ["policy", "reclassify", "--queue"])

    assert result.exit_code != 0 and "--queue needs --apply" in result.output
    assert ran == []  # not even the report ran


def test_apply_queue_flags_the_meetings_it_names(monkeypatch):
    changes = [_change("chousei_jukyu", 122, "other", "handout"),
               _change("chousei_jukyu", 121, "other", "handout"),
               _change("chousei_jukyu", 121, "other", "handout"),          # same meeting: once
               _change("santeii", 109, "handout", "other")]                # a roster leaving: not a gain
    out, code, calls = _run(monkeypatch, changes, "--apply", "--queue")

    assert code == 0
    assert calls == [[("chousei_jukyu", 121), ("chousei_jukyu", 122)]]
    assert "queued 2 meeting(s) for a new briefing" in out
    assert "not queued" not in out


def test_queue_names_the_untracked_committees_it_skipped(monkeypatch):
    out, _, _ = _run(monkeypatch, [_change("chousei_jukyu", 122, "other", "handout")], "--apply", "--queue",
                     queue_result={"queued": [], "untracked": [("chousei_jukyu", 122)]})
    assert "queued 0 meeting(s)" in out and "skipped 1 in untracked committee(s)" in out


def test_queue_covers_meetings_beyond_the_printed_cap(monkeypatch):
    """The list is capped for readability; the queue is not."""
    changes = [_change("saisei_kano", n, "other", "handout") for n in range(1, 101)]
    out, _, calls = _run(monkeypatch, changes, "--apply", "--queue")
    assert len(calls[0]) == 100 and "queued 100 meeting(s)" in out
    assert out.count("policy run --committee saisei_kano") == cli._RECLASSIFY_LIST_CAP


def test_apply_without_queue_says_how_to_queue_afterwards(monkeypatch):
    """After an apply the old kinds are gone, so a later run has nothing left to diff: the
    output must say so rather than leave --queue looking like a no-op."""
    out, _, calls = _run(monkeypatch, [_change("chousei_jukyu", 122, "other", "handout")], "--apply")
    assert calls == []
    assert "not queued" in out and "only acts on the run that re-types" in out
    assert "policy queue --committee K --meeting N" in out


def test_apply_with_nothing_gained_stays_quiet_about_queueing(monkeypatch):
    out, _, _ = _run(monkeypatch, [_change("santeii", 109, "handout", "other")], "--apply")
    assert "not queued" not in out


def test_report_only_run_offers_queue_in_its_hint(monkeypatch):
    out, _, _ = _run(monkeypatch, [_change("chousei_jukyu", 122, "other", "handout")])
    assert "re-run with --apply" in out and "--queue" in out


# ── store.queue_resummarise ──────────────────────────────────────────────────
def _summarised(db: str, key: str, num: int) -> None:
    store.record_meeting(key, num, [Material(num, f"{num:03d}_01", f"https://x/{num}.pdf", "資料1", "handout")],
                         db_path=db)
    store.update_meeting(pipeline._meeting_id(key, num, db), db_path=db, state="done",
                         briefing_md="# 要約", retry_count=2)


def test_queue_resummarise_flags_tracked_done_meetings_only(tmp_path: Path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    _summarised(db, "chousei_jukyu", 10)
    _summarised(db, "santeii", 5)
    store.set_committee_enabled("santeii", False, db_path=db)
    store.record_meeting("chousei_jukyu", 11, None, db_path=db)  # never summarised: not done

    res = store.queue_resummarise(
        [("chousei_jukyu", 10), ("santeii", 5), ("chousei_jukyu", 11), ("chousei_jukyu", 999)], db_path=db)

    assert res == {"queued": [("chousei_jukyu", 10)], "untracked": [("santeii", 5)]}
    with store.session_scope(db, commit=False) as s:
        rows = {(m.committee_key, m.meeting_num): m for m in s.query(PolicyMeeting)}
    flagged = rows[("chousei_jukyu", 10)]
    assert flagged.resummarise_requested is True
    assert flagged.retry_count == 0   # a fresh reason: earlier failures no longer count
    assert flagged.state == "done"    # and its briefing stays visible meanwhile
    assert not rows[("santeii", 5)].resummarise_requested  # no chip for work that never starts
    assert not rows[("chousei_jukyu", 11)].resummarise_requested
    # the run's worklist has it now, behind the never-summarised meeting
    work = [(m["committee_key"], m["meeting_num"])
            for m in store.pending_meetings(db_path=db, include_resummarise=True, only_enabled=True)]
    assert work == [("chousei_jukyu", 11), ("chousei_jukyu", 10)]
