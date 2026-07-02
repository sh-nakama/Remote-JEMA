"""Tests for the policy observer: pure parse functions, material selection,
detection (network mocked), running-document regeneration, and the no-Aurora gate.

Network-free: ``conditional_get`` and the discovery functions are monkeypatched;
a temporary SQLite path holds the policy tables; POLICY_DIR is redirected to tmp.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repower.policy import detect as detect_mod
from repower.policy import discover as discover_mod
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, store
from repower.policy.committees import COMMITTEES, committee_by_key
from repower.policy.scraper import (
    Discovery,
    Material,
    classify_material,
    extract_meeting_number,
    extract_pdf_id,
    material_id,
    meeting_num_from_url,
    parse_egc_index,
    parse_meti_meeting_urls,
    parse_pdf_links,
)

# ── Fixtures (small inline HTML) ─────────────────────────────────────────────
METI_INDEX = """
<html><body>
  <ul>
    <a href="003.html">第3回会合</a>
    <a href="002.html">第2回会合</a>
    <a href="001.html">第1回会合</a>
    <a href="../top/index.html">委員会トップ</a>
  </ul>
</body></html>
"""

METI_MEETING = """
<html><body>
  <a href="/data/079_01_00.pdf">資料1 再エネ大量導入（PDF形式：1,234KB）</a>
  <a href="079_gijiroku.pdf">議事録</a>
  <a href="079_gijiyoshi.pdf">議事要旨</a>
  <a href="079_torimatome.pdf">中間とりまとめ</a>
  <a href="notes.html">参考リンク</a>
</body></html>
"""

EGC_INDEX = """
<html><body>
<table>
  <tr><th>日付</th><th>回</th><th>資料</th></tr>
  <tr>
    <td>2025/03/01</td><td>第100回</td>
    <td>
      <a href="pdf/100_gijiyoshi.pdf">議事要旨</a>
      <a href="pdf/100_gijiroku.pdf">議事録</a>
      <a href="haifu_100.html">配布資料</a>
      <a href="https://youtu.be/x">動画</a>
    </td>
  </tr>
  <tr><td>過去</td><td>第1回～第5回</td><td>ログページ参照</td></tr>
</table>
</body></html>
"""


# ── Pure parse functions ─────────────────────────────────────────────────────
def test_parse_meti_meeting_urls():
    base = "https://www.meti.go.jp/shingikai/x/"
    urls = parse_meti_meeting_urls(METI_INDEX, base)
    assert set(urls) == {1, 2, 3}
    assert urls[3] == "https://www.meti.go.jp/shingikai/x/003.html"
    # The non-numbered nav link must be excluded.
    assert all(u.endswith(".html") and "/00" in u or "/003" in u for u in urls.values())


def test_parse_pdf_links_resolves_and_dedups():
    base = "https://www.meti.go.jp/shingikai/x/003.html"
    links = parse_pdf_links(METI_MEETING, base)
    urls = [link["url"] for link in links]
    assert "https://www.meti.go.jp/data/079_01_00.pdf" in urls
    assert "https://www.meti.go.jp/shingikai/x/079_gijiroku.pdf" in urls
    # The non-PDF link is ignored.
    assert all(u.lower().endswith(".pdf") for u in urls)


def test_parse_egc_index_skips_nav_rows():
    meetings = parse_egc_index(EGC_INDEX, "https://www.egc.meti.go.jp/activity/index_system.html")
    assert len(meetings) == 1
    m = meetings[0]
    assert m["meeting_num"] == 100
    assert m["haifu_url"].endswith("haifu_100.html")
    # 議事要旨 + 議事録 are direct PDFs; the video link is not.
    assert len(m["direct_pdfs"]) == 2


def test_classify_material():
    assert classify_material("議事録", "x/100_gijiroku.pdf") == "minutes"
    assert classify_material("議事要旨", "x/100_gijiyoshi.pdf") == "brief"
    assert classify_material("中間とりまとめ", "x/torimatome.pdf") == "compilation"
    assert classify_material("資料1 制度設計", "x/079_01.pdf") == "handout"
    assert classify_material("別紙2", "x/besshi02.pdf") == "appendix"
    assert classify_material("議事次第", "x/shidai.pdf") == "agenda"
    assert classify_material("その他", "x/random.pdf") == "other"


def test_extract_meeting_number():
    assert extract_meeting_number("079_01_00.pdf") == 79
    assert extract_meeting_number("youryou_kentoukai_71_gijiroku.pdf") == 71
    assert extract_meeting_number("no_number_here.pdf") is None


def test_extract_pdf_id():
    assert extract_pdf_id("079_01_00_shiryo.pdf") == "079_01_00"
    assert extract_pdf_id("chousei_jukyu_116_01.pdf") == "116_01"


def test_material_id_is_meeting_scoped_and_stable():
    a = material_id(79, "https://x/data/079_gijiroku.pdf")
    assert a.startswith("079_")
    # Deterministic
    assert a == material_id(79, "https://x/data/079_gijiroku.pdf")
    # Same file stem in a different meeting → different id
    assert material_id(80, "https://x/data/079_gijiroku.pdf") != a


def test_meeting_num_from_url():
    assert meeting_num_from_url("https://www.occto.or.jp/iinkai/chousei_jukyu/116.html") == 116
    assert meeting_num_from_url("https://x/index.html") is None


# ── Material selection ───────────────────────────────────────────────────────
def test_select_materials_prefers_minutes_and_caps(monkeypatch):
    monkeypatch.setattr(pipeline, "MEETING_SOURCE_BUDGET", 4)
    mats = [
        {"pdf_id": "001_min", "kind": "minutes", "url": "u", "title": ""},
        {"pdf_id": "001_brief", "kind": "brief", "url": "u", "title": ""},
        {"pdf_id": "001_h1", "kind": "handout", "url": "u", "title": ""},
        {"pdf_id": "001_h2", "kind": "handout", "url": "u", "title": ""},
        {"pdf_id": "001_h3", "kind": "handout", "url": "u", "title": ""},
        {"pdf_id": "001_app", "kind": "appendix", "url": "u", "title": ""},
    ]
    chosen = pipeline._select_materials(mats)
    kinds = [c["kind"] for c in chosen]
    assert kinds[0] == "minutes"  # minutes first
    assert "brief" not in kinds  # superseded by minutes
    assert "appendix" not in kinds  # dropped when over budget
    assert len(chosen) <= 4


# ── NotebookLM error classification ──────────────────────────────────────────
class _FakeProc:
    def __init__(self, returncode: int, stderr: str = "", stdout: str = ""):
        self.returncode, self.stderr, self.stdout = returncode, stderr, stdout


def test_run_classifies_rate_limit_vs_generic_error(monkeypatch):
    # A server-side rate limit surfaces as exit 1 with "RateLimitError" in stderr.
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeProc(1, "ERROR [notebooklm] RPC CREATE_ARTIFACT failed: RateLimitError"),
    )
    with pytest.raises(nb_mod.NotebookLMRateLimitError):
        nb_mod._run(["generate", "report"], timeout=5)

    # A different exit-1 failure must stay a plain NotebookLMError (not rate-limit),
    # so it still counts against the per-meeting retry budget.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(1, "boom: not found"))
    with pytest.raises(nb_mod.NotebookLMError) as ei:
        nb_mod._run(["create", "x"], timeout=5)
    assert not isinstance(ei.value, nb_mod.NotebookLMRateLimitError)


# ── Detection (network mocked) ───────────────────────────────────────────────
def test_detect_dry_run_reports_new_without_writing(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    key = "system_review"
    monkeypatch.setattr(detect_mod, "discover_meetings",
                        lambda c, **kw: Discovery("ok", [3, 2, 1]))
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [])

    results = detect_mod.detect([key], db_path=db, dry_run=True)

    assert results[0]["status"] == "ok"
    assert results[0]["new"] == 3
    # Dry run must not persist anything.
    assert store.known_meeting_nums(key, db_path=db) == set()


def test_detect_persists_meetings_and_materials(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    key = "chousei_jukyu"
    monkeypatch.setattr(detect_mod, "discover_meetings",
                        lambda c, **kw: Discovery("ok", [2, 1]))

    def fake_list(c, n, **kw):
        return [Material(n, f"{n:03d}_min", f"https://x/{n}_gijiroku.pdf", "議事録", "minutes")]

    monkeypatch.setattr(detect_mod, "list_materials", fake_list)

    results = detect_mod.detect([key], db_path=db)

    assert results[0]["new"] == 2
    assert store.known_meeting_nums(key, db_path=db) == {1, 2}
    mats = store.meeting_materials(key, 2, db_path=db)
    assert len(mats) == 1 and mats[0]["kind"] == "minutes"

    # Re-running detection is idempotent: nothing new.
    again = detect_mod.detect([key], db_path=db)
    assert again[0]["new"] == 0


def test_detect_unchanged_short_circuits(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    monkeypatch.setattr(detect_mod, "discover_meetings",
                        lambda c, **kw: Discovery("unchanged", []))
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [])
    results = detect_mod.detect(["santeii"], db_path=db)
    assert results[0]["status"] == "unchanged"
    assert results[0]["new"] == 0


# ── Running document regeneration ────────────────────────────────────────────
def test_regenerate_running_doc(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    policy_dir = tmp_path / "policy"
    monkeypatch.setattr(store, "POLICY_DIR", policy_dir)
    key = "system_review"

    store.sync_committees(db_path=db)
    store.record_meeting(
        key, 5,
        [Material(5, "005_min", "https://x/5_gijiroku.pdf", "議事録", "minutes")],
        db_path=db,
    )
    pend = store.pending_meetings(key, db_path=db)
    assert len(pend) == 1
    store.update_meeting(pend[0]["id"], db_path=db, state="done",
                         briefing_md="## 主要な論点\n価格規律について議論。")

    path = store.regenerate_running_doc(key, db_path=db)
    assert Path(path).exists()
    text = Path(path).read_text(encoding="utf-8")
    assert "第5回" in text
    assert "価格規律" in text
    # latest_meeting advances to the highest 'done' meeting.
    assert store.get_committee(key, db_path=db).latest_meeting == 5


def test_pending_retries_errors_under_cap(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.record_meeting("santeii", 5, None, db_path=db)
    mid = store.pending_meetings("santeii", db_path=db)[0]["id"]

    # Errored under the retry cap → still in the worklist.
    store.update_meeting(mid, db_path=db, state="error", retry_count=1)
    assert any(m["id"] == mid for m in store.pending_meetings("santeii", db_path=db))

    # Errored at the cap → dropped from the worklist.
    store.update_meeting(mid, db_path=db, state="error", retry_count=store.MAX_RETRIES)
    assert not any(m["id"] == mid for m in store.pending_meetings("santeii", db_path=db))

    # Done → always excluded.
    store.update_meeting(mid, db_path=db, state="done", retry_count=0)
    assert not any(m["id"] == mid for m in store.pending_meetings("santeii", db_path=db))


# ── Synthesis selection (flag-based, backfill-safe) ──────────────────────────
def test_meetings_for_synthesis_uses_flag_not_watermark(tmp_path):
    db = str(tmp_path / "t.db")
    key = "emissions_trading"
    store.sync_committees(db_path=db)
    # Two done meetings recorded newest-first (5 then 3), each with a briefing.
    for n in (5, 3):
        store.record_meeting(key, n, None, db_path=db)
        mid = next(m["id"] for m in store.pending_meetings(key, db_path=db) if m["meeting_num"] == n)
        store.update_meeting(mid, db_path=db, state="done", briefing_md=f"briefing {n}")

    # Both unsynthesised → returned oldest-first.
    assert [m["meeting_num"] for m in store.meetings_for_synthesis(key, db_path=db)] == [3, 5]

    # Synthesise the NEWER meeting first (the pilot/forward case)…
    store.mark_synthesized(key, 5, db_path=db)
    # …the older (backfilled) meeting must STILL be selected — the watermark bug.
    assert [m["meeting_num"] for m in store.meetings_for_synthesis(key, db_path=db)] == [3]

    store.mark_synthesized(key, 3, db_path=db)
    assert store.meetings_for_synthesis(key, db_path=db) == []


# ── Web committee discovery (network injected) ───────────────────────────────
METI_ROOT_INDEX = """
<html><body>
  <a href="system_review/">制度検討作業部会</a>
  <a href="saisei_kano/index.html">再生可能エネルギー大量導入・次世代電力ネットワーク小委員会</a>
  <a href="ccus_jigyo/">CCS事業実施ワーキンググループ</a>
  <a href="../top/">トップページ</a>
  <a href="https://example.com/other/">外部の委員会</a>
  <a href="report.pdf">議事録（PDF）</a>
  <a href="news.html">お知らせ</a>
</body></html>
"""

OCCTO_ROOT_INDEX = """
<html><body>
  <a href="youryou_kentoukai/">容量市場の在り方等に関する検討会</a>
  <a href="chousei_jukyu/">調整力及び需給バランス評価等に関する委員会</a>
</body></html>
"""


def test_parse_committee_links_filters_nav_and_cross_host():
    root = "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/"
    cands = discover_mod.parse_committee_links(METI_ROOT_INDEX, root)
    keys = {c.key for c in cands}
    # Three real committees; nav ("トップページ"/"お知らせ"), the PDF, and the
    # cross-host link are all excluded.
    assert keys == {"system_review", "saisei_kano", "ccus_jigyo"}
    sr = next(c for c in cands if c.key == "system_review")
    assert sr.source == "METI" and sr.name_ja == "制度検討作業部会"
    assert sr.url == "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/system_review/"


def test_discover_committees_query_and_tracked_flag():
    root = "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/"

    def fake_fetch(u):
        return ("ok", METI_ROOT_INDEX.encode("utf-8"))

    # Japanese-name query.
    cands = discover_mod.discover_committees(
        "CCS", roots=(root,), fetch=fake_fetch, tracked_urls=set(), tracked_keys=set())
    assert [c.key for c in cands] == ["ccus_jigyo"]

    # already_tracked is flagged when the key is in the registry.
    cands = discover_mod.discover_committees(
        "", roots=(root,), fetch=fake_fetch,
        tracked_urls=set(), tracked_keys={"system_review"})
    tracked = {c.key: c.already_tracked for c in cands}
    assert tracked["system_review"] is True and tracked["ccus_jigyo"] is False


def test_discover_english_query_bridges_to_japanese():
    root = "https://www.occto.or.jp/iinkai/"

    def fake_fetch(u):
        return ("ok", OCCTO_ROOT_INDEX.encode("utf-8"))

    # "capacity" (EN) should match 容量市場… via the EN→JA hint bridge.
    cands = discover_mod.discover_committees(
        "capacity", roots=(root,), fetch=fake_fetch, tracked_urls=set(), tracked_keys=set())
    assert [c.key for c in cands] == ["youryou_kentoukai"]
    assert cands[0].source == "OCCTO"


def test_probe_url_guesses_source_key_name(monkeypatch):
    html = "<html><head><title>同時市場の在り方等に関する検討会（METI/経済産業省）</title></head></html>"
    cand = discover_mod.probe_url(
        "https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/",
        fetch=lambda u: ("ok", html.encode("utf-8")),
        validate=False, tracked_urls=set(), tracked_keys=set(),
    )
    assert cand is not None
    assert cand.source == "METI"
    assert cand.key == "doji_shijo_kento"
    assert cand.name_ja == "同時市場の在り方等に関する検討会"  # site suffix trimmed


def test_probe_url_validate_previews_meeting_count(monkeypatch):
    monkeypatch.setattr(discover_mod, "discover_meetings",
                        lambda c, **kw: Discovery("ok", [3, 2, 1]))
    cand = discover_mod.probe_url(
        "https://www.occto.or.jp/iinkai/new_wg/",
        fetch=lambda u: ("ok", "<html><title>新しい委員会</title></html>".encode("utf-8")),
        validate=True, tracked_urls=set(), tracked_keys=set(),
    )
    assert cand.source == "OCCTO" and "3 meeting" in cand.note


def test_probe_url_rejects_non_http():
    assert discover_mod.probe_url("not a url", validate=False,
                                  tracked_urls=set(), tracked_keys=set()) is None


# ── No-Aurora gate ───────────────────────────────────────────────────────────
def test_no_aurora_anywhere_in_package():
    root = Path(__file__).resolve().parents[1] / "src" / "repower"
    offenders = []
    for p in root.rglob("*.py"):
        if "aurora" in p.read_text(encoding="utf-8", errors="ignore").lower():
            offenders.append(str(p))
    assert not offenders, f"'aurora' found in: {offenders}"


def test_all_committees_have_unique_keys_and_valid_source():
    keys = [c.key for c in COMMITTEES]
    assert len(keys) == len(set(keys)) == 14
    assert all(c.source in {"METI", "OCCTO", "EGC"} for c in COMMITTEES)
    assert committee_by_key("chousei_jukyu").is_occto
    # The two recently-added METI committees are tracked.
    assert committee_by_key("doji_shijo").is_meti
    assert committee_by_key("saiene_shuryoku").is_meti


def test_pending_meetings_ordered_by_priority_then_newest(tmp_path):
    """A quota-bounded run should drain high-priority committees first, newest-first."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    # santeii is a default-priority committee; system_review is priority 1.
    store.record_meeting("santeii", 5, None, db_path=db)
    store.record_meeting("system_review", 108, None, db_path=db)
    store.record_meeting("system_review", 114, None, db_path=db)

    order = [(m["committee_key"], m["meeting_num"]) for m in store.pending_meetings(db_path=db)]
    assert order == [("system_review", 114), ("system_review", 108), ("santeii", 5)]


# ── DB-backed registry: enable/disable, add, resolve, request queue ──────────
def test_sync_seeds_priority_and_enabled(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    rows = {c["committee_key"]: c for c in store.list_committees(db_path=db)}
    # Code priority is seeded into the DB and everything starts enabled.
    assert rows["system_review"]["priority"] == 1
    assert rows["emissions_trading"]["priority"] == 2
    assert all(c["enabled"] for c in rows.values())
    assert not any(c["user_added"] for c in rows.values())


def test_sync_preserves_ui_edits(tmp_path):
    """A committee disabled / re-prioritised in the UI stays that way across syncs."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.set_committee_enabled("santeii", False, db_path=db)
    store.set_committee_priority("santeii", 7, db_path=db)

    store.sync_committees(db_path=db)  # a later detection run re-syncs
    row = next(c for c in store.list_committees(db_path=db) if c["committee_key"] == "santeii")
    assert row["enabled"] is False
    assert row["priority"] == 7


def test_disabled_committee_excluded_from_detection(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.set_committee_enabled("santeii", False, db_path=db)

    tracked_keys = {c.key for c in store.tracked_committees(db_path=db)}
    assert "santeii" not in tracked_keys
    assert "system_review" in tracked_keys

    # detect() over the whole (enabled) registry must skip the disabled committee.
    seen: list[str] = []
    monkeypatch.setattr(detect_mod, "discover_meetings",
                        lambda c, **kw: seen.append(c.key) or Discovery("unchanged", []))
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [])
    detect_mod.detect(db_path=db)
    assert "santeii" not in seen and "system_review" in seen


def test_add_user_committee_tracked_and_resolved(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    created = store.add_committee(
        key="new_ccus", name_ja="CCS事業実施小委員会", name_en="CCS Business Subcommittee",
        url="https://www.meti.go.jp/shingikai/enecho/shigen_nenryo/ccs_jigyo/",
        source="METI", priority=5, db_path=db,
    )
    assert created is True

    c = store.resolve_committee("new_ccus", db_path=db)
    assert c.is_meti and c.name_ja == "CCS事業実施小委員会" and c.priority == 5
    tracked = {t.key for t in store.tracked_committees(db_path=db)}
    assert "new_ccus" in tracked
    # It is flagged user_added and can be deleted (unlike code committees).
    assert store.delete_committee("new_ccus", db_path=db) is True
    assert store.delete_committee("santeii", db_path=db) is False  # code committee → refused


def test_resolve_committee_roundtrips_occto_and_egc_params(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    # OCCTO params (max_meeting/prefix) survive the DB round-trip.
    occto = store.resolve_committee("chousei_jukyu", db_path=db)
    assert occto.is_occto and occto.max_meeting == 150 and occto.prefix == "chousei_jukyu"
    # EGC log_pages (JSON list) round-trip to a tuple.
    egc = store.resolve_committee("emsc_system", db_path=db)
    assert egc.is_egc and egc.min_meeting == 30
    assert egc.log_pages and egc.log_pages[0] == "index_systemlog9.html"


def test_generation_request_orders_first(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    # santeii is default priority; system_review is priority 1.
    store.record_meeting("santeii", 5, None, db_path=db)
    store.record_meeting("system_review", 114, None, db_path=db)

    # Without a request, priority wins.
    order = [m["committee_key"] for m in store.pending_meetings(db_path=db)]
    assert order[0] == "system_review"

    # A queued request on the lower-priority committee jumps the queue.
    assert store.request_generation("santeii", 5, db_path=db) is True
    top = store.pending_meetings(db_path=db)[0]
    assert (top["committee_key"], top["meeting_num"]) == ("santeii", 5)
    assert top["gen_requested"] is True

    store.clear_generation_request("santeii", 5, db_path=db)
    assert store.pending_meetings(db_path=db)[0]["committee_key"] == "system_review"
