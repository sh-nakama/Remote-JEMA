"""The readiness gate: a meeting is only worth a briefing once it has been held *and* has a
paper to read. Committee pages post the agenda and handouts days ahead, so without it the
daily run summarised papers for meetings that had not happened, then spent a second quota slot
rewriting them (chousei_jukyu 第123回: summarised 6 days before its date).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import pytest

from repower.dashboard.export_web import build_policy_snapshot, build_policy_status
from repower.policy import detect as detect_mod
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, store
from repower.policy.committees import committee_by_key
from repower.policy.scraper import Discovery, Material
from repower.policy.store import AWAITING, READY, UPCOMING, meeting_readiness
from repower.timeutil import today_jst

TODAY = date(2026, 10, 24)
LOOKED = datetime(2026, 10, 22, tzinfo=UTC)  # the page was read two days ago


def _mat(n: int, kind: str, pid: str | None = None) -> Material:
    return Material(n, pid or f"{n:03d}_{kind}", f"https://x/{n}/{kind}.pdf", kind, kind)


def _meeting(db: str, key: str, n: int, kinds=("handout",), **fields) -> int:
    store.record_meeting(key, n, [_mat(n, k) for k in kinds] or None, db_path=db)
    mid = pipeline._meeting_id(key, n, db)
    assert mid is not None
    if fields:
        store.update_meeting(mid, db_path=db, **fields)
    return mid


def _nums(db: str, **kw) -> list[int]:
    return [m["meeting_num"] for m in store.pending_meetings(db_path=db, today=TODAY, **kw)]


# ── The classifier ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("held,kinds,checked,expected", [
    (TODAY - timedelta(days=1), ("handout",), None, READY),
    (TODAY - timedelta(days=1), ("minutes",), LOOKED, READY),
    (TODAY - timedelta(days=1), ("brief",), LOOKED, READY),
    (TODAY - timedelta(days=1), ("compilation",), LOOKED, READY),
    (TODAY, ("handout",), LOOKED, UPCOMING),              # the 06:30 run precedes a same-day meeting
    (TODAY + timedelta(days=3), ("handout", "agenda"), LOOKED, UPCOMING),
    (TODAY + timedelta(days=3), (), None, UPCOMING),      # upcoming wins over "no papers"
    # Looked recently, nothing to read: awaiting.
    (TODAY - timedelta(days=1), ("agenda",), LOOKED, AWAITING),
    (TODAY - timedelta(days=1), ("agenda", "appendix", "other"), LOOKED, AWAITING),
    (TODAY - timedelta(days=1), (), LOOKED, AWAITING),
    # Never looked: the list is *unknown*, not empty — it must stay reachable so it gets listed.
    (TODAY - timedelta(days=1), (), None, READY),
    (TODAY - timedelta(days=1), ("agenda",), None, READY),
    # …and a "nothing yet" verdict goes stale after RELIST_DAYS.
    (TODAY - timedelta(days=30), ("agenda",), datetime(2026, 10, 18, tzinfo=UTC), AWAITING),
    (TODAY - timedelta(days=30), ("agenda",), datetime(2026, 10, 17, tzinfo=UTC), READY),
    (None, ("handout",), None, READY),                    # a missing date never blocks real work
    (None, ("agenda",), LOOKED, AWAITING),
])
def test_meeting_readiness(held, kinds, checked, expected):
    assert meeting_readiness(held, kinds, today=TODAY, checked_at=checked) == expected


# ── The worklist ─────────────────────────────────────────────────────────────
def test_only_ready_meetings_are_in_the_worklist(policy_db):
    db = policy_db
    _meeting(db, "santeii", 1, meeting_date=TODAY - timedelta(days=5))                    # ready
    _meeting(db, "santeii", 2, meeting_date=TODAY + timedelta(days=2))                    # upcoming
    _meeting(db, "santeii", 3, kinds=("agenda",), meeting_date=TODAY - timedelta(days=5),
             materials_checked_at=LOOKED)                                                  # awaiting
    _meeting(db, "santeii", 4, kinds=(), meeting_date=TODAY - timedelta(days=5),
             materials_checked_at=LOOKED)                                                  # awaiting
    _meeting(db, "santeii", 5, kinds=(), meeting_date=TODAY - timedelta(days=5))           # never listed

    # 5 stays: nothing is on file because nobody has looked, and looking is the next step.
    assert _nums(db) == [5, 1]
    everything = {m["meeting_num"]: m["readiness"] for m in
                  store.pending_meetings(db_path=db, today=TODAY, ready_only=False)}
    assert everything == {1: READY, 2: UPCOMING, 3: AWAITING, 4: AWAITING, 5: READY}


def test_a_requested_meeting_bypasses_the_gate(policy_db):
    db = policy_db
    _meeting(db, "santeii", 2, meeting_date=TODAY + timedelta(days=2), gen_requested=True)
    assert _nums(db) == [2]


def test_a_summarised_meeting_flagged_for_update_is_not_regated(policy_db):
    """It already passed; a late paper is a deliberate upgrade, not a first summary."""
    db = policy_db
    _meeting(db, "santeii", 1, kinds=("agenda",), state="done", briefing_md="x",
             resummarise_requested=True, meeting_date=TODAY - timedelta(days=40))
    got = store.pending_meetings(db_path=db, today=TODAY, include_resummarise=True)
    assert [(m["meeting_num"], m["resummarise"], m["readiness"]) for m in got] == [(1, True, READY)]


def test_the_gate_applies_to_the_breadth_first_run_and_the_queue_view(policy_db):
    db = policy_db
    _meeting(db, "santeii", 1, meeting_date=TODAY - timedelta(days=5))
    _meeting(db, "santeii", 2, meeting_date=TODAY + timedelta(days=2))
    assert _nums(db, breadth_first=True, only_enabled=True) == [1]
    q = store.queue_snapshot(db_path=db, now=datetime(2026, 10, 24, 12))
    assert [i["num"] for i in q["items"]] == [1]


def test_meeting_gate_reports_requested_and_exempts_done(policy_db):
    db = policy_db
    _meeting(db, "santeii", 2, meeting_date=TODAY + timedelta(days=2))
    assert store.meeting_gate("santeii", 2, {"handout"}, today=TODAY, db_path=db) == (UPCOMING, False)
    store.request_generation("santeii", 2, db_path=db)
    assert store.meeting_gate("santeii", 2, {"handout"}, today=TODAY, db_path=db) == (UPCOMING, True)
    _meeting(db, "santeii", 3, kinds=("agenda",), state="done", briefing_md="x")
    assert store.meeting_gate("santeii", 3, {"agenda"}, today=TODAY, db_path=db)[0] == READY


# ── The pipeline ─────────────────────────────────────────────────────────────
def test_summarize_defers_an_unready_meeting_without_touching_it(policy_db, monkeypatch):
    """No error, no retry spent, no notebook created: it is simply not time yet."""
    db = policy_db
    future = today_jst() + timedelta(days=3)
    mid = _meeting(db, "santeii", 2, meeting_date=future)
    monkeypatch.setattr(nb_mod, "create_notebook",
                        lambda *a, **k: pytest.fail("a deferred meeting must not reach NotebookLM"))

    out = pipeline.summarize_meeting(committee_by_key("santeii"), 2, db_path=db)

    assert out == "deferred"
    row = next(m for m in store.pending_meetings(db_path=db, ready_only=False) if m["id"] == mid)
    assert row["state"] == "detected" and row["readiness"] == UPCOMING


def test_summarize_relists_then_defers_a_held_meeting_with_only_an_agenda(policy_db, monkeypatch):
    """Was an agenda-only summary (or a red ``no_sources`` error). The page is read again —
    the list on file may be stale — and only if that finds a paper does it go ahead."""
    db = policy_db
    past = today_jst() - timedelta(days=3)
    _meeting(db, "santeii", 2, kinds=("agenda",), meeting_date=past)
    listed: list[int] = []
    monkeypatch.setattr(pipeline, "list_materials",
                        lambda c, n, **k: listed.append(n) or [_mat(n, "agenda")])
    monkeypatch.setattr(nb_mod, "create_notebook", lambda *a, **k: pytest.fail("no quota for this"))

    assert pipeline.summarize_meeting(committee_by_key("santeii"), 2, db_path=db) == "deferred"

    assert listed == [2]
    row = store.pending_meetings(db_path=db, ready_only=False)[0]
    assert (row["state"], row["readiness"]) == ("detected", AWAITING)  # looked, nothing yet
    # Told so, the daily worklist now leaves it alone for a week instead of re-reading it daily.
    assert store.pending_meetings(db_path=db) == []


def test_summarize_goes_ahead_when_the_relisted_page_has_a_paper(policy_db, monkeypatch):
    db = policy_db
    _meeting(db, "santeii", 2, kinds=("agenda",), meeting_date=today_jst() - timedelta(days=3))
    monkeypatch.setattr(pipeline, "list_materials", lambda c, n, **k: [_mat(n, "agenda"), _mat(n, "handout")])
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "not_found")
    out = pipeline.summarize_meeting(committee_by_key("santeii"), 2, db_path=db)
    assert out != "deferred"


def test_an_unlisted_backlog_meeting_is_listed_not_deferred_forever(policy_db, monkeypatch):
    """The 533 meetings with no document rows at all: the gate must let the first look happen."""
    db = policy_db
    _meeting(db, "santeii", 3, kinds=(), meeting_date=today_jst() - timedelta(days=400))
    assert [m["meeting_num"] for m in store.pending_meetings(db_path=db)] == [3]
    monkeypatch.setattr(pipeline, "list_materials", lambda c, n, **k: [_mat(n, "handout")])
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "not_found")
    assert pipeline.summarize_meeting(committee_by_key("santeii"), 3, db_path=db) != "deferred"


def test_run_counts_a_deferral_as_free(policy_db, monkeypatch):
    """A deferral takes no slot of ``--max-per-run`` and is not an error."""
    db = policy_db
    for n in (1, 2, 3):
        _meeting(db, "santeii", n, meeting_date=TODAY - timedelta(days=9))
    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "summarize_meeting",
                        lambda c, n, **k: "deferred" if n == 3 else "done")

    out = pipeline.run(["santeii"], max_per_run=2, db_path=db)

    assert (out["done"], out["errored"], out["deferred"]) == (2, 0, 1)
    assert out["processed"] == 2


def test_a_targeted_run_forces_past_the_gate(policy_db, monkeypatch):
    db = policy_db
    _meeting(db, "santeii", 2, meeting_date=TODAY + timedelta(days=2))
    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)
    seen: list[bool] = []
    monkeypatch.setattr(pipeline, "summarize_meeting",
                        lambda c, n, **k: seen.append(k.get("force")) or "done")

    pipeline.run(["santeii"], meeting_num=2, db_path=db)
    assert seen == [True]


# ── Withdrawing summaries that predate their meeting ─────────────────────────
def test_reset_unready_summaries_withdraws_a_briefing_of_an_unheld_meeting(policy_db):
    """The chousei_jukyu 第123回 case, plus the two things that must be left alone."""
    db = policy_db
    future = TODAY + timedelta(days=2)
    premature = _meeting(
        db, "chousei_jukyu", 123, kinds=("handout", "agenda"), meeting_date=future, state="done",
        briefing_md="# 要約", digest_en_json='{"answer": "x"}', resummarise_requested=True,
        synth_done=True, notebook_id="nb-1", quality_flag="ocr_suspect",
    )
    held = _meeting(db, "chousei_jukyu", 122, meeting_date=TODAY - timedelta(days=9),
                    state="done", briefing_md="# 要約", digest_en_json='{"answer": "x"}')
    no_sources = _meeting(db, "shorai_jukyu", 12, kinds=(), meeting_date=future, state="error",
                          quality_flag="no_sources", last_error="No usable source documents",
                          retry_count=1)
    real_failure = _meeting(db, "shorai_jukyu", 11, meeting_date=future, state="error",
                            quality_flag="download_failed", last_error="boom", retry_count=2)

    assert store.reset_unready_summaries(db, today=TODAY) == {"unsummarised": 1, "cleared": 1}

    from repower.db import PolicyMeeting, get_session
    s = get_session(db)
    try:
        p = s.get(PolicyMeeting, premature)
        assert (p.state, p.briefing_md, p.digest_en_json) == ("detected", None, None)
        assert not p.resummarise_requested and not p.synth_done and p.quality_flag is None
        assert p.notebook_id == "nb-1"  # kept, so the next run deletes the stale notebook
        assert s.get(PolicyMeeting, held).state == "done"
        ns = s.get(PolicyMeeting, no_sources)
        assert (ns.state, ns.quality_flag, ns.last_error, ns.retry_count) == ("detected", None, None, 0)
        rf = s.get(PolicyMeeting, real_failure)
        assert (rf.state, rf.quality_flag, rf.retry_count) == ("error", "download_failed", 2)
    finally:
        s.close()

    # Withdrawn means out of the worklist until it is held, then back in.
    assert 123 not in _nums(db)
    assert store.reset_unready_summaries(db, today=TODAY) == {"unsummarised": 0, "cleared": 0}  # idempotent
    later = store.pending_meetings(db_path=db, today=future + timedelta(days=1))
    assert 123 in [m["meeting_num"] for m in later]


def test_a_held_no_sources_failure_clears_only_once_looked_at(policy_db):
    """Held, but the page lists no usable papers: awaiting, so it is cleared too — it is "not
    yet" either way. A failure that is *not* ``no_sources`` is never touched."""
    db = policy_db
    _meeting(db, "santeii", 1, kinds=("agenda",), meeting_date=TODAY - timedelta(days=5),
             state="error", quality_flag="no_sources", last_error="nothing",
             materials_checked_at=LOOKED)
    _meeting(db, "santeii", 2, kinds=("agenda",), meeting_date=TODAY - timedelta(days=5),
             state="error", quality_flag="no_sources", last_error="never looked")
    assert store.reset_unready_summaries(db, today=TODAY)["cleared"] == 1  # only the one looked at


def test_detect_runs_the_withdrawal_each_pass(policy_db, monkeypatch, caplog):
    db = policy_db
    _meeting(db, "chousei_jukyu", 123, kinds=("handout",), meeting_date=today_jst() + timedelta(days=2),
             state="done", briefing_md="# 要約", digest_en_json='{"answer": "x"}')
    monkeypatch.setattr(detect_mod, "discover_meetings", lambda c, **k: Discovery("unchanged", []))

    with caplog.at_level(logging.INFO, logger=detect_mod.logger.name):
        detect_mod.detect(["chousei_jukyu"], db_path=db, refresh_window_days=None, watch_horizon_days=None)

    assert "withdrawn" in caplog.text
    assert store.pending_meetings(db_path=db, ready_only=False)[0]["state"] == "detected"


# ── What the readers see ─────────────────────────────────────────────────────
def _snapshot_status(db: str, num: int) -> str:
    return next(m["status"] for m in build_policy_snapshot(db)["meetings"]
                if m["num"] == num and m["com"] == "santeii")


def test_export_labels_unready_meetings_instead_of_calling_them_pending(policy_db):
    db = policy_db
    today = today_jst()
    _meeting(db, "santeii", 1, meeting_date=today - timedelta(days=5))
    _meeting(db, "santeii", 2, meeting_date=today + timedelta(days=4))
    _meeting(db, "santeii", 3, kinds=("agenda",), meeting_date=today - timedelta(days=5),
             materials_checked_at=datetime.now(UTC))
    # An old "no sources" failure for a meeting that is just not ready reads as "not yet".
    _meeting(db, "santeii", 4, kinds=("agenda",), meeting_date=today + timedelta(days=4),
             state="error", quality_flag="no_sources")
    _meeting(db, "santeii", 5, meeting_date=today - timedelta(days=5), state="error",
             quality_flag="download_failed")

    assert [_snapshot_status(db, n) for n in (1, 2, 3, 4, 5)] == [
        "pending", "upcoming", "awaiting", "upcoming", "error"]
    snap = {m["num"]: m for m in build_policy_snapshot(db)["meetings"] if m["com"] == "santeii"}
    assert "Upcoming" in snap[2]["emptyTitle"] and "Awaiting" in snap[3]["emptyTitle"]


def test_an_upcoming_meeting_with_no_papers_still_appears(policy_db):
    db = policy_db
    _meeting(db, "santeii", 9, kinds=(), meeting_date=today_jst() + timedelta(days=4))
    assert _snapshot_status(db, 9) == "upcoming"


def test_a_calendar_entry_for_a_listed_upcoming_meeting_is_not_shown_twice(policy_db):
    from repower.db import PolicyUpcoming, get_session

    db = policy_db
    when = today_jst() + timedelta(days=4)
    _meeting(db, "santeii", 9, meeting_date=when)
    s = get_session(db)
    try:
        for num, key in ((9, "listed"), (None, "other")):
            s.add(PolicyUpcoming(meeting_date=when if key == "listed" else when + timedelta(days=1),
                                 source_key=key, name_ja="算定委", org="METI",
                                 committee_key="santeii", meeting_num=num, source="meti-cal",
                                 source_url="https://x"))
        s.commit()
    finally:
        s.close()

    shown = build_policy_snapshot(db)["upcoming"]
    assert [u["date"] for u in shown] == [str(when + timedelta(days=1))]


def test_status_rows_carry_readiness(policy_db):
    db = policy_db
    _meeting(db, "santeii", 1, meeting_date=today_jst() + timedelta(days=4))
    _meeting(db, "santeii", 2, meeting_date=today_jst() - timedelta(days=4))
    got = {m["num"]: m["readiness"] for m in build_policy_status(db)["meetings"] if m["com"] == "santeii"}
    assert got == {1: UPCOMING, 2: READY}
