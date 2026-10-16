"""The summarisation queue view: `store.queue_snapshot`, the drain stamps the pipeline writes,
and the `queue` block of the status payload the Manage → Queue view reads.

The snapshot must be the *same* worklist `policy run --committee all` takes — it calls the same
function — so these tests pin the interesting orderings and the things a reader would otherwise
misread (an untracked committee, a retry-capped meeting, a capped list vs the whole queue).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from repower.dashboard import export_web
from repower.db import PolicyMeeting
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, store
from repower.policy.scraper import Material

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _mat(n: int) -> Material:
    return Material(n, f"{n:03d}_01", f"https://x/{n}/01.pdf", "資料1", "handout")


def _meeting(db: str, key: str, n: int, **fields) -> None:
    store.record_meeting(key, n, [_mat(n)], db_path=db)
    if fields:
        store.update_meeting(pipeline._meeting_id(key, n, db), db_path=db, **fields)


def _done(db: str, key: str, n: int, **fields) -> None:
    _meeting(db, key, n, state="done", briefing_md="# 要約", **fields)


def _snap(db: str, **kw) -> dict:
    return store.queue_snapshot(db_path=db, now=NOW, **kw)


def _order(q: dict) -> list[tuple[str, int]]:
    return [(i["com"], i["num"]) for i in q["items"]]


# ── The worklist ─────────────────────────────────────────────────────────────
def test_snapshot_labels_each_kind_and_numbers_from_one(policy_db):
    db = policy_db
    _meeting(db, "santeii", 5)                                          # never summarised
    _meeting(db, "santeii", 4, state="error", retry_count=1)            # failed once: retried
    _done(db, "santeii", 3, resummarise_requested=True)                 # a late paper: update
    q = _snap(db)

    kinds = {(i["com"], i["num"]): i["kind"] for i in q["items"]}
    assert kinds == {("santeii", 5): "new", ("santeii", 4): "retry", ("santeii", 3): "update"}
    assert [i["rank"] for i in q["items"]] == [1, 2, 3]
    assert q["totals"] == {"new": 1, "update": 1, "retry": 1, "requested": 0}
    assert q["total"] == 3 and q["truncated"] == 0
    retry = next(i for i in q["items"] if i["kind"] == "retry")
    assert retry["retries"] == 1 and retry["state"] == "error"


def test_snapshot_is_exactly_the_worklist_the_run_takes(policy_db):
    """Same function, same order — so the view cannot drift from what the run does."""
    db = policy_db
    for key, nums in (("santeii", (5, 4, 3)), ("saisei_kano", (9, 8)), ("doji_shijo", (2,))):
        for n in nums:
            _meeting(db, key, n)
    _done(db, "santeii", 1, resummarise_requested=True)

    expected = [(w["committee_key"], w["meeting_num"]) for w in store.pending_meetings(
        db_path=db, only_enabled=True, breadth_first=True, include_resummarise=True)]

    assert _order(_snap(db)) == expected


def test_a_meeting_moved_to_the_front_ranks_first_and_is_marked(policy_db):
    db = policy_db
    _meeting(db, "santeii", 5)
    _meeting(db, "doji_shijo", 2)
    store.request_generation("doji_shijo", 2, db_path=db)
    q = _snap(db)
    assert q["items"][0]["com"] == "doji_shijo" and q["items"][0]["requested"] is True
    assert q["totals"]["requested"] == 1
    assert q["byCom"]["doji_shijo"]["requested"] == 1


def test_queue_leaves_out_untracked_committees_and_retry_capped_meetings(policy_db):
    db = policy_db
    _meeting(db, "santeii", 5)
    _meeting(db, "doji_shijo", 2)
    store.set_committee_enabled("doji_shijo", False, db_path=db)        # untracked: a run skips it
    _meeting(db, "santeii", 4, state="error", retry_count=store.MAX_RETRIES)   # given up on
    q = _snap(db)
    assert _order(q) == [("santeii", 5)] and q["total"] == 1


def test_an_update_follows_the_newest_pending_meetings_but_not_the_whole_backlog(policy_db):
    """The ordering rule, made visible: with a deep backlog the update ranks right after the
    committees' newest pending meetings. It once ranked 291 of 291 (about 37 daily runs away)."""
    db = policy_db
    for n in range(1, 41):
        _meeting(db, "santeii", n)                    # a deep backlog in one committee
    _meeting(db, "saisei_kano", 5)
    _done(db, "doji_shijo", 9, resummarise_requested=True)

    q = _snap(db)
    update = next(i for i in q["items"] if i["kind"] == "update")

    assert update["rank"] == 3                        # santeii's newest, saisei_kano's newest, then it
    assert update["rank"] <= q["cap"]                 # so the next daily run takes it
    assert q["total"] == 42


def test_an_update_alone_is_still_queued(policy_db):
    db = policy_db
    _done(db, "santeii", 9, resummarise_requested=True)
    assert _order(_snap(db)) == [("santeii", 9)]


def test_items_are_capped_but_totals_and_by_committee_count_the_whole_queue(policy_db):
    db = policy_db
    for n in range(1, 8):
        _meeting(db, "santeii", n)
    for n in range(1, 4):
        _meeting(db, "saisei_kano", n)
    q = _snap(db, max_items=4)

    assert len(q["items"]) == 4 and q["truncated"] == 6 and q["total"] == 10
    assert q["totals"]["new"] == 10
    assert q["byCom"] == {"santeii": {"new": 7, "update": 0, "retry": 0, "requested": 0},
                          "saisei_kano": {"new": 3, "update": 0, "retry": 0, "requested": 0}}
    assert list(q["byCom"]) == ["santeii", "saisei_kano"]   # biggest first


def test_updates_retries_and_moved_to_front_are_listed_whatever_their_rank(policy_db):
    """An update can rank past a plain list cap (here: after each committee's newest pending
    meeting, which is more than the cap), and the "Update" filter would then find nothing — the
    chip said 1, the filtered list said nothing, when it ranked 291."""
    db = policy_db
    for n in range(1, 21):
        _meeting(db, "santeii", n)                                           # ordinary backlog
    _meeting(db, "saisei_kano", 3)
    _meeting(db, "doji_shijo", 2, state="error", retry_count=1)              # a retry
    _done(db, "youryou_kentoukai", 7, resummarise_requested=True)            # the update
    q = _snap(db, max_items=2)

    by_kind = {i["kind"]: i for i in q["items"] if i["kind"] != "new"}
    assert set(by_kind) == {"update", "retry"}
    assert by_kind["update"]["rank"] == 4        # after the three committees' newest, not last…
    assert by_kind["update"]["rank"] < q["total"]
    assert by_kind["update"]["rank"] > 2         # …but beyond the list cap, and still listed
    assert sum(1 for i in q["items"] if i["kind"] == "new") <= 2
    # truncated counts only the ordinary new meetings left out
    assert q["truncated"] == q["total"] - len(q["items"])
    assert [i["rank"] for i in q["items"]] == sorted(i["rank"] for i in q["items"])


def test_a_meeting_moved_to_the_front_is_listed_even_with_a_zero_cap(policy_db):
    db = policy_db
    _meeting(db, "santeii", 5)
    _meeting(db, "doji_shijo", 2)
    store.request_generation("doji_shijo", 2, db_path=db)
    q = _snap(db, max_items=0)
    assert [(i["com"], i["requested"]) for i in q["items"]] == [("doji_shijo", True)]
    assert q["truncated"] == 1


def test_an_empty_queue_is_a_valid_snapshot(policy_db):
    q = _snap(policy_db)
    assert q["total"] == 0 and q["items"] == [] and q["byCom"] == {} and q["recent"] == []
    assert q["cap"] == store.DAILY_RUN_CAP


# ── Recently drained ─────────────────────────────────────────────────────────
def test_recent_lists_what_drained_in_the_window_newest_first(policy_db):
    db = policy_db
    _done(db, "santeii", 1, summarised_at=NOW - timedelta(hours=3))
    _done(db, "santeii", 2, summarised_at=NOW - timedelta(days=2),
          resummarised_at=NOW - timedelta(days=2))
    _done(db, "santeii", 3, summarised_at=NOW - timedelta(days=30))     # outside the window
    q = _snap(db)
    assert [(r["num"], r["kind"]) for r in q["recent"]] == [(1, "new"), (2, "update")]


def test_recent_falls_back_for_meetings_summarised_before_the_stamps_existed(policy_db):
    """No summarised_at, but a generation time and a recent touch: shown, with kind unknown."""
    db = policy_db
    _done(db, "santeii", 1, gen_seconds=120.0)                           # updated_at = now (real clock)
    q = store.queue_snapshot(db_path=db)                                 # real clock, to match updated_at
    assert [(r["num"], r["kind"]) for r in q["recent"]] == [(1, None)]
    # …but not a done meeting with no generation time (it was never run through the pipeline)
    _done(db, "santeii", 2)
    assert [r["num"] for r in store.queue_snapshot(db_path=db)["recent"]] == [1]


def test_recent_is_capped(policy_db):
    db = policy_db
    for n in range(1, 8):
        _done(db, "santeii", n, summarised_at=NOW - timedelta(hours=n))
    assert len(_snap(policy_db, max_recent=3)["recent"]) == 3


# ── Drain stamps written by the pipeline ─────────────────────────────────────
def _stub_notebooklm(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pipeline, "_scratch", lambda: tmp_path / "scratch")
    monkeypatch.setattr(pipeline, "_download_pdf", lambda url, dest, **kw: (
        dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"%PDF-1.4"), "ok")[-1])
    monkeypatch.setattr(pipeline.nb, "create_notebook", lambda *a, **k: "nb1")
    monkeypatch.setattr(pipeline.nb, "add_source", lambda nb_id, path: f"src:{Path(path).name}")
    monkeypatch.setattr(pipeline.nb, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(pipeline, "_ocr_guard", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.nb, "generate_report", lambda *a, **k: "task1")
    monkeypatch.setattr(pipeline.nb, "wait_artifact", lambda *a, **k: True)
    monkeypatch.setattr(
        pipeline.nb, "download_report",
        lambda nb_id, task_id, out: (out.write_text("## 要約\n" + "y" * 500, encoding="utf-8"), True)[1])
    monkeypatch.setattr(pipeline.nb, "ask", lambda *a, **k: {"answer": "ok"})
    monkeypatch.setattr(pipeline.nb, "delete_notebook", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "regenerate_running_doc", lambda *a, **k: None)
    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)


def _row(db: str, key: str, n: int) -> PolicyMeeting:
    with store.session_scope(db, commit=False) as s:
        m = s.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=n).one()
        s.expunge(m)
        return m


def test_a_first_summary_stamps_summarised_but_not_resummarised(monkeypatch, policy_db, tmp_path):
    db = policy_db
    _stub_notebooklm(monkeypatch, tmp_path)
    _meeting(db, "santeii", 5)
    pipeline.run(["santeii"], db_path=db)
    m = _row(db, "santeii", 5)
    assert m.state == "done" and m.summarised_at is not None and m.resummarised_at is None
    q = store.queue_snapshot(db_path=db)
    assert q["total"] == 0                                                # it left the queue…
    assert [(r["num"], r["kind"]) for r in q["recent"]] == [(5, "new")]    # …and is shown as drained


def test_an_update_stamps_both_and_is_shown_as_an_update(monkeypatch, policy_db, tmp_path):
    db = policy_db
    _stub_notebooklm(monkeypatch, tmp_path)
    _done(db, "santeii", 5, resummarise_requested=True)
    before = store.queue_snapshot(db_path=db)
    assert [i["kind"] for i in before["items"]] == ["update"]

    pipeline.run(["santeii"], db_path=db)

    m = _row(db, "santeii", 5)
    assert m.resummarise_requested is False
    assert m.summarised_at is not None and m.resummarised_at == m.summarised_at
    after = store.queue_snapshot(db_path=db)
    assert after["total"] == 0 and [(r["num"], r["kind"]) for r in after["recent"]] == [(5, "update")]


# ── The cap, the payload, the schema ─────────────────────────────────────────
def test_daily_run_cap_matches_the_workflow_default():
    """The "first N" line in the view is only honest while this equals what policy.yml runs."""
    text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "policy.yml").read_text(encoding="utf-8")
    inputs = re.search(r"max_per_run:.*?default:\s*\"(\d+)\"", text, re.S)
    step = re.search(r"MAX_PER_RUN:.*?\|\|\s*'(\d+)'", text)
    assert inputs and step
    assert int(inputs.group(1)) == int(step.group(1)) == store.DAILY_RUN_CAP


def test_status_payload_carries_the_queue(policy_db):
    db = policy_db
    _meeting(db, "santeii", 5)
    out = export_web.build_policy_status(db)
    assert out["queue"]["cap"] == store.DAILY_RUN_CAP
    assert out["queue"]["items"][0]["com"] == "santeii"
    assert set(out["queue"]) >= {"cap", "total", "totals", "byCom", "items", "truncated", "recent", "recentDays"}


def test_drain_stamp_columns_are_added_to_a_pulled_database(tmp_path):
    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE policy_meeting (id INTEGER PRIMARY KEY, committee_key VARCHAR(64) NOT NULL,"
                " meeting_num INTEGER NOT NULL, state VARCHAR(16) NOT NULL)")
    con.commit()
    con.close()
    store.sync_committees(db_path=db)
    cols = {r[1] for r in sqlite3.connect(db).execute("pragma table_info(policy_meeting)")}
    assert {"summarised_at", "resummarised_at"} <= cols
