"""Resummarise flag and the late-minutes watch.

A summarised meeting that gains a paper after the fact (minutes land weeks late) is
flagged ``resummarise_requested`` instead of being pushed back to ``detected``: the
briefing stays on the page while the re-run waits for quota. These tests pin the
worklist order, what a run does to the row on each outcome, and which meetings the
slow re-check selects. Network-free, like ``test_policy.py``.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

import pytest

from repower.policy import detect as detect_mod
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, store
from repower.policy.scraper import Discovery, Material

KEY = "doji_shijo"


def _mat(n: int, name: str, kind: str, title: str = "") -> Material:
    return Material(n, f"{n:03d}_{name}", f"https://x/{n}/{name}.pdf", title or name, kind)


def _summarised(db: str, key: str, n: int, mats: list[Material],
                held: datetime.date | None = None) -> None:
    """A meeting that has been through a run: done, briefing + synthesis flag set."""
    store.record_meeting(key, n, mats, db_path=db)
    store.update_meeting(pipeline._meeting_id(key, n, db), db_path=db, state="done",
                         briefing_md="# 要約", synth_done=True, meeting_date=held)


def _update(db: str, key: str, n: int, **fields) -> None:
    store.update_meeting(pipeline._meeting_id(key, n, db), db_path=db, **fields)


def _row(db: str, key: str, n: int):
    from repower.db import PolicyMeeting
    with store.session_scope(db, commit=False) as s:
        m = s.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=n).one()
        s.expunge(m)
        return m


def _worklist(db: str, **kw) -> list[tuple[str, int]]:
    return [(m["committee_key"], m["meeting_num"])
            for m in store.pending_meetings(db_path=db, include_resummarise=True, **kw)]


def _no_auth_no_synthesis(monkeypatch) -> None:
    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)


def _stub_notebooklm(monkeypatch, tmp_path: Path, report: str) -> None:
    """The happy path of summarize_meeting, with NotebookLM and the host faked."""
    monkeypatch.setattr(pipeline, "_scratch", lambda: tmp_path / "scratch")
    monkeypatch.setattr(pipeline, "_download_pdf", lambda url, dest, **kw: (
        dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"%PDF-1.4"), "ok")[-1])
    monkeypatch.setattr(pipeline.nb, "create_notebook", lambda *a, **k: "nb1")
    monkeypatch.setattr(pipeline.nb, "add_source", lambda nb_id, path: f"src:{Path(path).name}")
    monkeypatch.setattr(pipeline.nb, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(pipeline, "_ocr_guard", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.nb, "generate_report", lambda *a, **k: "task1")
    monkeypatch.setattr(pipeline.nb, "wait_artifact", lambda *a, **k: True)
    monkeypatch.setattr(pipeline.nb, "download_report",
                        lambda nb_id, task_id, out: (out.write_text(report, encoding="utf-8"), True)[1])
    monkeypatch.setattr(pipeline.nb, "ask", lambda *a, **k: {"answer": "ok"})
    monkeypatch.setattr(pipeline.nb, "delete_notebook", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "regenerate_running_doc", lambda *a, **k: None)


# ── worklist ─────────────────────────────────────────────────────────────────
def test_resummarise_is_ordered_behind_never_summarised_meetings(policy_db):
    db = policy_db
    _summarised(db, KEY, 9, [_mat(9, "01", "handout")])
    _update(db, KEY, 9, resummarise_requested=True)
    store.record_meeting(KEY, 4, [_mat(4, "01", "handout")], db_path=db)  # oldest, no briefing
    store.record_meeting("santeii", 3, [_mat(3, "01", "handout")], db_path=db)

    order = _worklist(db)

    assert order[-1] == (KEY, 9)  # last, though it is the committee's newest meeting
    assert set(order[:-1]) == {(KEY, 4), ("santeii", 3)}
    # a person's explicit "run this first" still outranks everything
    store.request_generation(KEY, 9, db_path=db)
    assert _worklist(db)[0] == (KEY, 9)


def test_resummarise_does_not_deepen_the_breadth_first_backlog(policy_db):
    """An upgrade is not backlog: it must not make a committee's real newest pending
    meeting look second in line behind it."""
    db = policy_db
    _summarised(db, KEY, 9, [_mat(9, "01", "handout")])
    _update(db, KEY, 9, resummarise_requested=True)
    store.record_meeting(KEY, 4, [_mat(4, "01", "handout")], db_path=db)
    store.record_meeting("santeii", 3, [_mat(3, "01", "handout")], db_path=db)
    store.record_meeting("santeii", 2, [_mat(2, "01", "handout")], db_path=db)

    # Every committee's newest pending meeting (the first pass), then the update, then deeper
    # backlog. Were the update counted as depth, KEY 4 would be pushed to second place.
    assert _worklist(db, breadth_first=True) == [
        (KEY, 4), ("santeii", 3), (KEY, 9), ("santeii", 2)]


def test_an_update_follows_each_committees_newest_but_precedes_deeper_backlog(policy_db):
    """The daily run's rule, with numbers: committees A and B each have three pending
    meetings; an update on C. First pass A-newest, B-newest; then the update; only then the
    second-newest of anyone — so it does not wait behind the whole backlog."""
    db = policy_db
    for key, nums in (("santeii", (30, 29, 28)), ("saisei_kano", (20, 19, 18))):
        for n in nums:
            store.record_meeting(key, n, [_mat(n, "01", "handout")], db_path=db)
    _summarised(db, "doji_shijo", 5, [_mat(5, "01", "handout")])
    _update(db, "doji_shijo", 5, resummarise_requested=True)

    order = _worklist(db, breadth_first=True)

    assert set(order[:2]) == {("saisei_kano", 20), ("santeii", 30)}   # the two newest, in priority order
    assert order[2] == ("doji_shijo", 5)                              # then the update
    assert order.index(("doji_shijo", 5)) < order.index(("santeii", 29))
    assert order.index(("doji_shijo", 5)) < order.index(("saisei_kano", 19))


def test_updates_share_their_slot_in_priority_then_newest_order(policy_db):
    db = policy_db
    store.record_meeting("santeii", 30, [_mat(30, "01", "handout")], db_path=db)
    store.record_meeting("santeii", 29, [_mat(29, "01", "handout")], db_path=db)
    for key, num in (("saisei_kano", 7), ("saisei_kano", 8), ("doji_shijo", 5)):
        _summarised(db, key, num, [_mat(num, "01", "handout")])
        _update(db, key, num, resummarise_requested=True)

    updates = [x for x in _worklist(db, breadth_first=True) if x[0] != "santeii"]
    # newest first within a committee; committees in priority order
    assert [n for k, n in updates if k == "saisei_kano"] == [8, 7]
    # and all three sit between santeii's newest (30) and its second-newest (29)
    order = _worklist(db, breadth_first=True)
    lo, hi = order.index(("santeii", 30)), order.index(("santeii", 29))
    assert all(lo < order.index(u) < hi for u in updates)


def test_a_depth_first_run_still_puts_updates_after_every_pending_meeting(policy_db):
    """A single-committee backfill drains history; an update is not part of it. (Only the
    breadth-first daily run slots updates in early.)"""
    db = policy_db
    _summarised(db, KEY, 9, [_mat(9, "01", "handout")])
    _update(db, KEY, 9, resummarise_requested=True)
    for n in (4, 3, 2):
        store.record_meeting(KEY, n, [_mat(n, "01", "handout")], db_path=db)
    assert _worklist(db) == [(KEY, 4), (KEY, 3), (KEY, 2), (KEY, 9)]


def test_a_meeting_moved_to_the_front_still_outranks_an_update(policy_db):
    db = policy_db
    _summarised(db, KEY, 9, [_mat(9, "01", "handout")])
    _update(db, KEY, 9, resummarise_requested=True)
    store.record_meeting("santeii", 3, [_mat(3, "01", "handout")], db_path=db)
    store.request_generation("santeii", 3, db_path=db)
    assert _worklist(db, breadth_first=True)[0] == ("santeii", 3)


def test_pending_counts_do_not_include_upgrades_unless_asked(policy_db):
    """"Pending" is also a status count meaning "no briefing yet"."""
    db = policy_db
    _summarised(db, KEY, 9, [_mat(9, "01", "handout")])
    _update(db, KEY, 9, resummarise_requested=True)
    assert store.pending_meetings(db_path=db) == []
    assert _worklist(db) == [(KEY, 9)]


def test_resummarise_honours_the_retry_cap_and_the_tracked_filter(policy_db):
    db = policy_db
    _summarised(db, KEY, 9, [_mat(9, "01", "handout")])
    _update(db, KEY, 9, resummarise_requested=True, retry_count=store.MAX_RETRIES)
    assert _worklist(db) == []  # a re-run that keeps failing does not burn quota forever

    _update(db, KEY, 9, retry_count=0)
    assert _worklist(db) == [(KEY, 9)]
    store.set_committee_enabled(KEY, False, db_path=db)
    assert _worklist(db, only_enabled=True) == []


def test_request_generation_on_a_done_meeting_queues_a_rerun(policy_db):
    """"Queue to front" on a summarised meeting used to set a flag nothing read."""
    db = policy_db
    _summarised(db, KEY, 9, [_mat(9, "01", "handout")])

    assert store.request_generation(KEY, 9, db_path=db) is True
    m = _row(db, KEY, 9)
    assert m.gen_requested is True and m.resummarise_requested is True and m.state == "done"

    # the pipeline's post-attempt clear must not drop a re-run that failed…
    store.clear_generation_request(KEY, 9, db_path=db)
    assert _row(db, KEY, 9).resummarise_requested is True
    # …but a person taking it off the queue withdraws it
    store.clear_generation_request(KEY, 9, db_path=db, withdraw_resummarise=True)
    assert _row(db, KEY, 9).resummarise_requested is False


# ── what a run does to the row ───────────────────────────────────────────────
def test_a_successful_rerun_replaces_the_briefing_and_clears_the_flag(monkeypatch, policy_db, tmp_path):
    db = policy_db
    _stub_notebooklm(monkeypatch, tmp_path, "## 新しい要約\n" + "y" * 500)
    _no_auth_no_synthesis(monkeypatch)
    _summarised(db, KEY, 9, [_mat(9, "gijishidai", "agenda")])
    store.add_late_materials(KEY, 9, [_mat(9, "gijiroku", "minutes")], db_path=db)
    assert _row(db, KEY, 9).resummarise_requested is True

    res = pipeline.run([KEY], db_path=db)

    assert res["done"] == 1
    m = _row(db, KEY, 9)
    assert m.state == "done" and m.resummarise_requested is False
    assert m.briefing_md.startswith("## 新しい要約")
    assert m.synth_done is False  # so the committee synthesis folds the new briefing in
    assert {r["status"] for r in store.meeting_materials(KEY, 9, db_path=db)} == {"ingested"}


@pytest.mark.parametrize("outcome", ["error", "blocked"])
def test_a_failed_rerun_keeps_the_old_briefing_on_the_page(monkeypatch, policy_db, outcome):
    db = policy_db
    _no_auth_no_synthesis(monkeypatch)
    _summarised(db, KEY, 9, [_mat(9, "gijishidai", "agenda")])
    store.add_late_materials(KEY, 9, [_mat(9, "gijiroku", "minutes")], db_path=db)

    def fail(committee, n, **kw):  # what the real failure paths do to the row
        _update(db, KEY, n, state="error", last_error="download failed")
        return outcome

    monkeypatch.setattr(pipeline, "summarize_meeting", fail)
    pipeline.run([KEY], db_path=db)

    m = _row(db, KEY, 9)
    assert m.state == "done" and m.briefing_md == "# 要約"  # never left the page
    assert m.resummarise_requested is True                   # still queued
    assert m.last_error == "download failed"                 # and says why it has not landed


def test_a_rate_limited_rerun_keeps_the_old_briefing_on_the_page(monkeypatch, policy_db):
    db = policy_db
    _no_auth_no_synthesis(monkeypatch)
    _summarised(db, KEY, 9, [_mat(9, "gijishidai", "agenda")])
    store.add_late_materials(KEY, 9, [_mat(9, "gijiroku", "minutes")], db_path=db)

    def limited(committee, n, **kw):
        _update(db, KEY, n, state="detected", notebook_id=None)  # as the real path resets it
        raise nb_mod.NotebookLMRateLimitError("quota")

    monkeypatch.setattr(pipeline, "summarize_meeting", limited)
    res = pipeline.run([KEY], db_path=db)

    assert res["rate_limited"] is True
    m = _row(db, KEY, 9)
    assert m.state == "done" and m.briefing_md == "# 要約" and m.resummarise_requested is True


# ── late-minutes watch ───────────────────────────────────────────────────────
def _watch(db: str, today: datetime.date, **kw) -> list[int]:
    return store.watch_meeting_nums(KEY, today, db_path=db, **kw)


def test_watch_picks_summarised_meetings_without_minutes_or_brief(policy_db):
    db, today = policy_db, datetime.date(2026, 10, 15)
    held = datetime.date(2026, 10, 1)
    _summarised(db, KEY, 1, [_mat(1, "01", "handout")], held=held)
    _summarised(db, KEY, 2, [_mat(2, "min", "minutes")], held=held)
    _summarised(db, KEY, 3, [_mat(3, "brief", "brief")], held=held)
    store.record_meeting(KEY, 4, [_mat(4, "01", "handout")], db_path=db)  # not summarised yet

    assert _watch(db, today) == [1]


def test_watch_looks_once_at_any_age_then_stops_past_the_horizon(policy_db):
    db, today = policy_db, datetime.date(2026, 10, 15)
    _summarised(db, KEY, 1, [_mat(1, "01", "handout")], held=datetime.date(2025, 6, 1))
    assert _watch(db, today) == [1]  # never read: one look, however old

    store.add_late_materials(KEY, 1, [_mat(1, "01", "handout")], db_path=db)  # looked, nothing new
    assert _row(db, KEY, 1).materials_checked_at is not None
    assert _watch(db, today) == []  # old and already looked at: finished


def test_watch_repeats_weekly_inside_the_horizon(policy_db):
    db = policy_db
    now = datetime.datetime.now(datetime.UTC).date()
    _summarised(db, KEY, 2, [_mat(2, "01", "handout")], held=now - datetime.timedelta(days=20))
    store.add_late_materials(KEY, 2, [_mat(2, "01", "handout")], db_path=db)  # read just now

    assert _watch(db, now) == []                                      # too soon
    assert _watch(db, now + datetime.timedelta(days=6)) == []
    assert _watch(db, now + datetime.timedelta(days=8)) == [2]        # a week on, still inside 90d
    assert _watch(db, now + datetime.timedelta(days=80)) == []        # 100 days after the meeting


def test_watch_skips_untracked_committees(policy_db):
    db, today = policy_db, datetime.date(2026, 10, 15)
    _summarised(db, KEY, 1, [_mat(1, "01", "handout")], held=datetime.date(2026, 10, 1))
    store.set_committee_enabled(KEY, False, db_path=db)
    assert _watch(db, today) == []


def _reachable(monkeypatch) -> None:
    monkeypatch.setattr(detect_mod, "discover_meetings", lambda c, **kw: Discovery("unchanged", []))
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(detect_mod, "budget_exhausted", lambda url: False)


def test_detect_watch_finds_late_minutes_and_flags_the_meeting(monkeypatch, policy_db):
    db, key = policy_db, "chousei_jukyu"
    today = datetime.date(2026, 10, 15)
    # held five weeks ago: outside the 7-day window, inside the 90-day watch
    _summarised(db, key, 121, [_mat(121, "01", "handout")], held=datetime.date(2026, 9, 9))
    _reachable(monkeypatch)
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [
        _mat(n, "01", "handout"), _mat(n, "gijiroku", "minutes")])

    res = detect_mod.detect([key], db_path=db, today=today)

    assert (res[0]["refreshed"], res[0]["requeued"]) == (1, 1)
    m = _row(db, key, 121)
    assert m.state == "done" and m.resummarise_requested is True and m.has_minutes is True
    assert {r["pdf_id"] for r in store.meeting_materials(key, 121, db_path=db)} == {
        "121_01", "121_gijiroku"}

    # minutes are on file now, so the next day does not read the page again
    again: list[int] = []
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: (again.append(n), [])[1])
    detect_mod.detect([key], db_path=db, today=today + datetime.timedelta(days=1),
                      refresh_window_days=None)
    assert again == []


def test_detect_watch_can_be_switched_off_on_its_own(monkeypatch, policy_db):
    db, key = policy_db, "chousei_jukyu"
    _summarised(db, key, 121, [_mat(121, "01", "handout")], held=datetime.date(2026, 9, 9))
    _reachable(monkeypatch)
    monkeypatch.setattr(detect_mod, "list_materials",
                        lambda c, n, **kw: pytest.fail("watch is off; 121 is outside the window"))
    detect_mod.detect([key], db_path=db, today=datetime.date(2026, 10, 15), watch_horizon_days=None)


def test_first_seen_is_recorded_for_new_and_late_documents(policy_db):
    from repower.db import PolicyMaterial
    db = policy_db
    store.record_meeting(KEY, 1, [_mat(1, "01", "handout")], db_path=db)
    _summarised(db, KEY, 2, [_mat(2, "01", "handout")])
    store.add_late_materials(KEY, 2, [_mat(2, "gijiroku", "minutes")], db_path=db)
    with store.session_scope(db, commit=False) as s:
        seen = {p.pdf_id: p.first_seen_at for p in s.query(PolicyMaterial).all()}
    assert set(seen) == {"001_01", "002_01", "002_gijiroku"}
    assert all(v is not None for v in seen.values())


def test_new_columns_are_added_to_a_pulled_database(tmp_path):
    """Production DBs come from Hugging Face and predate these columns."""
    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE policy_meeting (id INTEGER PRIMARY KEY, committee_key VARCHAR(64) NOT NULL,"
                " meeting_num INTEGER NOT NULL, state VARCHAR(16) NOT NULL)")
    con.execute("CREATE TABLE policy_material (id INTEGER PRIMARY KEY, committee_key VARCHAR(64) NOT NULL,"
                " meeting_num INTEGER NOT NULL, pdf_id VARCHAR(128) NOT NULL)")
    con.execute("INSERT INTO policy_meeting VALUES (1, 'k', 1, 'done')")
    con.commit()
    con.close()

    store.sync_committees(db_path=db)  # init_db runs the migrations

    con = sqlite3.connect(db)
    mcols = {r[1] for r in con.execute("pragma table_info(policy_meeting)")}
    pcols = {r[1] for r in con.execute("pragma table_info(policy_material)")}
    assert {"resummarise_requested", "materials_checked_at"} <= mcols
    assert "first_seen_at" in pcols
    assert con.execute("select resummarise_requested from policy_meeting").fetchone()[0] in (0, None)
