"""The committee index's own word on a meeting. Each EGC row is date | 第N回 | 議事要旨 | 議事録 |
配布資料 | 動画, and the ※ remarks sit in the last (動画, video) cell: ※書面開催 / ※非公開開催 (a written
or closed meeting) and ※削除[済み] (the recording was taken down) all explain a missing *video*, not
missing papers. A row that links no document at all has nothing to read, so it leaves the worklist
instead of failing as ``no_sources`` and spending a retry every run (emsc_system 第619回: ※書面開催,
no links); a row that links papers is summarised whatever its remark says, and papers already on
file outrank the note.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from repower.dashboard.export_web import build_policy_catalog, build_policy_snapshot, build_policy_status
from repower.policy import detect as detect_mod
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, store
from repower.policy.scraper import (
    NOTE_NO_PAPERS,
    Discovery,
    Material,
    egc_row_note,
    parse_egc_index,
)
from repower.policy.store import AWAITING, NO_PAPERS, READY, UPCOMING, meeting_readiness
from repower.timeutil import today_jst

TODAY = date(2026, 10, 24)
LOOKED = datetime(2026, 10, 22, tzinfo=UTC)

# The value an earlier version stored for ※削除[済み]. Nothing writes or reads it any more, but
# databases written meanwhile still carry it, and it must mean nothing.
RETIRED_NOTE = "removed"

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
  <tr><td>平成29年10月02日</td><td>第609回</td><td></td><td></td><td></td><td>※削除済み</td></tr>
  <tr><td>令和8年6月8日</td><td>第608回</td>
      <td><a href="emsc/pdf/608_giji.pdf">議事要旨</a></td><td></td>
      <td><a href="emsc/608_haifu.html">配布資料</a></td><td></td></tr>
</table></body></html>
"""

# index_electricityreview.html as fetched (two rows, trimmed to the table cells) plus a ※削除済み
# row that links nothing. 第35回's papers are all still linked: the remark is about its video.
EGC_REVIEW_INDEX = """
<html><body><table>
<tr><td>平成31年02月18日</td><td>第36回</td>
  <td><a href="emsc_electricity/pdf/036_gizigaiyo.pdf">議事要旨</a></td>
  <td><a href="emsc_electricity/pdf/036_gijiroku.pdf">議事録</a></td>
  <td><a href="emsc_electricity/036_haifu.html">配布資料</a></td>
  <td><a href="https://www.youtube.com/watch?v=JXbW7gEZ6U8">動画1</a></td></tr>
<tr><td>平成31年01月15日</td><td>第35回</td>
  <td><a href="emsc_electricity/pdf/035_gizigaiyo.pdf">議事要旨</a></td>
  <td><a href="emsc_electricity/pdf/035_gijiroku.pdf">議事録</a></td>
  <td><a href="emsc_electricity/035_haifu.html">配布資料</a></td>
  <td>※削除済み</td></tr>
<tr><td>平成30年12月10日</td><td>第34回</td><td></td><td></td><td></td><td>※削除済み</td></tr>
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
                "flag": m.quality_flag, "error": m.last_error, "note": m.index_note}


def _count(db: str, key: str, n: int) -> int:
    """How many rows the table holds for the meeting (0 or 1)."""
    from repower.db import PolicyMeeting
    with store.session_scope(db, commit=False) as session:
        return session.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=n).count()


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
        611: None,             # 削除済み is the same kind of remark: its papers are still linked
        610: None,             # …and so is the bare ※削除 spelling
        609: NOTE_NO_PAPERS,   # 削除済み on a row that links nothing
        608: None,
    }


def test_a_removed_video_does_not_hide_the_papers_the_row_still_links():
    """index_electricityreview.html: 第35回 is ※削除済み (its video) yet links 議事要旨, 議事録 and
    配布資料. Reading that as "documents removed" dropped 35 of the page's 39 meetings."""
    rows = {m["meeting_num"]: m for m in parse_egc_index(
        EGC_REVIEW_INDEX, "https://www.egc.meti.go.jp/activity/index_electricityreview.html")}

    assert {n: m["note"] for n, m in rows.items()} == {
        36: None,              # has a 動画 link, no remark
        35: None,              # ※削除済み, but the papers are linked
        34: NOTE_NO_PAPERS,    # ※削除済み and nothing linked: nothing to read
    }
    assert [p["url"].rsplit("/", 1)[-1] for p in rows[35]["direct_pdfs"]] == [
        "035_gizigaiyo.pdf", "035_gijiroku.pdf"]
    assert rows[35]["haifu_url"].endswith("emsc_electricity/035_haifu.html")


@pytest.mark.parametrize("text,links,expected", [
    ("令和8年9月28日 第619回 ※書面開催", False, NOTE_NO_PAPERS),
    ("令和8年9月28日 第619回 ※書面開催", True, None),
    ("令和8年7月22日 第613回 ※非公開開催", False, NOTE_NO_PAPERS),
    ("令和8年7月22日 第613回 ※非公開開催", True, None),
    ("平成31年01月15日 第35回 議事要旨 議事録 配布資料 ※削除済み", True, None),
    ("平成31年01月15日 第35回 ※削除済み", False, NOTE_NO_PAPERS),
    ("平成31年01月15日 第35回 議事要旨 ※削除", True, None),
    ("平成31年01月15日 第35回 ※削除", False, NOTE_NO_PAPERS),
    ("令和8年6月8日 第608回 議事要旨", True, None),
    ("令和8年6月8日 第608回", False, None),   # no note, no links: undated-style row, not our call
])
def test_egc_row_note(text, links, expected):
    assert egc_row_note(text, has_links=links) == expected


# ── The classifier ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("note,kinds,checked,held,expected", [
    (NO_PAPERS, (), None, TODAY - timedelta(days=5), NO_PAPERS),
    (NO_PAPERS, (), LOOKED, TODAY - timedelta(days=5), NO_PAPERS),        # not "awaiting": not a timer
    (NO_PAPERS, ("agenda",), LOOKED, TODAY - timedelta(days=5), NO_PAPERS),  # an agenda is not a paper
    (NO_PAPERS, (), None, None, NO_PAPERS),                                # a missing date never matters
    # A paper on file outranks the note. The note is only the row as last read from the *main*
    # index, and a row that has moved to a log page keeps it for good, so it cannot be trusted over
    # documents we hold — nor may it strand a meeting already mid-pipeline.
    (NO_PAPERS, ("minutes",), None, TODAY - timedelta(days=5), READY),
    (NO_PAPERS, ("handout", "minutes"), LOOKED, TODAY - timedelta(days=5), READY),
    (NO_PAPERS, ("brief",), LOOKED, None, READY),
    (NO_PAPERS, (), None, TODAY + timedelta(days=3), UPCOMING),            # not held yet: still upcoming
    (NO_PAPERS, ("handout",), None, TODAY + timedelta(days=3), UPCOMING),
    # The retired note means nothing: the meeting is judged on its date and documents alone.
    (RETIRED_NOTE, ("handout", "minutes"), LOOKED, TODAY - timedelta(days=5), READY),
    (RETIRED_NOTE, (), None, TODAY - timedelta(days=5), READY),
    (RETIRED_NOTE, ("agenda",), LOOKED, TODAY - timedelta(days=5), AWAITING),
    (RETIRED_NOTE, (), None, TODAY + timedelta(days=3), UPCOMING),
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

    assert store.set_meeting_index_notes("emsc_system", {619: NOTE_NO_PAPERS, 620: None, 999: NOTE_NO_PAPERS},
                                         db_path=db) == 1
    assert _row(db, "emsc_system", 619)["note"] == NOTE_NO_PAPERS
    assert _row(db, "emsc_system", 620)["note"] is None
    assert _count(db, "emsc_system", 999) == 0       # an unknown row is ignored, not created
    # Idempotent, and a pure note write does not reshuffle recency-ordered views.
    assert store.set_meeting_index_notes("emsc_system", {619: NOTE_NO_PAPERS}, db_path=db) == 0
    assert {n: _row(db, "emsc_system", n)["updated_at"] for n in (619, 620)} == stamp

    # METI drops the note once papers are posted: the meeting comes back.
    assert store.set_meeting_index_notes("emsc_system", {619: None}, db_path=db) == 1
    assert _row(db, "emsc_system", 619)["note"] is None
    assert store.set_meeting_index_notes("emsc_system", {}, db_path=db) == 0


# ── The worklist ─────────────────────────────────────────────────────────────
def test_a_noted_meeting_with_nothing_on_file_leaves_the_worklist_but_is_still_reported(policy_db):
    db = policy_db
    held = TODAY - timedelta(days=5)
    _meeting(db, "emsc_system", 1, meeting_date=held)                                       # ready
    _meeting(db, "emsc_system", 2, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)  # nothing posted

    assert _nums(db) == [1]
    assert _nums(db, breadth_first=True, only_enabled=True) == [1]
    everything = {m["meeting_num"]: m["readiness"] for m in
                  store.pending_meetings(db_path=db, today=TODAY, ready_only=False)}
    assert everything == {1: READY, 2: NO_PAPERS}
    # …and the queue view does not list it as backlog.
    q = store.queue_snapshot(db_path=db, now=datetime(2026, 10, 24, 12))
    assert [i["num"] for i in q["items"]] == [1]


def test_papers_on_file_outrank_the_note_in_the_worklist(policy_db):
    """A note left on a row that moved to a log page is never cleared, and the retired ``removed``
    is still in old databases: neither may hide a meeting whose papers we hold."""
    db = policy_db
    held = TODAY - timedelta(days=5)
    _meeting(db, "emsc_system", 3, meeting_date=held, index_note=NOTE_NO_PAPERS)
    _meeting(db, "emsc_system", 4, meeting_date=held, index_note=RETIRED_NOTE)

    assert _nums(db) == [4, 3]
    assert {m["meeting_num"]: m["readiness"] for m in
            store.pending_meetings(db_path=db, today=TODAY, ready_only=False)} == {3: READY, 4: READY}


@pytest.mark.parametrize("fields", [
    {"state": "generating", "notebook_id": "nb-7"},
    {"state": "ingesting", "notebook_id": "nb-7"},
    {"state": "error", "quality_flag": "download_blocked", "retry_count": 1, "notebook_id": "nb-7"},
], ids=["generating", "ingesting", "errored-with-notebook"])
def test_a_noted_meeting_already_mid_pipeline_stays_in_the_worklist(policy_db, fields):
    """``resume`` and the retry draw on the same worklist as a first attempt. With the note ranked
    above the papers on file, a meeting that had already started — and owns a notebook — dropped
    out of it and was never finished or cleaned up."""
    db = policy_db
    _meeting(db, "emsc_system", 7, kinds=("minutes",), meeting_date=TODAY - timedelta(days=5),
             index_note=NOTE_NO_PAPERS, **fields)

    assert _nums(db) == [7]
    got = store.pending_meetings(db_path=db, today=TODAY, ready_only=False)
    assert [(m["meeting_num"], m["state"], m["readiness"]) for m in got] == [(7, fields["state"], READY)]


def test_a_requested_noted_meeting_is_still_offered(policy_db):
    """A person asked for it: that overrides the gate, like every other readiness verdict."""
    db = policy_db
    _meeting(db, "emsc_system", 2, kinds=(), meeting_date=TODAY - timedelta(days=5),
             index_note=NOTE_NO_PAPERS, gen_requested=True)
    assert _nums(db) == [2]


def test_a_summarised_meeting_keeps_its_briefing_whatever_its_row_says(policy_db):
    db = policy_db
    _meeting(db, "emsc_system", 1, state="done", briefing_md="x", index_note=NOTE_NO_PAPERS,
             meeting_date=TODAY - timedelta(days=40))
    assert store.meeting_gate("emsc_system", 1, {"handout"}, today=TODAY, db_path=db)[0] == READY
    assert store.reset_unready_summaries(db, today=TODAY) == {"unsummarised": 0, "cleared": 0}
    assert _row(db, "emsc_system", 1)["state"] == "done"


# ── Healing failures already on file ─────────────────────────────────────────
def test_errors_on_noted_meetings_with_nothing_to_read_are_cleared(policy_db):
    """emsc_system 第619回 is the live case: errored ``no_sources`` with 0 retries spent, never
    looked at. A noted meeting whose only file is an agenda that would not download fails as
    ``download_failed`` and burns the retry budget; both go back to ``detected`` rather than
    reading as failures."""
    db = policy_db
    held = TODAY - timedelta(days=5)
    _meeting(db, "emsc_system", 619, kinds=(), meeting_date=held, state="error", quality_flag="no_sources",
             last_error="No usable source documents", index_note=NOTE_NO_PAPERS)
    _meeting(db, "emsc_electricityreview", 12, kinds=("agenda",), meeting_date=held, state="error",
             quality_flag="download_failed", last_error="404", retry_count=2, index_note=NOTE_NO_PAPERS)
    # A genuine failure on a meeting with no note is never touched.
    _meeting(db, "emsc_system", 620, meeting_date=held, state="error", quality_flag="download_failed",
             last_error="timeout")

    assert store.reset_unready_summaries(db, today=TODAY)["cleared"] == 2

    assert _row(db, "emsc_system", 619)["state"] == "detected"
    assert _row(db, "emsc_system", 619)["flag"] is None
    assert _row(db, "emsc_electricityreview", 12)["state"] == "detected"
    assert _row(db, "emsc_electricityreview", 12)["retries"] == 0
    assert _row(db, "emsc_system", 620)["state"] == "error"


def test_a_real_error_on_a_noted_meeting_that_has_papers_is_left_alone(policy_db):
    """With papers on file the note proves nothing: a failed download or a failed generation on
    such a meeting is a real failure (it still has its retries to spend), not something to wipe."""
    db = policy_db
    held = TODAY - timedelta(days=5)
    _meeting(db, "emsc_system", 7, kinds=("handout", "minutes"), meeting_date=held, state="error",
             quality_flag="download_failed", last_error="404 on 007_handout", retry_count=2,
             index_note=NOTE_NO_PAPERS)
    # …and neither is one on a row still carrying the retired note.
    _meeting(db, "emsc_system", 8, kinds=("handout",), meeting_date=held, state="error",
             quality_flag="download_failed", last_error="timeout", retry_count=1, index_note=RETIRED_NOTE)

    assert store.reset_unready_summaries(db, today=TODAY) == {"unsummarised": 0, "cleared": 0}

    seven = _row(db, "emsc_system", 7)
    assert (seven["state"], seven["flag"], seven["error"], seven["retries"]) == (
        "error", "download_failed", "404 on 007_handout", 2)
    eight = _row(db, "emsc_system", 8)
    assert (eight["state"], eight["flag"], eight["error"], eight["retries"]) == (
        "error", "download_failed", "timeout", 1)


# ── The pipeline ─────────────────────────────────────────────────────────────
def test_summarize_defers_a_noted_meeting_with_nothing_on_file_once_the_page_still_lists_nothing(
        policy_db, monkeypatch):
    """The note is only as fresh as the last detect, so the page is read again; when it still
    lists nothing the gate defers the meeting — no error, no retry spent, no NotebookLM."""
    db = policy_db
    mid = _meeting(db, "emsc_system", 619, kinds=(), meeting_date=today_jst() - timedelta(days=5),
                   index_note=NOTE_NO_PAPERS)
    listed: list[int] = []
    monkeypatch.setattr(pipeline, "list_materials", lambda c, n, **k: listed.append(n) or [])
    monkeypatch.setattr(nb_mod, "create_notebook",
                        lambda *a, **k: pytest.fail("a deferred meeting must not reach NotebookLM"))

    out = pipeline.summarize_meeting(_egc_committee(db), 619, db_path=db)

    assert out == "deferred"
    assert listed == [619]
    row = next(m for m in store.pending_meetings(db_path=db, ready_only=False) if m["id"] == mid)
    assert row["state"] == "detected" and row["readiness"] == NO_PAPERS
    assert _row(db, "emsc_system", 619)["retries"] == 0


def test_summarize_goes_ahead_on_a_noted_meeting_that_has_papers_on_file(policy_db, monkeypatch, tmp_path):
    db = policy_db
    _meeting(db, "emsc_system", 619, kinds=("handout", "minutes"),
             meeting_date=today_jst() - timedelta(days=5), index_note=NOTE_NO_PAPERS)
    monkeypatch.setattr(pipeline, "_scratch", lambda: tmp_path / "scratch")
    monkeypatch.setattr(pipeline, "list_materials",
                        lambda *a, **k: pytest.fail("papers are on file: there is nothing to look up"))
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "not_found")  # stops short of NotebookLM
    monkeypatch.setattr(nb_mod, "create_notebook", lambda *a, **k: pytest.fail("download was stubbed to fail"))

    assert pipeline.summarize_meeting(_egc_committee(db), 619, db_path=db) == "error"

    assert _row(db, "emsc_system", 619)["flag"] == "download_failed"   # it got as far as its papers


@pytest.mark.parametrize("page,flag", [
    ((), "no_sources"),                           # still nothing: an honest failure, from a fresh read
    (("minutes", "handout"), "download_failed"),  # posted since the note: the request goes ahead
], ids=["page-still-empty", "papers-posted-since"])
def test_a_requested_noted_meeting_reads_the_page_instead_of_trusting_the_note(
        policy_db, monkeypatch, tmp_path, page, flag):
    """``gen_requested`` bypasses the gate, so the list on file is all the request is judged on —
    and with nothing readable there it must be refreshed. Skipping the read because of the note
    answered a person's request from stale data: it failed ``no_sources`` ("lists 0 material(s)")
    and spent a slot even when the papers had been posted since."""
    db = policy_db
    _meeting(db, "emsc_system", 619, kinds=(), meeting_date=today_jst() - timedelta(days=5),
             index_note=NOTE_NO_PAPERS, gen_requested=True)
    listed: list[int] = []
    monkeypatch.setattr(pipeline, "_scratch", lambda: tmp_path / "scratch")
    monkeypatch.setattr(pipeline, "list_materials",
                        lambda c, n, **k: listed.append(n) or [_mat(n, kind) for kind in page])
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "not_found")  # stops short of NotebookLM
    monkeypatch.setattr(nb_mod, "create_notebook", lambda *a, **k: pytest.fail("download was stubbed to fail"))

    assert pipeline.summarize_meeting(_egc_committee(db), 619, db_path=db) == "error"

    assert listed == [619]
    row = _row(db, "emsc_system", 619)
    assert row["flag"] == flag
    assert len(store.meeting_materials("emsc_system", 619, db_path=db)) == len(page)  # what the page lists is on file
    if not page:
        assert "lists 0 material(s)" in row["error"]


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
    assert _row(db, "emsc_system", 619)["note"] == NOTE_NO_PAPERS
    assert _row(db, "emsc_system", 617)["note"] is None   # the papers arrived


def test_detect_does_not_force_other_sources(policy_db, monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(detect_mod, "discover_meetings",
                        lambda c, **k: (seen.append(k.get("force")), Discovery("unchanged", []))[1])
    detect_mod.detect(["santeii"], db_path=policy_db, refresh_window_days=None, watch_horizon_days=None)
    assert seen == [False]


# ── Not re-listing what has nothing to list ──────────────────────────────────
# A listing that finds nothing is never stamped, so without the skip every catch-up re-listed a noted
# meeting — an EGC index fetch each, against the host's 16 requests per 300 s.
def test_a_noted_meeting_with_no_materials_is_not_backfilled(policy_db):
    db = policy_db
    _meeting(db, "emsc_system", 1, kinds=(), index_note=NOTE_NO_PAPERS)   # its row links nothing
    _meeting(db, "emsc_system", 2, kinds=())                               # an ordinary material-less meeting
    _meeting(db, "emsc_system", 3, kinds=(), index_note=RETIRED_NOTE)      # the retired note means nothing

    assert store.meetings_missing_materials("emsc_system", db_path=db) == [3, 2]


def test_backfill_materials_does_not_relist_a_noted_meeting(policy_db, monkeypatch):
    db = policy_db
    _meeting(db, "emsc_system", 1, kinds=(), index_note=NOTE_NO_PAPERS)
    _meeting(db, "emsc_system", 2, kinds=())
    listed: list[int] = []
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **k: listed.append(n) or [])
    monkeypatch.setattr(detect_mod, "budget_exhausted", lambda url: False)
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)

    res = detect_mod.backfill_materials(["emsc_system"], db_path=db)

    assert listed == [2]
    assert next(r for r in res if r["key"] == "emsc_system")["checked"] == 1


def test_recent_meeting_nums_skips_an_unsummarised_noted_meeting_only(policy_db):
    """The 7-day refresh re-reads a meeting's document list; a noted one has none to find. A
    summarised meeting is never judged by its note, so it keeps being refreshed."""
    db = policy_db
    held = TODAY - timedelta(days=2)
    _meeting(db, "emsc_system", 1, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)
    _meeting(db, "emsc_system", 2, kinds=("agenda",), meeting_date=held)
    _meeting(db, "emsc_system", 3, meeting_date=held, state="done", briefing_md="x", index_note=NOTE_NO_PAPERS)
    _meeting(db, "emsc_system", 4, kinds=(), meeting_date=held, index_note=RETIRED_NOTE)

    assert store.recent_meeting_nums("emsc_system", TODAY - timedelta(days=7), db_path=db) == [4, 3, 2]


def test_detect_refresh_does_not_re_read_a_noted_meeting(policy_db, monkeypatch):
    db = policy_db
    held = TODAY - timedelta(days=2)
    _meeting(db, "emsc_system", 1, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)
    _meeting(db, "emsc_system", 2, kinds=("agenda",), meeting_date=held)
    listed: list[int] = []
    monkeypatch.setattr(detect_mod, "discover_meetings", lambda c, **k: Discovery("unchanged", []))
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **k: listed.append(n) or [])
    monkeypatch.setattr(detect_mod, "budget_exhausted", lambda url: False)
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)

    detect_mod.detect(["emsc_system"], db_path=db, today=TODAY)

    assert listed == [2]


# ── What the readers see ─────────────────────────────────────────────────────
def test_export_labels_noted_meetings(policy_db):
    db = policy_db
    held = today_jst() - timedelta(days=5)
    _meeting(db, "santeii", 1, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)
    # The red row such a meeting used to be reads as "no papers", not as a failure.
    _meeting(db, "santeii", 2, kinds=(), meeting_date=held, state="error", quality_flag="no_sources",
             index_note=NOTE_NO_PAPERS)
    # Papers on file outrank the note: it is queued like any other, and a real failure shows as one.
    _meeting(db, "santeii", 3, meeting_date=held, index_note=NOTE_NO_PAPERS)
    _meeting(db, "santeii", 4, meeting_date=held, state="error", quality_flag="download_failed",
             last_error="404", index_note=NOTE_NO_PAPERS)
    _meeting(db, "santeii", 5, meeting_date=held, index_note=RETIRED_NOTE)

    snap = {m["num"]: m for m in build_policy_snapshot(db)["meetings"] if m["com"] == "santeii"}
    assert [snap[n]["status"] for n in (1, 2, 3, 4, 5)] == [
        "no_papers", "no_papers", "pending", "error", "pending"]
    assert "No papers" in snap[1]["emptyTitle"] and "資料なし" in snap[1]["emptyTitle"]
    assert "Summary pending" in snap[3]["emptyTitle"]
    assert "removed" not in snap[5]["emptyTitle"].lower()


def test_the_manage_table_judges_a_meeting_by_its_note_too(policy_db):
    """``build_policy_status`` derives readiness on its own path. Dropping the note from it flipped
    most of a real database's meetings with no test noticing, so pin it as the cards are pinned."""
    db = policy_db
    held = today_jst() - timedelta(days=5)
    _meeting(db, "santeii", 1, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)
    _meeting(db, "santeii", 2, kinds=(), meeting_date=held, state="error", quality_flag="no_sources",
             index_note=NOTE_NO_PAPERS)
    _meeting(db, "santeii", 3, kinds=("minutes",), meeting_date=held, index_note=NOTE_NO_PAPERS)  # papers win
    _meeting(db, "santeii", 4, kinds=(), meeting_date=held)                                       # never looked
    _meeting(db, "santeii", 5, kinds=(), meeting_date=held, index_note=RETIRED_NOTE)

    got = {m["num"]: m["readiness"] for m in build_policy_status(db)["meetings"] if m["com"] == "santeii"}

    assert got == {1: NO_PAPERS, 2: NO_PAPERS, 3: READY, 4: READY, 5: READY}


# The committee rollup (Deep Dive header, Manage PEND column, "failing" filter) is built by one function
# fed by two callers, so both are checked.
def _committee_row(db: str, key: str, via: str) -> dict:
    rows = build_policy_catalog(db) if via == "catalog" else build_policy_snapshot(db)["committees"]
    return next(c for c in rows if c["key"] == key)


@pytest.mark.parametrize("via", ["catalog", "snapshot"])
def test_the_rollup_does_not_count_a_meeting_with_nothing_to_read(policy_db, via):
    """Its card says "No papers published", so calling it pending — or, while it is still in ``error``,
    errored — put "3 pending" in the header and could flag the committee as failing for meetings that
    will never be summarised."""
    db = policy_db
    held = today_jst() - timedelta(days=5)
    _meeting(db, "santeii", 1, meeting_date=held)                                       # waiting for its summary
    _meeting(db, "santeii", 2, kinds=(), meeting_date=held, index_note=NOTE_NO_PAPERS)  # nothing to read
    # Its old failure, and the meeting touched last:
    _meeting(db, "santeii", 3, kinds=(), meeting_date=held, state="error", quality_flag="no_sources",
             last_error="No usable source documents", index_note=NOTE_NO_PAPERS)

    row = _committee_row(db, "santeii", via)

    assert (row["done"], row["pending"], row["error"]) == (0, 1, 0)
    assert row["meetings"] == 3                    # still one of the committee's meetings
    # The "failing" filter also reads the newest event: that failure is not it.
    assert row["lastUpdateState"] != "error" and row["lastUpdateError"] is None


@pytest.mark.parametrize("via", ["catalog", "snapshot"])
def test_the_rollup_still_counts_what_the_cards_call_pending_or_errored(policy_db, via):
    db = policy_db
    today = today_jst()
    held = today - timedelta(days=5)
    _meeting(db, "santeii", 1, meeting_date=held, index_note=NOTE_NO_PAPERS)       # papers outrank the note: pending
    _meeting(db, "santeii", 2, meeting_date=held, state="error", quality_flag="download_failed",
             last_error="404", index_note=NOTE_NO_PAPERS)                          # …so this is a real failure
    _meeting(db, "santeii", 3, kinds=(), meeting_date=held, index_note=RETIRED_NOTE)    # retired note: pending
    _meeting(db, "santeii", 4, kinds=(), meeting_date=today + timedelta(days=3),
             index_note=NOTE_NO_PAPERS)                                            # upcoming keeps its treatment
    _meeting(db, "santeii", 5, kinds=("agenda",), meeting_date=held,
             materials_checked_at=datetime.now(UTC))                               # awaiting keeps its treatment
    _meeting(db, "santeii", 6, kinds=(), meeting_date=held, state="done", briefing_md="x",
             index_note=NOTE_NO_PAPERS)                                            # summarised, whatever its row says

    row = _committee_row(db, "santeii", via)

    assert (row["done"], row["pending"], row["error"]) == (1, 4, 1)
