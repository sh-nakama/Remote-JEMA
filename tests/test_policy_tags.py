"""Topic tags: the vocabulary and rules, who-may-overwrite-whom, the pipeline hook, the CLI
and the export. All hermetic — DB-only, NotebookLM faked at the lowest primitive."""

from __future__ import annotations

import datetime
import json
import sqlite3

import pytest
from typer.testing import CliRunner

from repower import cli
from repower.dashboard.export_web import build_policy_catalog, build_policy_snapshot, export_policy
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, store, tagging
from repower.policy import tags as tg
from repower.policy.committees import COMMITTEES, committee_by_key
from repower.policy.scraper import Material

# ── Vocabulary & rules ───────────────────────────────────────────────────────


def test_curated_committee_tags_are_all_in_the_vocabulary():
    for c in COMMITTEES:
        for key in c.tags or ():
            assert tg.valid(key), f"{c.key}: unknown tag {key}"


def test_the_first_pass_vocabulary_covers_the_agreed_topics():
    keys = set(tg.TAG_KEYS)
    # grid-scale solar, grid storage, offshore wind and grid infrastructure were the brief.
    assert {"solar_utility", "storage_grid", "wind_offshore", "grid_planning", "grid_connection"} <= keys
    assert {"support_fit_fip", "support_ltda", "hydrogen_ammonia", "nuclear"} <= keys


def test_vocabulary_export_matches_the_definitions():
    vocab = tg.vocabulary()
    assert [t["key"] for t in vocab["tags"]] == list(tg.TAG_KEYS)
    assert {t["group"] for t in vocab["tags"]} <= {g["key"] for g in vocab["groups"]}


@pytest.mark.parametrize(("name", "expected"), [
    ("洋上風力促進ワーキンググループ", ["wind_offshore"]),
    ("調達価格等算定委員会", ["support_fit_fip"]),
    ("系統用蓄電池の在り方に関する検討会", ["storage_grid"]),
    ("同時市場の在り方等に関する検討会", []),
    (None, []),
])
def test_committee_name_rules(name, expected):
    assert tg.tags_from_name(name) == expected


def test_a_title_hit_is_enough_for_a_meeting():
    got = tg.tags_for_meeting(titles=["資料3 洋上風力発電の促進区域の指定について"])
    assert got == ["wind_offshore"]


def test_a_passing_mention_in_the_briefing_is_not_a_topic():
    body = "太陽光に触れた。" * 2 + "送配電網の維持。一般送配電事業者。"
    assert tg.tags_for_meeting(titles=["資料1 容量市場の見直し"], body=body) == []
    # …but a briefing that keeps coming back to it is.
    assert tg.tags_for_meeting(titles=["資料1 容量市場の見直し"], body="系統用蓄電池 " * 3) == ["storage_grid"]


def test_generic_wind_defers_to_offshore():
    both = tg.tags_for_meeting(titles=["資料1 洋上風力の促進区域", "資料2 風力発電の導入動向"])
    assert both == ["wind_offshore"]
    # With no offshore signal the generic word is onshore wind.
    assert tg.tags_for_meeting(titles=["資料2 風力発電の導入動向"]) == ["wind_onshore"]


def test_generic_solar_defers_to_rooftop_and_nextgen():
    assert tg.tags_for_meeting(titles=["太陽光発電の導入拡大"]) == ["solar_utility"]
    assert tg.tags_for_meeting(titles=["住宅用太陽光の導入拡大"]) == ["solar_rooftop"]
    assert tg.tags_for_meeting(titles=["ペロブスカイト太陽電池の導入"]) == ["solar_nextgen"]


def test_distribution_does_not_match_transmission_and_distribution():
    """送配電 is in nearly every grid document; only 配電 on its own words count."""
    assert tg.tags_for_meeting(titles=["送配電網の維持・運用", "一般送配電事業者の役割"]) == []
    assert tg.tags_for_meeting(titles=["配電事業ライセンスの運用"]) == ["grid_distribution"]


def test_ascii_keywords_respect_word_boundaries():
    assert tg.count_hits("ADR と DRAM", ["DR"]) == 0
    assert tg.count_hits("DRの活用とVPP", ["DR", "VPP"]) == 2
    assert tg.count_hits("fit制度", ["FIT"]) == 1  # case-insensitive


def test_a_meeting_carries_at_most_the_cap_best_first():
    topics = ("洋上風力", "系統用蓄電池", "ノンファーム", "出力制御", "託送料金", "水素", "原子力")
    titles = [f"{kw} の検討" for kw in topics]
    got = tg.tags_for_meeting(titles=titles)
    assert len(got) == tg.MAX_MEETING_TAGS
    assert got == [k for k in tg.TAG_KEYS if k in got]  # vocabulary order


D = datetime.date


def test_coverage_is_graded_by_how_much_of_the_committee_a_topic_is():
    rows = [(D(2026, 9, i), ["wind_offshore"], True) for i in range(1, 9)]       # 8 of 10
    rows += [(D(2026, 9, 10 + i), ["grid_cost"], True) for i in range(2)]        # 2 of 10
    cov = tg.coverage(rows)

    assert cov["wind_offshore"].score > cov["grid_cost"].score > 0
    assert (cov["wind_offshore"].n, cov["wind_offshore"].of) == (8, 10)
    assert cov["wind_offshore"].last == D(2026, 9, 8)
    assert "nuclear" not in cov


def test_coverage_shrinks_thin_evidence():
    """One tagged meeting out of one is a hint, not '100% of the committee'."""
    one = tg.coverage([(D(2026, 9, 1), ["wind_offshore"], True)])["wind_offshore"].score
    many = tg.coverage([(D(2026, 9, i), ["wind_offshore"], True) for i in range(1, 21)])["wind_offshore"].score
    assert one < 0.4 < 0.85 < many < 1


def test_coverage_skips_meetings_with_no_evidence():
    rows = [(D(2026, 9, 1), ["wind_offshore"], True), (D(2026, 9, 2), ["wind_offshore"], True)]
    backlog = [(D(2026, 9, 3), [], False)] * 50   # detected, nothing downloaded or summarised
    assert tg.coverage(rows + backlog) == tg.coverage(rows)
    assert tg.coverage(backlog) == {}


def test_coverage_favours_recent_meetings():
    old = [(D(2022, 1, 1) + datetime.timedelta(days=30 * i), ["biomass"], True) for i in range(5)]
    new = [(D(2026, 1, 1) + datetime.timedelta(days=30 * i), ["wind_offshore"], True) for i in range(5)]
    cov = tg.coverage(old + new)
    assert cov["wind_offshore"].score > 3 * cov["biomass"].score


def test_coverage_ages_from_the_committees_own_newest_meeting():
    """A concluded committee keeps its topics; only meetings *within* it fade."""
    rows = [(D(2019, 1, 1) + datetime.timedelta(days=30 * i), ["wind_offshore"], True) for i in range(6)]
    assert tg.coverage(rows)["wind_offshore"].score == pytest.approx(
        tg.coverage([(d + datetime.timedelta(days=2500), t, ok) for d, t, ok in rows])["wind_offshore"].score)
    assert tg.coverage(rows)["wind_offshore"].score > 0.5


def test_undated_meetings_count_in_full():
    assert tg.coverage([(None, ["nuclear"], True), (None, [], True)])["nuclear"].score == pytest.approx(1 / 4)


def test_standing_tags_need_recurrence_not_a_one_off():
    meetings = [(D(2026, 9, i), t, True) for i, t in enumerate(
        [["wind_offshore"], ["wind_offshore", "grid_cost"], [], [], []], start=1)]
    assert tg.tags_from_coverage(tg.coverage(meetings)) == ["wind_offshore"]   # 2 of 5; grid_cost only once
    assert tg.tags_from_coverage(tg.coverage([(D(2026, 9, 1), ["grid_cost"], True)])) == []
    assert tg.tags_from_coverage({}) == []


@pytest.mark.parametrize(("answer", "expected"), [
    ('{"tags": ["wind_offshore", "grid_cost"]}', ["wind_offshore", "grid_cost"]),
    ('```json\n{"tags": ["wind_offshore"]}\n```', ["wind_offshore"]),
    ('Sure! {"tags": ["storage_grid"]} Hope that helps.', ["storage_grid"]),
    ('["nuclear"]', ["nuclear"]),
    ('{"tags": ["wind_offshore", "made_up"]}', ["wind_offshore"]),   # unknown keys dropped
    ('{"tags": []}', []),                                           # a valid "none apply"
    ("I could not tell.", None),                                    # unusable ≠ empty
    ('{"tags": "wind_offshore"}', None),
    ("", None),
    (None, None),
])
def test_parse_classification(answer, expected):
    assert tg.parse_classification(answer) == expected


def test_classification_question_is_a_closed_vocabulary():
    q = tg.classification_question()
    for t in tg.TAGS:
        assert t.key in q


# ── Persistence & precedence ─────────────────────────────────────────────────


def _meeting(db, key, num, *titles, body=None):
    store.record_meeting(
        key, num,
        [Material(num, f"{num:03d}_{t}", f"https://x/{num}_{t}.pdf", t, "handout") for t in titles],
        db_path=db,
    )
    if body is not None:
        row = next(m for m in store.pending_meetings(key, db_path=db) if m["meeting_num"] == num)
        store.update_meeting(row["id"], db_path=db, state="done", briefing_md=body)


def _tags(db, key, num=None):
    from repower.db import PolicyCommittee, PolicyMeeting, get_session, init_db

    init_db(db)
    s = get_session(db)
    try:
        row = (s.get(PolicyCommittee, key) if num is None else
               s.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=num).one())
        return tg.decode(row.tags), row.tags_source
    finally:
        s.close()


def test_retag_dry_run_reports_and_writes_nothing(policy_db):
    _meeting(policy_db, "doji_shijo", 1, "資料1 洋上風力発電について")

    res = tagging.retag(policy_db, apply=False)

    assert [(c["key"], c["num"], c["new"]) for c in res["meetings"]] == [("doji_shijo", 1, ["wind_offshore"])]
    assert _tags(policy_db, "doji_shijo", 1) == (None, None)


def test_retag_applies_idempotently(policy_db):
    _meeting(policy_db, "doji_shijo", 1, "資料1 洋上風力発電について")

    first = tagging.retag(policy_db)
    second = tagging.retag(policy_db)

    assert _tags(policy_db, "doji_shijo", 1) == (["wind_offshore"], "rule")
    assert len(first["meetings"]) == 1 and second["meetings"] == [] and second["committees"] == []


def test_rule_tags_follow_new_material_and_the_briefing(policy_db):
    """Titles grow as documents land and the briefing arrives later: rule tags track both."""
    _meeting(policy_db, "doji_shijo", 1, "資料1 議事次第")
    tagging.retag(policy_db)
    assert _tags(policy_db, "doji_shijo", 1) == ([], "rule")

    _meeting(policy_db, "doji_shijo", 1, "資料2 系統用蓄電池の接続について")  # a late document
    tagging.retag(policy_db)
    assert _tags(policy_db, "doji_shijo", 1)[0] == ["storage_grid"]

    _meeting(policy_db, "doji_shijo", 2, "資料1 議事次第", body="ノンファーム 型接続 " * 3)
    tagging.retag(policy_db)
    assert _tags(policy_db, "doji_shijo", 2)[0] == ["grid_connection"]


def test_pending_meetings_without_evidence_do_not_dilute_the_committee_rollup(policy_db):
    for n in (1, 2):
        _meeting(policy_db, "doji_shijo", n, "資料1 洋上風力について")
    for n in range(3, 10):
        _meeting(policy_db, "doji_shijo", n)  # detected, no materials yet: no evidence
    tagging.retag(policy_db)

    assert _tags(policy_db, "doji_shijo")[0] == ["wind_offshore"]


def test_llm_and_manual_tags_outrank_the_rules(policy_db):
    _meeting(policy_db, "doji_shijo", 1, "資料1 洋上風力について")
    _meeting(policy_db, "doji_shijo", 2, "資料1 洋上風力について")
    tagging.retag(policy_db)

    assert tagging.set_meeting_llm_tags("doji_shijo", 1, ["nuclear"], db_path=policy_db)
    assert tagging.set_manual_tags("doji_shijo", ["grid_cost"], meeting_num=2, db_path=policy_db)
    tagging.retag(policy_db)

    assert _tags(policy_db, "doji_shijo", 1) == (["nuclear"], "llm")
    assert _tags(policy_db, "doji_shijo", 2) == (["grid_cost"], "manual")
    # An LLM answer cannot override a person's pin either.
    assert tagging.set_meeting_llm_tags("doji_shijo", 2, ["nuclear"], db_path=policy_db) is False
    assert _tags(policy_db, "doji_shijo", 2) == (["grid_cost"], "manual")


def test_a_manual_empty_pin_is_kept_and_distinct_from_untagged(policy_db):
    _meeting(policy_db, "doji_shijo", 1, "資料1 洋上風力について")
    tagging.set_manual_tags("doji_shijo", [], meeting_num=1, db_path=policy_db)
    tagging.retag(policy_db)

    assert _tags(policy_db, "doji_shijo", 1) == ([], "manual")


def test_clearing_a_pin_hands_the_row_back_to_the_rules(policy_db):
    _meeting(policy_db, "doji_shijo", 1, "資料1 洋上風力について")
    tagging.set_manual_tags("doji_shijo", ["nuclear"], meeting_num=1, db_path=policy_db)

    assert tagging.clear_manual_tags("doji_shijo", meeting_num=1, db_path=policy_db)
    tagging.retag(policy_db)

    assert _tags(policy_db, "doji_shijo", 1) == (["wind_offshore"], "rule")


def test_manual_tags_reject_unknown_keys_and_unknown_rows(policy_db):
    with pytest.raises(ValueError, match="made_up"):
        tagging.set_manual_tags("doji_shijo", ["made_up"], db_path=policy_db)
    assert tagging.set_manual_tags("no_such", ["nuclear"], db_path=policy_db) is False
    assert tagging.set_manual_tags("doji_shijo", ["nuclear"], meeting_num=99, db_path=policy_db) is False


def test_curated_committee_tags_apply_and_a_person_still_wins(policy_db):
    tagging.retag(policy_db)
    tags, source = _tags(policy_db, "yojo_fuuryoku")
    assert (tags, source) == (["wind_offshore"], "config")

    tagging.set_manual_tags("yojo_fuuryoku", ["wind_offshore", "grid_planning"], db_path=policy_db)
    tagging.retag(policy_db)
    assert _tags(policy_db, "yojo_fuuryoku") == (["wind_offshore", "grid_planning"], "manual")


def test_an_uncurated_committee_is_tagged_from_its_name_and_its_meetings(policy_db):
    store.upsert_discovered_committees(
        [{"key": "battery_wg", "name_ja": "系統用蓄電池ワーキンググループ", "source": "METI",
          "url": "https://www.meti.go.jp/shingikai/x/battery_wg/"},
         {"key": "misc", "name_ja": "その他の検討会", "source": "METI",
          "url": "https://www.meti.go.jp/shingikai/x/misc/"}],
        db_path=policy_db,
    )
    for n in (1, 2, 3):
        _meeting(policy_db, "misc", n, "資料1 託送料金の見直し")
    tagging.retag(policy_db)

    assert _tags(policy_db, "battery_wg") == (["storage_grid"], "rule")
    assert _tags(policy_db, "misc") == (["grid_cost"], "rule")


def test_committee_scope_limits_the_pass(policy_db):
    _meeting(policy_db, "doji_shijo", 1, "資料1 洋上風力について")
    _meeting(policy_db, "emissions_trading", 1, "資料1 洋上風力について")

    res = tagging.retag(policy_db, committee="doji_shijo")

    assert {c["key"] for c in res["meetings"]} == {"doji_shijo"}
    assert _tags(policy_db, "emissions_trading", 1) == (None, None)


def test_decode_drops_keys_that_left_the_vocabulary():
    assert tg.decode('["wind_offshore", "retired_tag"]') == ["wind_offshore"]
    assert tg.decode(None) is None and tg.decode("not json") is None and tg.decode('{"a": 1}') is None


def test_committee_coverage_reads_the_stored_tags(policy_db):
    for n in (1, 2, 3):
        _meeting(policy_db, "yojo_fuuryoku", n, "資料1 洋上風力の促進区域")
    _meeting(policy_db, "yojo_fuuryoku", 4, "資料1 託送料金")
    for n in range(5, 15):
        _meeting(policy_db, "yojo_fuuryoku", n)                 # no documents: no evidence
    tagging.retag(policy_db)

    cov = tagging.committee_coverage(policy_db)["yojo_fuuryoku"]

    assert (cov["wind_offshore"].n, cov["wind_offshore"].of) == (3, 4)
    assert cov["grid_cost"].n == 1 and cov["grid_cost"].score < cov["wind_offshore"].score
    assert tagging.committee_coverage(policy_db, committee="doji_shijo") == {}


# ── Migration ────────────────────────────────────────────────────────────────


def test_migration_adds_the_columns_to_a_pre_tags_database(tmp_path):
    """The production DB is pulled from Hugging Face: it must upgrade in place."""
    from repower.db import init_db

    db = str(tmp_path / "old.db")
    init_db(db)
    con = sqlite3.connect(db)
    for table in ("policy_committee", "policy_meeting"):
        con.execute(f"ALTER TABLE {table} DROP COLUMN tags")
        con.execute(f"ALTER TABLE {table} DROP COLUMN tags_source")
    con.commit()
    con.close()

    from repower import db as db_mod
    db_mod._INITIALIZED.discard(db)
    db_mod._ENGINES.pop(db, None)
    store.sync_committees(db_path=db)  # init_db → migrate

    con = sqlite3.connect(db)
    for table in ("policy_committee", "policy_meeting"):
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        assert {"tags", "tags_source"} <= cols
    con.close()


# ── Pipeline: the NotebookLM classification ──────────────────────────────────


def _fake_notebooklm(monkeypatch, tmp_path, *, tag_answer):
    """Fake only the NotebookLM primitives, so summarize_meeting runs its real success path."""
    def download(url, dest, **k):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        return "ok"

    monkeypatch.setattr(pipeline, "_download_pdf", download)
    monkeypatch.setattr(pipeline.nb, "create_notebook", lambda *a, **k: "nb1")
    monkeypatch.setattr(pipeline.nb, "add_source", lambda *a, **k: "src1")
    monkeypatch.setattr(pipeline.nb, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(pipeline, "_ocr_guard", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.nb, "generate_report", lambda *a, **k: "task1")
    monkeypatch.setattr(pipeline.nb, "wait_artifact", lambda *a, **k: True)
    def download_report(nid, tid, dest, **k):
        dest.write_text("洋上風力の議論。" * 80, encoding="utf-8")
        return True

    monkeypatch.setattr(pipeline.nb, "download_report", download_report)
    monkeypatch.setattr(pipeline.nb, "delete_notebook", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "regenerate_running_doc", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_scratch", lambda: tmp_path / "scratch")
    asked: list[str] = []

    def ask(nid, question, **k):
        asked.append(question)
        if question == pipeline._ENGLISH_DIGEST_Q:
            return {"answer": "Lead.\n\n### Key decisions\n* x"}
        if isinstance(tag_answer, Exception):
            raise tag_answer
        return {"answer": tag_answer}

    monkeypatch.setattr(pipeline.nb, "ask", ask)
    return asked


def _stage(db, key="doji_shijo", num=7):
    store.sync_committees(db_path=db)
    store.record_meeting(
        key, num, [Material(num, f"{num:03d}_min", f"https://x/{num}_gijiroku.pdf", "議事録", "minutes")],
        db_path=db)
    return committee_by_key(key)


def test_summarising_records_the_llm_classification(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    committee = _stage(db)
    asked = _fake_notebooklm(monkeypatch, tmp_path, tag_answer='{"tags": ["wind_offshore", "bogus"]}')

    assert pipeline.summarize_meeting(committee, 7, db_path=db) == "done"

    assert _tags(db, "doji_shijo", 7) == (["wind_offshore"], "llm")
    assert tg.classification_question() in asked


@pytest.mark.parametrize("answer", ["no idea", nb_mod.NotebookLMError("boom")], ids=["unusable", "error"])
def test_a_failed_classification_leaves_the_meeting_done_for_the_rules(monkeypatch, tmp_path, answer):
    db = str(tmp_path / "t.db")
    committee = _stage(db)
    _fake_notebooklm(monkeypatch, tmp_path, tag_answer=answer)

    assert pipeline.summarize_meeting(committee, 7, db_path=db) == "done"
    assert _tags(db, "doji_shijo", 7) == (None, None)

    tagging.retag(db)  # the daily rule pass derives them from the briefing instead
    assert _tags(db, "doji_shijo", 7) == (["wind_offshore"], "rule")


def test_an_llm_answer_does_not_overwrite_a_manual_pin(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    committee = _stage(db)
    tagging.set_manual_tags("doji_shijo", ["nuclear"], meeting_num=7, db_path=db)
    _fake_notebooklm(monkeypatch, tmp_path, tag_answer='{"tags": ["wind_offshore"]}')

    assert pipeline.summarize_meeting(committee, 7, db_path=db) == "done"
    assert _tags(db, "doji_shijo", 7) == (["nuclear"], "manual")


# ── Export ───────────────────────────────────────────────────────────────────


def test_snapshot_and_catalog_carry_tags_and_the_vocabulary(policy_db):
    _meeting(policy_db, "doji_shijo", 1, "資料1 系統用蓄電池について")
    tagging.retag(policy_db)

    snap = build_policy_snapshot(policy_db)

    assert snap["tagVocab"] == tg.vocabulary()
    com = {c["key"]: c for c in snap["committees"]}
    assert com["yojo_fuuryoku"]["tags"] == ["wind_offshore"]
    assert com["emissions_trading"]["tags"] == []  # never tagged → empty, not missing
    assert snap["meetings"][0]["tags"] == ["storage_grid"]
    # The live catalog (Manage modal) is built by the same payload function.
    assert {c["key"]: c["tags"] for c in build_policy_catalog(policy_db)}["yojo_fuuryoku"] == ["wind_offshore"]


def test_static_export_writes_the_vocabulary_beside_the_committees(policy_db, tmp_path):
    export_policy(tmp_path, policy_db)

    data = json.loads((tmp_path / "policy" / "committees.json").read_text(encoding="utf-8"))
    assert data["tagVocab"] == tg.vocabulary()
    assert all("tags" in c for c in data["committees"])


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli_db(monkeypatch, tmp_path):
    """Point the CLI's DB at a temp file (config reads REPOWER_DB_PATH at import, so patch the users)."""
    db = str(tmp_path / "cli.db")
    store.sync_committees(db_path=db)
    from repower.policy import store as store_mod
    real_scope = store_mod.session_scope
    monkeypatch.setattr(store_mod, "session_scope", lambda db_path=None, **k: real_scope(db_path or db, **k))
    monkeypatch.setattr(tagging, "session_scope", store_mod.session_scope)
    return db


def test_policy_tag_is_a_dry_run_unless_applied(monkeypatch, tmp_path):
    db = _cli_db(monkeypatch, tmp_path)
    _meeting(db, "doji_shijo", 1, "資料1 洋上風力について")

    dry = CliRunner().invoke(cli.app, ["policy", "tag"])
    assert dry.exit_code == 0, dry.output
    assert "Dry run" in dry.output and "wind_offshore" in dry.output
    assert _tags(db, "doji_shijo", 1) == (None, None)

    applied = CliRunner().invoke(cli.app, ["policy", "tag", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert _tags(db, "doji_shijo", 1) == (["wind_offshore"], "rule")


def test_policy_tag_set_pins_and_validates(monkeypatch, tmp_path):
    db = _cli_db(monkeypatch, tmp_path)
    _meeting(db, "doji_shijo", 1, "資料1 洋上風力について")
    run = lambda *a: CliRunner().invoke(cli.app, ["policy", "tag-set", *a])  # noqa: E731

    assert run("doji_shijo", "nuclear", "--meeting", "1").exit_code == 0
    assert _tags(db, "doji_shijo", 1) == (["nuclear"], "manual")

    bad = run("doji_shijo", "made_up")
    assert bad.exit_code == 2 and "made_up" in bad.output
    assert run("no_such", "nuclear").exit_code == 1
    assert run("doji_shijo").exit_code == 2                       # needs tags, --none or --auto
    assert run("doji_shijo", "nuclear", "--none").exit_code == 2

    assert run("doji_shijo", "--none", "--meeting", "1").exit_code == 0
    assert _tags(db, "doji_shijo", 1) == ([], "manual")

    assert run("doji_shijo", "--auto", "--meeting", "1").exit_code == 0
    assert _tags(db, "doji_shijo", 1) == (["wind_offshore"], "rule")


def test_policy_tags_lists_the_vocabulary():
    out = CliRunner().invoke(cli.app, ["policy", "tags"]).output
    for t in tg.TAGS:
        assert t.key in out
