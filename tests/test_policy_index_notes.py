"""The committee index's own word on a meeting: EGC marks rows ※書面開催 / ※非公開開催 (a written or
closed meeting, often with nothing posted) and ※削除済み (documents taken down). Such a meeting has
nothing to read, so it leaves the worklist instead of failing as ``no_sources`` / ``download_failed``
and spending a retry every run (emsc_system 第619回: ※書面開催, no links at all).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from repower.dashboard.export_web import build_policy_snapshot
from repower.policy import detect as detect_mod
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, store
from repower.policy.scraper import (
    NOTE_NO_PAPERS,
    NOTE_REMOVED,
    Discovery,
    Material,
    egc_row_note,
    parse_egc_index,
)
from repower.policy.store import AWAITING, NO_PAPERS, READY, REMOVED, UPCOMING, meeting_readiness
from repower.timeutil import today_jst

TODAY = date(2026, 10, 24)
LOOKED = datetime(2026, 10, 22, tzinfo=UTC)

# Rows as they appear on www.egc.meti.go.jp (index_emsc.html, index_electricityreview.html …).
EGC_NOTED_INDEX = """
<html><body><table>
  <tr><td>令和8年9月28日</td><td>第619回</td><td></td><td></td><td></td><td>※書面開催</td></tr>
  <tr><td>令和8年9月2日</td><td>第617回</td>
      <td><a href="emsc/pdf/617_giji.pdf">議事要旨</a></td><td></td>
      <td><a href="emsc/617_haifu.html">配布資料</a></td><td>※書面開催</td></tr>
  <tr><td>令和8年7月31日</td><td>第614回</td><td></td><td></td><td></td><td>※書面開催</td></tr>
  <tr><td>令和8年7月22日</td><td>第613回</td>
      <td><a href="emsc/pdf/613_giji.pdf">議事要旨</a></td><td></td><td></td><td>※非公開開催</td></tr>
  <tr><td>平成30年10月05日</td><td>第612回</td><td></td><td></td>
      <td><a href="emsc/612_haifu.html">配布資料</a></td><td>※非公開開催</td></tr>
  <tr><td>平成31年01月15日</td><td>第611回</td>
      <td><a href="emsc/pdf/611_giji.pdf">議事要旨</a></td><td></td>
      <td><a href="emsc/611_haifu.html">配布資料</a></td><td>※削除済み</td></tr>
  <tr><td>平成29年11月07日</td><td>第610回</td>
      <td><a href="emsc/pdf/610_giji.pdf">議事要旨</a></td><td></td><td></td><td>※削除</td></tr>
  <tr><td>令和8年6月8日</td><td>第608回</td>
      <td><a href="emsc/pdf/608_giji.pdf">議事要旨</a></td><td></td>
      <td><a href="emsc/608_haifu.html">配布資料</a></td><td></td></tr>
</table></body></html>
"""


def _mat(n: int, kind: str) -> Material:
    return Material(n, f"{n:03d}_{kind}", f"https://x/{n}/{kind}.pdf", kind, kind)


def _meeting(db: str, key: str, n: int, kinds=("handout",), **fields) -> int:
    store.record_meeting(key, n, [_mat(n, k) for k in kinds] or None, db_path=db)
    mid = pipeline._meeting_id(key, n, db)
    assert mid is not None
    if fields:
        store.update_meeting(mid, db_path=db, **fields)
    return mid


def _row(db: str, key: str, n: int) -> dict:
    """The meeting's stored row, as plain values (``pending_meetings`` rows omit some columns)."""
    from repower.db import PolicyMeeting
    with store.session_scope(db, commit=False) as session:
        m = session.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=n).one()
        return {"state": m.state, "retries": m.retry_count or 0, "updated_at": m.updated_at,
                "flag": m.quality_flag, "error": m.last_error}


def _nums(db: str, **kw) -> list[int]:
    return [m["meeting_num"] for m in store.pending_meetings(db_path=db, today=TODAY, **kw)]


# ── Reading the note off the index row ───────────────────────────────────────
def test_the_note_is_judged_on_the_row_not_the_label_alone():
    notes = {m["meeting_num"]: m["note"]
             for m in parse_egc_index(EGC_NOTED_INDEX, "https://www.egc.meti.go.jp/activity/index_emsc.html")}
    assert notes == {
        619: NOTE_NO_PAPERS,   # 書面開催, links nothing
        617: None,             # 書面開催 but it publishes a 議事要旨 and a 配布資料 page
        614: NOTE_NO_PAPERS,
        613: None,             # 非公開開催 with a 議事要旨 PDF
        612: None,             # 非公開開催 with a 配布資料 page: the papers may be there
        611: NOTE_REMOVED,     # 削除済み wins even though the links are still listed
        610: NOTE_REMOVED,     # …and so does the bare ※削除 spelling
        608: None,
    }


@pytest.mark.parametrize("text,links,expected", [
    ("令和8年9月28日 第619回 ※書面開催", False, NOTE_NO_PAPERS),
    ("令和8年9月28日 第619回 ※書面開催", True, None),
    ("令和8年7月22日 第613回 ※非公開開催", False, NOTE_NO_PAPERS),
    ("平成31年01月15日 第35回 議事要旨 議事録 配布資料 ※削除済み", True, NOTE_REMOVED),
    ("平成31年01月15日 第35回 ※削除済み", False, NOTE_REMOVED),
    ("令和8年6月8日 第608回 議事要旨", True, None),
    ("令和8年6月8日 第608回", False, None),   # no note, no links: undated-style row, not our call
])
def test_egc_row_note(text, links, expected):
    assert egc_row_note(text, has_links=links) == expected


# ── The classifier ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("note,kinds,checked,held,expected", [
    (NO_PAPERS, (), None, TODAY - timedelta(days=5), NO_PAPERS),
    (NO_PAPERS, (), LOOKED, TODAY - timedelta(days=5), NO_PAPERS),        # not "awaiting": not a timer
    (REMOVED, ("handout", "minutes"), LOOKED, TODAY - timedelta(days=5), REMOVED),  # the dead links
    (REMOVED, (), None, None, REMOVED),                                    # a missing date never matters
    (NO_PAPERS, (), None, TODAY + timedelta(days=3), UPCOMING),            # not held yet: still upcoming
    (None, ("handout",), None, TODAY - timedelta(days=5), READY),
    (None, ("agenda",), LOOKED, TODAY - timedelta(days=5), AWAITING),
])
def test_readiness_follows_the_index_note(note, kinds, checked, held, expected):
    assert meeting_readiness(held, kinds, today=TODAY, checked_at=checked, index_note=note) == expected


# ── Recording it ─────────────────────────────────────────────────────────────
def test_set_meeting_index_notes_sets_clears_and_ignores_unknown_rows(policy_db):
    db = policy_db
    _meeting(db, "emsc_system", 619, kinds=())
    _meeting(db, "emsc_system", 620)
    stamp = {n: _row(db, "emsc_system", n)["updated_at"] for n in (619, 620)}

    assert store.set_meeting_index_notes("emsc_system", {619: NOTE_NO_PAPERS, 620: None, 999: NOTE_REMOVED},
                                         db_path=db) == 1
    assert store.meeting_index_note("emsc_system", 619, db_path=db) == NOTE_NO_PAPERS
    assert store.meeting_index_note("emsc_system", 620, db_path=db) is None
    assert store.meeting_index_note("emsc_system", 999, db_path=db) is None
    # Idempotent, and a pure note write does not reshuffle recency-ordered views.
    assert store.set_meeting_index_notes("emsc_system", {619: NOTE_NO_PAPERS}, db_path=db) == 0
    assert {n: _row(db, "emsc_system", n)["updated_at"] for n in (619, 620)} == stamp

    # METI drops the note once papers are posted: the meeting comes back.
    assert store.set_meeting_index_notes("emsc_system", {619: None}, db_path=db) == 1
    assert store.meeting_index_note("emsc_system", 619, db_path=db) is None
    assert store.set_meeting_index_notes("emsc_system", {}, db_path=db) == 0


# ── The worklist ─────────────────────────────────────────────────────────────
def test_noted_meetings_leave_the_worklist_but_are_still_reported(policy_db):
    db = policy_db
    held = TODAY - timedelta(days=5)
    _meeting(db, "emsc_system", 1, meeting_date=held)                                       # ready
    _meeting(db, "emsc_system", 2, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)  # nothing posted
    _meeting(db, "emsc_system", 3, meeting_date=held, index_note=NOTE_REMOVED)              # deleted

    assert _nums(db) == [1]
    assert _nums(db, breadth_first=True, only_enabled=True) == [1]
    everything = {m["meeting_num"]: m["readiness"] for m in
                  store.pending_meetings(db_path=db, today=TODAY, ready_only=False)}
    assert everything == {1: READY, 2: NO_PAPERS, 3: REMOVED}
    # …and the queue view does not list them as backlog.
    q = store.queue_snapshot(db_path=db, now=datetime(2026, 10, 24, 12))
    assert [i["num"] for i in q["items"]] == [1]


def test_a_requested_noted_meeting_is_still_offered(policy_db):
    """A person asked for it: that overrides the gate, like every other readiness verdict."""
    db = policy_db
    _meeting(db, "emsc_system", 2, kinds=(), meeting_date=TODAY - timedelta(days=5),
             index_note=NOTE_NO_PAPERS, gen_requested=True)
    assert _nums(db) == [2]


def test_a_summarised_meeting_keeps_its_briefing_whatever_its_row_says(policy_db):
    db = policy_db
    _meeting(db, "emsc_system", 1, state="done", briefing_md="x", index_note=NOTE_REMOVED,
             meeting_date=TODAY - timedelta(days=40))
    assert store.meeting_gate("emsc_system", 1, {"handout"}, today=TODAY, db_path=db)[0] == READY
    assert store.reset_unready_summaries(db, today=TODAY) == {"unsummarised": 0, "cleared": 0}
    assert _row(db, "emsc_system", 1)["state"] == "done"


# ── Healing failures already on file ─────────────────────────────────────────
def test_errors_on_noted_meetings_are_cleared(policy_db):
    """emsc_system 第619回 is the live case: errored ``no_sources`` with 0 retries spent, never
    looked at. Documents METI deleted fail as ``download_failed`` and burn the retry budget; both
    go back to ``detected`` rather than reading as failures."""
    db = policy_db
    held = TODAY - timedelta(days=5)
    _meeting(db, "emsc_system", 619, kinds=(), meeting_date=held, state="error", quality_flag="no_sources",
             last_error="No usable source documents", index_note=NOTE_NO_PAPERS)
    _meeting(db, "emsc_electricityreview", 12, meeting_date=held, state="error",
             quality_flag="download_failed", last_error="404", retry_count=2, index_note=NOTE_REMOVED)
    # A genuine failure on a meeting with no note is never touched.
    _meeting(db, "emsc_system", 620, meeting_date=held, state="error", quality_flag="download_failed",
             last_error="timeout")

    assert store.reset_unready_summaries(db, today=TODAY)["cleared"] == 2

    assert _row(db, "emsc_system", 619)["state"] == "detected"
    assert _row(db, "emsc_system", 619)["flag"] is None
    assert _row(db, "emsc_electricityreview", 12)["state"] == "detected"
    assert _row(db, "emsc_electricityreview", 12)["retries"] == 0
    assert _row(db, "emsc_system", 620)["state"] == "error"


# ── The pipeline ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kinds,note", [((), NOTE_NO_PAPERS), (("handout", "minutes"), NOTE_REMOVED)])
def test_summarize_defers_a_noted_meeting_without_reading_the_page_or_notebooklm(
        policy_db, monkeypatch, kinds, note):
    db = policy_db
    mid = _meeting(db, "emsc_system", 619, kinds=kinds, meeting_date=today_jst() - timedelta(days=5),
                   index_note=note)
    monkeypatch.setattr(pipeline, "list_materials",
                        lambda *a, **k: pytest.fail("the index already said there is nothing to read"))
    monkeypatch.setattr(nb_mod, "create_notebook",
                        lambda *a, **k: pytest.fail("a deferred meeting must not reach NotebookLM"))

    out =pipeline.summarize_meeting(_egc_committee(db), 619, db_path=db)

    assert out == "deferred"
    row = next(m for m in store.pending_meetings(db_path=db, ready_only=False) if m["id"] == mid)
    assert row["state"] == "detected" and row["readiness"] == note
    assert _row(db, "emsc_system", 619)["retries"] == 0


def _egc_committee(db: str):
    from repower.policy.store import committee_or_config
    c = committee_or_config("emsc_system", db_path=db)  # a built-in EGC committee
    assert c is not None and c.is_egc
    return c


# ── Detection ────────────────────────────────────────────────────────────────
def test_detect_reads_the_egc_index_in_full_and_records_its_notes(policy_db, monkeypatch):
    """A 304 would leave the notes of already-known meetings unread for as long as the index
    stays unchanged, so an EGC index is always fetched with a body."""
    db = policy_db
    _meeting(db, "emsc_system", 619, kinds=(), meeting_date=TODAY - timedelta(days=5))
    _meeting(db, "emsc_system", 617, meeting_date=TODAY - timedelta(days=30), index_note=NOTE_NO_PAPERS)
    seen: list[bool] = []

    def fake_discover(c, **k):
        seen.append(k.get("force"))
        return Discovery("ok", [619, 617], notes={619: NOTE_NO_PAPERS, 617: None})

    monkeypatch.setattr(detect_mod, "discover_meetings", fake_discover)
    res = detect_mod.detect(["emsc_system"], db_path=db, refresh_window_days=None, watch_horizon_days=None)

    assert seen == [True]
    assert res[0]["noted"] == 2
    assert store.meeting_index_note("emsc_system", 619, db_path=db) == NOTE_NO_PAPERS
    assert store.meeting_index_note("emsc_system", 617, db_path=db) is None   # the papers arrived


def test_detect_does_not_force_other_sources(policy_db, monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(detect_mod, "discover_meetings",
                        lambda c, **k: (seen.append(k.get("force")), Discovery("unchanged", []))[1])
    detect_mod.detect(["santeii"], db_path=policy_db, refresh_window_days=None, watch_horizon_days=None)
    assert seen == [False]


# ── What the readers see ─────────────────────────────────────────────────────
def test_export_labels_noted_meetings(policy_db):
    db = policy_db
    held = today_jst() - timedelta(days=5)
    _meeting(db, "santeii", 1, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)
    _meeting(db, "santeii", 2, meeting_date=held, index_note=NOTE_REMOVED)
    _meeting(db, "santeii", 3, meeting_date=held, state="error", quality_flag="no_sources",
             index_note=NOTE_NO_PAPERS)

    snap = {m["num"]: m for m in build_policy_snapshot(db)["meetings"] if m["com"] == "santeii"}
    assert "No papers" in snap[1]["emptyTitle"] and "資料なし" in snap[1]["emptyTitle"]
    assert "removed" in snap[2]["emptyTitle"] and "削除" in snap[2]["emptyTitle"]
    assert snap[1]["status"] != "pending" and snap[2]["status"] != "pending"
