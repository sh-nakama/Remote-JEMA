"""Tests for the policy observer: pure parse functions, material selection,
detection (network mocked), running-document regeneration, and the no-Aurora gate.

Network-free: ``conditional_get`` and the discovery functions are monkeypatched;
a temporary SQLite path holds the policy tables; POLICY_DIR is redirected to tmp.
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

import pytest

from repower.policy import detect as detect_mod
from repower.policy import discover as discover_mod
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, scraper, store
from repower.policy.committees import COMMITTEES, Committee, committee_by_key
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
from repower.scrapers.http_cache import ChallengeNotClearedError, min_host_interval

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


def test_parse_meti_meeting_urls_skips_non_committee_links():
    # A footer link like /main/31.html would otherwise register as phantom meeting
    # 31 and hijack the latest-meeting frontier. Joint meetings under a sibling
    # /shingikai/ committee dir must still be kept.
    html = """
    <html><body>
      <ul>
        <li><a href="/shingikai/enecho/x/nenryo/022.html">2026年7月17日 第22回</a></li>
        <li><a href="/shingikai/enecho/x/suiso/014.html">2024年6月7日 第15回</a></li>
      </ul>
      <footer><a href="/main/31.html">サイトポリシー</a></footer>
    </body></html>
    """
    base = "https://www.meti.go.jp/shingikai/enecho/x/nenryo/"
    urls = parse_meti_meeting_urls(html, base)
    assert set(urls) == {22, 14}
    assert 31 not in urls
    assert urls[14].endswith("/shingikai/enecho/x/suiso/014.html")


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


# Main-commission (index_emsc.html) shape: a leading archive-navigation table of
# 第N回～第M回 range links, then the recent-meetings table where some rows are
# 非公開開催 / 書面開催 with an empty materials column.
EGC_EMSC_INDEX = """
<html><body>
<h3>電力・ガス取引監視等委員会（第604回～）</h3>
<table>
  <tr>
    <td><a href="index_log10.html">第507回～第565回 (令和6年度)</a></td>
    <td><a href="index_log11.html">第566回～第603回 (令和7年度)</a></td>
  </tr>
</table>
<table>
  <tr>
    <td>令和8年7月22日</td><td>第613回</td><td></td><td></td><td></td><td>※非公開開催</td>
  </tr>
  <tr>
    <td>令和8年7月15日</td><td>第612回</td><td></td><td></td>
    <td><a href="emsc/612_haifu.html">配布資料</a></td>
    <td><a href="https://www.youtube.com/live/x">動画</a></td>
  </tr>
  <tr>
    <td>令和8年6月17日</td><td>第609回</td><td></td><td></td><td></td><td>※書面開催</td>
  </tr>
  <tr>
    <td>令和8年6月8日</td><td>第608回</td>
    <td><a href="emsc/pdf/608_giji.pdf">議事要旨</a></td>
    <td><a href="emsc/pdf/608_gijiroku.pdf">議事録</a></td>
    <td><a href="emsc/608_haifu.html">配布資料</a></td>
    <td><a href="https://www.youtube.com/live/y">動画</a></td>
  </tr>
</table>
</body></html>
"""


def test_parse_egc_index_picks_up_nonpublic_meetings():
    url = "https://www.egc.meti.go.jp/activity/index_emsc.html"
    meetings = parse_egc_index(EGC_EMSC_INDEX, url)
    by_num = {m["meeting_num"]: m for m in meetings}
    # Every genuine meeting is present — including the materials-less
    # 非公開開催 (613) and 書面開催 (609) rows that used to be dropped.
    assert set(by_num) == {613, 612, 609, 608}
    # The archive range links (第507回～第565回 …) are not mistaken for meetings.
    assert 507 not in by_num and 566 not in by_num
    # Non-public meetings are dated (from the row) but carry no materials.
    import datetime

    assert by_num[613]["date"] == datetime.date(2026, 7, 22)
    assert by_num[613]["direct_pdfs"] == [] and by_num[613]["haifu_url"] is None
    assert by_num[609]["date"] == datetime.date(2026, 6, 17)
    # A 配布資料-only meeting keeps its haifu subpage; a full meeting keeps its PDFs.
    assert by_num[612]["haifu_url"].endswith("emsc/612_haifu.html")
    assert len(by_num[608]["direct_pdfs"]) == 2


def test_parse_egc_index_commission_and_subsequence_number():
    # Verification pages (index_emscverification.html) number rows as
    # 第520回(第6回): the commission number followed by a series sub-sequence.
    # The canonical meeting number is the first (commission) number, 520.
    # A leading とりまとめ (compilation report) row has a date but no 第N回.
    html = """
    <html><body>
    <table>
      <tr>
        <td>令和6年6月26日</td>
        <td colspan="5"><a href="ev/report_20240626.html">検証に係るとりまとめ</a></td>
      </tr>
      <tr>
        <td>令和6年6月26日</td><td>第520回(第6回)</td>
        <td><a href="ev/pdf/520_giji.pdf">議事要旨</a></td>
        <td><a href="ev/520_haifu.html">配布資料</a></td>
      </tr>
    </table>
    </body></html>
    """
    url = "https://www.egc.meti.go.jp/activity/index_emscverification.html"
    by_num = {m["meeting_num"]: m for m in parse_egc_index(html, url)}
    # The first (commission) number wins; the sub-sequence 6 is not a meeting.
    assert set(by_num) == {520}
    import datetime

    assert by_num[520]["date"] == datetime.date(2024, 6, 26)
    assert by_num[520]["haifu_url"].endswith("ev/520_haifu.html")


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


# ── PDF download: WAF handling and retry accounting ──────────────────────────
def _meeting_row(key: str, num: int, db):
    """Read a meeting's persisted state/flag/retry_count straight from the DB —
    ``pending_meetings`` deliberately doesn't expose the latter two."""
    from repower.db import PolicyMeeting, get_session, init_db

    init_db(db)
    session = get_session(db)
    try:
        m = session.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=num).one()
        return {"id": m.id, "state": m.state, "quality_flag": m.quality_flag,
                "retry_count": m.retry_count or 0,
                "last_error": m.last_error, "last_error_at": m.last_error_at}
    finally:
        session.close()


def _stage_meeting(db, key="doji_shijo", num=7):
    """A committee + one meeting with a single material, ready to summarise."""
    store.sync_committees(db_path=db)
    store.record_meeting(
        key, num,
        [Material(num, f"{num:03d}_min", f"https://x/{num}_gijiroku.pdf", "議事録", "minutes")],
        db_path=db,
    )
    return committee_by_key(key)


def test_download_pdf_goes_through_http_cache_and_classifies_waf_block(monkeypatch, tmp_path):
    """A 202 challenge that the shared layer could not clear is reported as such,
    not swallowed into a bare False — the caller needs the kind to decide whether
    the meeting or the host is at fault."""
    def _blocked(url, **kwargs):
        assert kwargs["force"] is True  # no persistent body store → a 304 is useless
        assert kwargs["allow_curl_fallback"] is True
        raise ChallengeNotClearedError(url, 4)

    monkeypatch.setattr(pipeline, "conditional_get", _blocked)
    dest = tmp_path / "x.pdf"
    assert pipeline._download_pdf("https://www.meti.go.jp/a.pdf", dest) == "challenge_unresolved"
    assert not dest.exists()


def test_download_pdf_writes_body_and_reports_404(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "conditional_get", lambda url, **k: ("ok", b"%PDF-1.4 body"))
    dest = tmp_path / "ok.pdf"
    assert pipeline._download_pdf("https://x/a.pdf", dest) == "ok"
    assert dest.read_bytes() == b"%PDF-1.4 body"

    monkeypatch.setattr(pipeline, "conditional_get", lambda url, **k: ("not_found", None))
    gone = tmp_path / "gone.pdf"
    assert pipeline._download_pdf("https://x/b.pdf", gone) == "not_found"
    assert not gone.exists()


def test_blocked_download_does_not_burn_the_retry_budget(monkeypatch, tmp_path):
    """A hostile host must not push a perfectly good meeting towards abandonment:
    the same PDFs download fine on a calm day."""
    db = str(tmp_path / "t.db")
    committee = _stage_meeting(db)
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "circuit_open")

    # 'blocked', not 'error': nothing reached NotebookLM, so the run's quota
    # budget must not be charged for it.
    assert pipeline.summarize_meeting(committee, 7, db_path=db) == "blocked"
    row = _meeting_row("doji_shijo", 7, db)
    assert row["quality_flag"] == "download_blocked"
    assert row["retry_count"] == 0
    # Still queued, so a later run picks it up again.
    assert any(m["meeting_num"] == 7 for m in store.pending_meetings("doji_shijo", db_path=db))


def test_mixed_failures_count_as_blocked(monkeypatch, tmp_path):
    """One transient kind is enough to make "these documents are gone" wrong."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key, num = "doji_shijo", 8
    store.record_meeting(
        key, num,
        [Material(num, "008_min", "https://x/8_gijiroku.pdf", "議事録", "minutes"),
         Material(num, "008_h1", "https://x/8_01_00.pdf", "資料1", "handout")],
        db_path=db,
    )
    kinds = iter(["not_found", "challenge_unresolved"])
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: next(kinds))

    assert pipeline.summarize_meeting(committee_by_key(key), num, db_path=db) == "blocked"
    row = _meeting_row(key, num, db)
    assert row["quality_flag"] == "download_blocked"
    assert row["retry_count"] == 0


def test_missing_documents_burn_the_retry_budget_and_eventually_drop_out(monkeypatch, tmp_path):
    """Documents that are genuinely gone must leave the worklist rather than be
    re-attempted every run forever."""
    db = str(tmp_path / "t.db")
    committee = _stage_meeting(db)
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "not_found")

    for expected in range(1, store.MAX_RETRIES + 1):
        assert pipeline.summarize_meeting(committee, 7, db_path=db) == "error"
        row = _meeting_row("doji_shijo", 7, db)
        assert row["quality_flag"] == "download_failed"
        assert row["retry_count"] == expected

    assert not any(m["meeting_num"] == 7
                   for m in store.pending_meetings("doji_shijo", db_path=db))


def test_every_failure_path_records_why_and_success_clears_it(monkeypatch, tmp_path):
    """`state='error'` alone can't be acted on. Each failure path must leave a
    message naming the cause — including the generic NotebookLM one, which has no
    quality_flag at all — and a later success must clear it, so the status table
    never reports a resolved error against a summarised meeting."""
    db = str(tmp_path / "t.db")
    committee = _stage_meeting(db)

    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "not_found")
    assert pipeline.summarize_meeting(committee, 7, db_path=db) == "error"
    row = _meeting_row("doji_shijo", 7, db)
    assert "not_found" in row["last_error"] and row["last_error_at"]

    # The generic NotebookLM path: no slug fits, so the message is the only record.
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "ok")
    monkeypatch.setattr(pipeline.nb, "create_notebook",
                        lambda *a, **k: (_ for _ in ()).throw(nb_mod.NotebookLMError("quota exhausted")))
    assert pipeline.summarize_meeting(committee, 7, db_path=db) == "error"
    row = _meeting_row("doji_shijo", 7, db)
    assert row["quality_flag"] is None
    assert "quota exhausted" in row["last_error"]

    # A later success wipes it.
    store.update_meeting(row["id"], db_path=db, state="done", last_error=None, last_error_at=None)
    row = _meeting_row("doji_shijo", 7, db)
    assert row["last_error"] is None and row["last_error_at"] is None


def test_blocked_meetings_do_not_consume_the_quota_budget(monkeypatch, tmp_path):
    """``--max-per-run`` guards the NotebookLM quota, and a blocked meeting spends
    none — so a run keeps looking until it has bought its budget in real work."""
    db = str(tmp_path / "t.db")
    key = "doji_shijo"
    store.sync_committees(db_path=db)
    for num in range(1, 7):
        store.record_meeting(key, num, None, db_path=db)

    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)
    seen: list[int] = []

    def fake_summarize(committee, num, **kwargs):  # newest two are host-blocked
        seen.append(num)
        return "blocked" if num >= 5 else "done"

    monkeypatch.setattr(pipeline, "summarize_meeting", fake_summarize)

    summary = pipeline.run([key], max_per_run=2, db_path=db)
    assert summary["done"] == 2  # the budget still bought two real summaries
    assert summary["blocked"] == 2
    assert summary["processed"] == 4  # attempted, not the whole worklist
    assert seen == [6, 5, 4, 3]  # newest first, stopping once the budget is spent


def test_run_stops_when_everything_is_blocked(monkeypatch, tmp_path):
    """A host-wide outage must not walk the entire backlog looking for work."""
    db = str(tmp_path / "t.db")
    key = "doji_shijo"
    store.sync_committees(db_path=db)
    monkeypatch.setattr(pipeline, "_MAX_BLOCKED_ATTEMPTS", 3)
    for num in range(1, 21):
        store.record_meeting(key, num, None, db_path=db)

    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "summarize_meeting", lambda *a, **k: "blocked")

    summary = pipeline.run([key], max_per_run=5, db_path=db)
    assert summary["blocked"] == 3  # stopped at the bound, not after all 20
    assert summary["done"] == 0


@pytest.mark.parametrize("exc,reason", [
    (nb_mod.NotebookLMRateLimitError("quota"), "rate_limited"),
    (nb_mod.NotebookLMAuthError("session expired"), "auth_expired"),
    (nb_mod.NotebookLMTimeout("notebooklm timed out"), "timed_out"),
])
def test_run_stops_cleanly_when_the_account_or_session_gives_out(monkeypatch, tmp_path,
                                                                 exc, reason):
    """A spent quota, a lapsed cookie and an unresponsive NotebookLM are all
    properties of the account, not of the meeting — the next meeting would fail
    identically. The run ends with a partial summary rather than a traceback."""
    db = str(tmp_path / "t.db")
    key = "doji_shijo"
    store.sync_committees(db_path=db)
    for num in (1, 2, 3):
        store.record_meeting(key, num, None, db_path=db)

    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee",
                        lambda *a, **k: pytest.fail("synthesis must be skipped after a halt"))
    seen: list[int] = []

    def fake_summarize(committee, num, **kwargs):
        seen.append(num)
        if len(seen) == 2:
            raise exc
        return "done"

    monkeypatch.setattr(pipeline, "summarize_meeting", fake_summarize)

    summary = pipeline.run([key], db_path=db)
    assert summary["stopped_early"] == reason
    assert summary["rate_limited"] is (reason == "rate_limited")
    assert summary["done"] == 1  # the meeting that finished before the halt is kept
    assert seen == [3, 2]  # stopped instead of walking on to 第1回


def test_run_stops_when_synthesis_hits_a_create_timeout(monkeypatch, tmp_path):
    """The crash this guards against: a synthesis rollover's ``create_notebook``
    timing out on a lapsing session used to kill the whole process."""
    db = str(tmp_path / "t.db")
    key = "doji_shijo"
    store.sync_committees(db_path=db)
    store.record_meeting(key, 1, None, db_path=db)

    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "summarize_meeting", lambda *a, **k: "done")

    def fake_synthesize(committee, **kwargs):
        raise nb_mod.NotebookLMTimeout("notebooklm timed out")

    monkeypatch.setattr(pipeline, "synthesize_committee", fake_synthesize)

    summary = pipeline.run([key], db_path=db)
    assert summary["stopped_early"] == "timed_out"
    assert summary["done"] == 1
    assert summary["synthesized"] == 0


def test_summarize_meeting_defers_a_timeout_without_burning_a_retry(monkeypatch, tmp_path):
    """A timeout is the session's fault, not the meeting's: the row goes back to
    'detected' with its retry budget intact, and the notebook isn't leaked."""
    db = str(tmp_path / "t.db")
    key = "doji_shijo"
    store.sync_committees(db_path=db)
    store.record_meeting(key, 3, [Material(
        meeting_num=3, pdf_id="p1", url="https://example.jp/a.pdf", title="議事録",
        kind="minutes",
    )], db_path=db)
    mid = store.pending_meetings(key, db_path=db)[0]["id"]

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    def fake_download(url, dest, **kwargs):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"pdf")
        return "ok"

    monkeypatch.setattr(pipeline, "_download_pdf", fake_download)
    monkeypatch.setattr(nb_mod, "create_notebook", lambda *a, **k: "nb-1")
    monkeypatch.setattr(nb_mod, "add_source", lambda *a, **k: "src-1")
    monkeypatch.setattr(nb_mod, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nb_mod, "source_fulltext", lambda *a, **k: {"char_count": 5000})
    monkeypatch.setattr(nb_mod, "generate_report",
                        lambda *a, **k: (_ for _ in ()).throw(nb_mod.NotebookLMTimeout("timed out")))
    deleted: list[str] = []
    monkeypatch.setattr(nb_mod, "delete_notebook", lambda nb_id, **k: deleted.append(nb_id))

    with pytest.raises(nb_mod.NotebookLMTimeout):
        pipeline.summarize_meeting(committee_by_key(key), 3, db_path=db)

    row = next(m for m in store.pending_meetings(key, db_path=db) if m["id"] == mid)
    assert row["state"] == "detected"  # back on the worklist, unblemished
    assert pipeline._bump_retry(key, 3, db) == 1  # i.e. the stored count is still 0
    assert deleted == ["nb-1"]  # the half-built notebook is not left behind


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


def test_run_classifies_a_lapsed_session_as_an_auth_error(monkeypatch):
    """``require_auth`` only gates the start of a run; a cookie that lapses an hour
    in shows up as an ordinary exit-1 failure and must not be mistaken for one."""
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeProc(1, "Token fetch failed: Authentication expired or invalid"),
    )
    with pytest.raises(nb_mod.NotebookLMAuthError):
        nb_mod._run(["create", "x"], timeout=5)


def test_create_notebook_adopts_the_notebook_a_timed_out_create_left_behind(monkeypatch):
    """The RPC can land server-side while the client gives up waiting. Adopting
    the notebook by title keeps it tracked instead of leaking it against the
    shared account's quota."""
    monkeypatch.setattr(nb_mod, "_json",
                        lambda *a, **k: (_ for _ in ()).throw(nb_mod.NotebookLMTimeout("timed out")))
    monkeypatch.setattr(nb_mod, "list_notebooks", lambda **k: [
        {"id": "nb-old", "title": "other", "created_at": "2026-08-01"},
        {"id": "nb-orphan", "title": "x synthesis (第7回〜)", "created_at": "2026-08-16"},
    ])
    monkeypatch.setattr(nb_mod, "list_sources", lambda *a, **k: [])
    assert nb_mod.create_notebook("x synthesis (第7回〜)") == "nb-orphan"

    # A same-titled notebook that already holds sources belongs to an earlier
    # attempt (its own delete may have timed out) — reusing it would duplicate
    # them, so the timeout stands and the caller stops the run.
    monkeypatch.setattr(nb_mod, "list_sources", lambda *a, **k: [{"id": "src-1"}])
    with pytest.raises(nb_mod.NotebookLMTimeout):
        nb_mod.create_notebook("x synthesis (第7回〜)")

    # The lookup itself failing (the dead session that caused the timeout) is not
    # a licence to guess.
    monkeypatch.setattr(nb_mod, "list_notebooks",
                        lambda **k: (_ for _ in ()).throw(nb_mod.NotebookLMAuthError("expired")))
    with pytest.raises(nb_mod.NotebookLMTimeout):
        nb_mod.create_notebook("x synthesis (第7回〜)")


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


# ── Material backfill (self-heal meetings detected during a source outage) ────
def test_meetings_missing_materials_lists_hidden_meetings(tmp_path):
    """meetings_missing_materials returns detected meetings with no materials
    (newest first), excluding done meetings and meetings that already have docs."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"
    store.record_meeting(key, 1, None, db_path=db)  # material-less
    store.record_meeting(key, 2, None, db_path=db)  # material-less
    store.record_meeting(  # already has a material → not hidden
        key, 3,
        [Material(3, "003_min", "https://x/3_gijiroku.pdf", "議事録", "minutes")],
        db_path=db,
    )
    store.record_meeting(key, 4, None, db_path=db)  # will be marked done
    mid4 = next(m["id"] for m in store.pending_meetings(key, db_path=db)
                if m["meeting_num"] == 4)
    store.update_meeting(mid4, db_path=db, state="done", briefing_md="x")

    assert store.meetings_missing_materials(key, db_path=db) == [2, 1]


def test_backfill_materials_populates_detected_meetings(monkeypatch, tmp_path):
    """backfill_materials fetches materials for material-less detected meetings so
    they stop being hidden — the 'tracked committee shows no meetings' fix."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"
    store.record_meeting(key, 1, None, db_path=db)
    store.record_meeting(key, 2, None, db_path=db)
    assert store.meetings_missing_materials(key, db_path=db) == [2, 1]

    def fake_list(c, n, **kw):
        return [Material(n, f"{n:03d}_01", f"https://x/{n}_agenda.pdf", "議事次第", "agenda")]

    # METI committee: backfill resolves subpage URLs from one index fetch.
    monkeypatch.setattr(detect_mod, "fetch_meti_url_map",
                        lambda c, **kw: {1: "https://x/001.html", 2: "https://x/002.html"})
    monkeypatch.setattr(detect_mod, "list_materials", fake_list)
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)

    results = detect_mod.backfill_materials([key], db_path=db)

    row = next(r for r in results if r["key"] == key)
    assert row["materialised"] == 2 and row["checked"] == 2
    # Both meetings now carry a material, so none remain hidden.
    assert store.meetings_missing_materials(key, db_path=db) == []
    assert len(store.meeting_materials(key, 2, db_path=db)) == 1


def test_backfill_materials_respects_per_committee_limit(monkeypatch, tmp_path):
    """The catch-up path caps work per committee so a full self-heal spreads across
    runs instead of hammering the source in one pass."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"
    for n in range(1, 6):
        store.record_meeting(key, n, None, db_path=db)

    monkeypatch.setattr(detect_mod, "fetch_meti_url_map",
                        lambda c, **kw: {n: f"https://x/{n:03d}.html" for n in range(1, 6)})
    monkeypatch.setattr(detect_mod, "list_materials",
                        lambda c, n, **kw: [Material(n, f"{n:03d}_01",
                                                     f"https://x/{n}.pdf", "議事次第", "agenda")])
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)

    results = detect_mod.backfill_materials([key], db_path=db, limit_per_committee=2)

    row = next(r for r in results if r["key"] == key)
    assert row["checked"] == 2 and row["materialised"] == 2  # newest two only
    # Meetings 4 and 5 healed; 1–3 still pending for the next run.
    assert store.meetings_missing_materials(key, db_path=db) == [3, 2, 1]


def test_backfill_materials_meti_fetches_index_once(monkeypatch, tmp_path):
    """A METI committee's index is fetched exactly once per run and each meeting's
    subpage URL is passed through, instead of re-fetching the (WAF-challenged)
    index once per meeting."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"  # METI
    for n in (1, 2, 3):
        store.record_meeting(key, n, None, db_path=db)

    index_fetches = {"n": 0}

    def fake_url_map(c, **kw):
        index_fetches["n"] += 1
        return {1: "https://x/001.html", 2: "https://x/002.html", 3: "https://x/003.html"}

    seen_page_urls: list[str | None] = []

    def fake_list(c, n, **kw):
        seen_page_urls.append(kw.get("page_url"))
        return [Material(n, f"{n:03d}_01", f"https://x/{n}.pdf", "議事次第", "agenda")]

    monkeypatch.setattr(detect_mod, "fetch_meti_url_map", fake_url_map)
    monkeypatch.setattr(detect_mod, "list_materials", fake_list)
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)

    results = detect_mod.backfill_materials([key], db_path=db)

    assert index_fetches["n"] == 1  # one index fetch for all three meetings
    assert seen_page_urls == ["https://x/003.html", "https://x/002.html", "https://x/001.html"]
    assert next(r for r in results if r["key"] == key)["materialised"] == 3


def test_backfill_materials_stops_when_the_host_budget_is_spent(monkeypatch, tmp_path):
    """meti.go.jp serves ~5 requests then blocks this IP outright for minutes, so a
    sweep stops short of the cliff and leaves the rest for the next run rather than
    collecting blocked meetings and teaching the edge to escalate sooner."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"  # METI
    for n in range(1, 6):
        store.record_meeting(key, n, None, db_path=db)

    fetched: list[int] = []

    def fake_list(c, n, **kw):
        fetched.append(n)
        return [Material(n, f"{n:03d}_01", f"https://x/{n}.pdf", "議事次第", "agenda")]

    monkeypatch.setattr(detect_mod, "fetch_meti_url_map",
                        lambda c, **kw: {n: f"https://x/{n:03d}.html" for n in range(1, 6)})
    monkeypatch.setattr(detect_mod, "list_materials", fake_list)
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(detect_mod, "budget_exhausted", lambda url: len(fetched) >= 2)

    results = detect_mod.backfill_materials([key], db_path=db)

    row = next(r for r in results if r["key"] == key)
    assert row["checked"] == 2 and row["materialised"] == 2
    assert row["deferred"] == 3  # reported, so the run doesn't read as complete
    # Untouched, not failed: the next run picks them up.
    assert store.meetings_missing_materials(key, db_path=db) == [3, 2, 1]


def test_detect_defers_committees_once_the_host_budget_is_spent(monkeypatch, tmp_path):
    """A deferred committee is never fetched, and is not recorded as a failure —
    it simply wasn't looked at this pass."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    discovered: list[str] = []

    def fake_discover(c, **kw):
        discovered.append(c.key)
        return Discovery(status="ok", meeting_nums=[1])

    monkeypatch.setattr(detect_mod, "discover_meetings", fake_discover)
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [])
    monkeypatch.setattr(detect_mod, "budget_exhausted", lambda url: len(discovered) >= 1)

    results = detect_mod.detect(db_path=db)

    assert len(discovered) == 1, "the sweep must stop after the allowance is spent"
    deferred = [r for r in results if r["status"] == "deferred"]
    assert len(deferred) == len(results) - 1
    assert all(r["error_kind"] is None for r in deferred)


def test_backfill_materials_defers_when_index_unreachable(monkeypatch, tmp_path):
    """If a METI committee's index can't be fetched (e.g. a persistent WAF 202),
    backfill defers the whole committee rather than hammering it per meeting."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"  # METI
    store.record_meeting(key, 1, None, db_path=db)
    store.record_meeting(key, 2, None, db_path=db)

    called = {"list": 0}

    def fake_list(c, n, **kw):
        called["list"] += 1
        return [Material(n, f"{n:03d}_01", f"https://x/{n}.pdf", "議事次第", "agenda")]

    monkeypatch.setattr(detect_mod, "fetch_meti_url_map", lambda c, **kw: {})  # unreachable
    monkeypatch.setattr(detect_mod, "list_materials", fake_list)
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)

    results = detect_mod.backfill_materials([key], db_path=db)

    row = next(r for r in results if r["key"] == key)
    assert row["materialised"] == 0 and row["checked"] == 0
    assert called["list"] == 0  # never fell through to per-meeting index fetches
    # Meetings stay pending so the next run retries them.
    assert store.meetings_missing_materials(key, db_path=db) == [2, 1]


# ── Meeting dates recorded during detection ──────────────────────────────────
def test_detect_records_meeting_dates_from_the_index(monkeypatch, tmp_path):
    """METI/EGC indexes print the meeting date next to the meeting link, so
    detection must persist it from the body it already parsed — otherwise the date
    depends on a second full crawl that routinely doesn't finish, and the Deep
    Dive falls back to showing the detection date instead of the date held."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"  # METI
    store.record_meeting(key, 1, None, db_path=db)  # known, and dateless

    disc = scraper.Discovery(
        "ok", [2, 1],
        {1: datetime.date(2026, 1, 20), 2: datetime.date(2026, 2, 2)},
    )
    monkeypatch.setattr(detect_mod, "discover_meetings", lambda c, **kw: disc)
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [])

    results = detect_mod.detect([key], db_path=db)

    row = next(r for r in results if r["key"] == key)
    assert row["new"] == 1 and row["dated"] == 2
    # Both the newly-detected and the already-known meeting got their real date.
    assert store.meetings_missing_date(key, db_path=db) == []


def test_detect_dry_run_does_not_write_dates(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"
    store.record_meeting(key, 1, None, db_path=db)

    disc = scraper.Discovery("ok", [1], {1: datetime.date(2026, 1, 20)})
    monkeypatch.setattr(detect_mod, "discover_meetings", lambda c, **kw: disc)
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [])

    results = detect_mod.detect([key], db_path=db, dry_run=True)

    assert next(r for r in results if r["key"] == key)["dated"] == 0
    assert store.meetings_missing_date(key, db_path=db) == [1]


def test_discover_meetings_carries_meti_index_dates(monkeypatch):
    """The METI index body yields numbers *and* dates in one parse."""
    html = (
        "<ul>"
        "<li><a href='/shingikai/enecho/denryoku_gas/genshiryoku/049.html'>"
        "2026年6月25日　第49回</a></li>"
        "<li><a href='/shingikai/enecho/denryoku_gas/genshiryoku/048.html'>"
        "2026年3月24日　第48回</a></li>"
        # Footer/nav link outside /shingikai/ must not register as a meeting.
        "<li><a href='/main/31.html'>2026年1月1日</a></li>"
        "</ul>"
    ).encode()
    committee = Committee(
        key="genshiryoku", name_ja="原子力小委員会", name_en="Nuclear Subcommittee",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/genshiryoku/",
        source="METI",
    )
    monkeypatch.setattr(scraper, "_fetch_ex", lambda url, **kw: scraper.FetchResult("ok", html))

    disc = scraper.discover_meetings(committee)

    assert disc.status == "ok"
    assert disc.meeting_nums == [49, 48]
    assert disc.dates == {49: datetime.date(2026, 6, 25), 48: datetime.date(2026, 3, 24)}


# ── Fetch-failure observability ──────────────────────────────────────────────
# A committee that cannot be fetched used to leave no trace: no cache row (the
# error raised before the store), no status on the committee, and — for OCCTO —
# a silently *truncated* meeting list reported as a clean success.


def test_blocked_index_reports_the_cause_instead_of_a_bare_error(monkeypatch):
    """`discover_meetings` must carry the reason out, not collapse it to "error"."""
    committee = committee_by_key("system_review")
    monkeypatch.setattr(
        scraper, "_fetch_ex",
        lambda url, **kw: scraper.FetchResult(
            "error", None, kind="challenge_unresolved", detail="WAF challenge", url=url,
        ),
    )

    disc = scraper.discover_meetings(committee)

    assert disc.status == "error"
    assert disc.error_kind == "challenge_unresolved"
    assert "WAF" in (disc.error_detail or "")
    assert disc.error_url


def test_occto_probe_aborts_rather_than_truncating_when_blocked(monkeypatch):
    """The data-corruption case, not just an observability one.

    A blocked probe used to look exactly like a 404, so the scan counted it as a
    miss, stopped, and returned a meeting list missing everything above the block
    — which detection then recorded as authoritative. Aborting is the only safe
    answer: a reported error can be retried, a lost meeting is never noticed.
    """
    committee = Committee(
        key="occto_x", name_ja="X", name_en="X",
        url="https://www.occto.or.jp/iinkai/x/index.html", source="OCCTO",
    )
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    # 11 and 12 exist; the host then starts blocking us at 13.
    monkeypatch.setattr(
        scraper, "_exists",
        lambda url: True if url.rsplit("/", 1)[-1] in ("11.html", "12.html") else None,
    )

    latest, kind = scraper.probe_occto_latest(committee, start_from=10)

    assert latest is None, "a partial scan must not be passed off as the frontier"
    assert kind == "blocked_403"


def test_occto_probe_still_tolerates_a_real_gap(monkeypatch):
    """The tri-state must not make genuine 404s abort the scan."""
    committee = Committee(
        key="occto_y", name_ja="Y", name_en="Y",
        url="https://www.occto.or.jp/iinkai/y/index.html", source="OCCTO",
    )
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    present = {"11.html", "13.html"}
    monkeypatch.setattr(
        scraper, "_exists", lambda url: url.rsplit("/", 1)[-1] in present,
    )

    latest, kind = scraper.probe_occto_latest(committee, start_from=10)

    assert kind is None
    assert latest == 13


def test_detect_persists_the_failure_so_it_can_be_diagnosed_later(monkeypatch, tmp_path):
    """Terminal output is ephemeral; the committee row is what survives a run."""
    db = str(tmp_path / "t.db")
    key = "system_review"
    store.sync_committees(db_path=db)
    monkeypatch.setattr(
        detect_mod, "discover_meetings",
        lambda c, **kw: Discovery(
            status="error", meeting_nums=[],
            error_kind="blocked_403", error_detail="blocked with status 403",
            error_url=c.url,
        ),
    )

    results = detect_mod.detect(keys=[key], db_path=db)

    assert next(r for r in results if r["key"] == key)["error_kind"] == "blocked_403"
    row = next(c for c in store.list_committees(db_path=db) if c["key"] == key)
    assert row["last_fetch_status"] == "error"
    assert row["last_fetch_kind"] == "blocked_403"
    # Stamped even though it failed: "attempted and failed" must be
    # distinguishable from "never scheduled".
    assert row["last_fetch_at"] is not None
    assert row["consecutive_failures"] == 1
    assert row["last_ok_at"] is None


def test_consecutive_failures_accumulate_then_reset_on_success(tmp_path):
    db = str(tmp_path / "t.db")
    key = "system_review"
    store.sync_committees(db_path=db)

    for _ in range(3):
        store.set_committee_fetch_result(
            key, "error", kind="blocked_403", detail="nope", url="u", db_path=db,
        )
    row = next(c for c in store.list_committees(db_path=db) if c["key"] == key)
    assert row["consecutive_failures"] == 3

    store.set_committee_fetch_result(key, "ok", url="u", db_path=db)
    row = next(c for c in store.list_committees(db_path=db) if c["key"] == key)
    assert row["consecutive_failures"] == 0
    assert row["last_fetch_kind"] is None
    assert row["last_ok_at"] is not None


# ── Fetch rotation ───────────────────────────────────────────────────────────
# A sweep only gets a handful of committees past the WAF per host before the
# circuit opens. With fixed registry order the same few consumed that budget every
# run and the rest starved permanently.


def _keys_in_fetch_order(db):
    from repower.policy.detect import _select_committees

    return [c.key for c in _select_committees(None, db)]


def test_sweep_puts_the_least_recently_succeeded_first(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    order = _keys_in_fetch_order(db)
    first, second, third = order[0], order[1], order[2]

    # `first` and `second` succeed, so they should drop behind everyone still
    # carrying no successful fetch at all.
    store.set_committee_fetch_result(first, "ok", db_path=db)
    store.set_committee_fetch_result(second, "ok", db_path=db)

    rotated = _keys_in_fetch_order(db)

    assert rotated[0] == third, "a never-succeeded committee must outrank a fresh success"
    assert rotated.index(first) > rotated.index(third)
    assert rotated.index(second) > rotated.index(third)
    # Rotation reorders, it must never drop or duplicate committees.
    assert sorted(rotated) == sorted(order)


def test_rotation_actually_rotates_when_nothing_succeeds(tmp_path):
    """The property that makes this a rotation rather than a reshuffle.

    A committee that can never succeed keeps `last_ok_at` NULL forever. If only
    that were consulted it would hold first place on every run and simply move the
    starvation onto a different victim, so the pass would still only ever touch the
    same committees. Being *attempted* has to cost it its place.
    """
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    order = _keys_in_fetch_order(db)
    budget = order[:3]

    # Simulate one pass where the whole budget was spent and every attempt failed.
    for k in budget:
        store.set_committee_fetch_result(k, "error", kind="challenge_unresolved", db_path=db)

    nxt = _keys_in_fetch_order(db)

    assert set(nxt[:3]).isdisjoint(budget), (
        "committees just attempted must not immediately reclaim the budget"
    )
    assert nxt[:3] == order[3:6], "the next-starved committees should be up"


def test_rotation_covers_every_committee_over_successive_passes(tmp_path):
    """End-to-end fairness under production semantics.

    Mirrors a real sweep: the first few committees per pass get through, then the
    circuit opens and *every remaining committee is still stamped* as collateral.
    That full stamping is what previously made this hard to get right — it means
    "was attempted" cannot be inferred from having a timestamp, so the rotation has
    to survive every row moving on every pass.
    """
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    order = _keys_in_fetch_order(db)
    total = len(order)
    budget = 3

    reached: set[str] = set()
    for _ in range(-(-total // budget)):  # ceil: just enough passes to cover all
        sweep = _keys_in_fetch_order(db)
        for i, k in enumerate(sweep):
            if i < budget:
                reached.add(k)
                store.set_committee_fetch_result(k, "ok", db_path=db)
            else:
                # Collateral: never actually fetched, but still recorded.
                store.set_committee_fetch_result(
                    k, "error", kind="circuit_open", db_path=db,
                )

    assert reached == set(order), (
        f"only {len(reached)}/{total} committees were ever reached — starvation"
    )


def test_registry_order_is_unchanged_for_non_sweep_callers(tmp_path):
    """Rotation is opt-in: listings and the UI must stay in stable registry order,
    or committees would appear to jump around between page loads."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    before = [c.key for c in store.tracked_committees(db_path=db, sync=False,
                                                      include_disabled=True)]
    store.set_committee_fetch_result(before[0], "ok", db_path=db)
    after = [c.key for c in store.tracked_committees(db_path=db, sync=False,
                                                     include_disabled=True)]

    assert after == before


def test_explicit_keys_keep_the_callers_order(tmp_path):
    """`--committee a --committee b` is user intent, not a sweep to be reordered."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    keys = _keys_in_fetch_order(db)[:3]
    store.set_committee_fetch_result(keys[0], "ok", db_path=db)

    from repower.policy.detect import _select_committees

    picked = [c.key for c in _select_committees(list(reversed(keys)), db)]

    assert picked == list(reversed(keys))


def test_a_later_failure_preserves_the_last_known_good_time(tmp_path):
    """`last_ok_at` answers "how long has this been broken?" — an error must not
    overwrite it, or the answer becomes unrecoverable."""
    db = str(tmp_path / "t.db")
    key = "system_review"
    store.sync_committees(db_path=db)

    store.set_committee_fetch_result(key, "ok", url="u", db_path=db)
    ok_at = next(c for c in store.list_committees(db_path=db) if c["key"] == key)["last_ok_at"]
    store.set_committee_fetch_result(key, "error", kind="circuit_open", db_path=db)

    row = next(c for c in store.list_committees(db_path=db) if c["key"] == key)
    assert row["last_ok_at"] == ok_at
    assert row["last_fetch_status"] == "error"


def test_fetch_event_history_is_capped_per_committee(tmp_path):
    """The log rides the Hugging Face sync, so it must not grow without bound."""
    db = str(tmp_path / "t.db")
    key = "system_review"
    store.sync_committees(db_path=db)

    for i in range(store.FETCH_EVENTS_PER_COMMITTEE + 7):
        store.set_committee_fetch_result(
            key, "error", kind="blocked_403", detail=f"attempt {i}", db_path=db,
        )

    events = store.fetch_events(key, limit=200, db_path=db)
    assert len(events) == store.FETCH_EVENTS_PER_COMMITTEE
    # Newest kept, oldest dropped.
    assert "attempt 26" in (events[0]["detail"] or "")


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


def test_regenerate_running_doc_for_discovered_committee(monkeypatch, tmp_path):
    """A discovered committee (in the DB, not the static config — e.g. one the
    cross-check accumulated) must render its running doc. build_running_doc used to
    call committee_by_key and KeyError on these, breaking backfill/summarise."""
    db = str(tmp_path / "t.db")
    policy_dir = tmp_path / "policy"
    monkeypatch.setattr(store, "POLICY_DIR", policy_dir)

    store.sync_committees(db_path=db)
    store.upsert_discovered_committees(
        [{"key": "gx_demand", "name_ja": "GX需要創出に向けた研究会", "source": "METI",
          "url": "https://www.meti.go.jp/shingikai/energy_environment/gx_demand/"}],
        db_path=db,
    )
    assert "gx_demand" not in {c.key for c in COMMITTEES}  # genuinely not in config
    store.record_meeting("gx_demand", 3, None, db_path=db)
    pend = store.pending_meetings("gx_demand", db_path=db)
    store.update_meeting(pend[0]["id"], db_path=db, state="done",
                         briefing_md="## 論点\nGX需要の創出策。")

    path = store.regenerate_running_doc("gx_demand", db_path=db)
    text = Path(path).read_text(encoding="utf-8")
    assert "GX需要創出に向けた研究会" in text  # JA name used as the (missing) EN title
    assert "第3回" in text


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


def test_synthesize_committee_recovers_stalled_report(monkeypatch, tmp_path):
    """A synthesis run interrupted between add_source (synth_done already set)
    and report generation must be recovered: the next pass regenerates the
    report from the existing notebook instead of skipping the committee forever."""
    db = str(tmp_path / "t.db")
    key = "emissions_trading"
    store.sync_committees(db_path=db)
    monkeypatch.setattr(store, "POLICY_DIR", tmp_path / "policy")

    # One done meeting whose briefing was folded in (synth_done=1) before the
    # interrupted run died — running_summary_md never written.
    store.record_meeting(key, 4, None, db_path=db)
    mid = store.pending_meetings(key, db_path=db)[0]["id"]
    store.update_meeting(mid, db_path=db, state="done", briefing_md="briefing 4")
    store.mark_synthesized(key, 4, db_path=db)
    store.update_committee(key, db_path=db, synthesis_notebook_id="nb-123")

    assert store.synthesized_meeting_nums(key, db_path=db) == [4]
    assert store.stalled_synthesis_committees(db_path=db) == [key]

    reported: list[str] = []
    monkeypatch.setattr(nb_mod, "create_notebook",
                        lambda *a, **k: pytest.fail("must reuse the existing notebook"))
    monkeypatch.setattr(nb_mod, "add_source",
                        lambda *a, **k: pytest.fail("no new sources to add"))
    monkeypatch.setattr(nb_mod, "generate_report",
                        lambda nb_id, *a, **k: reported.append(nb_id) or "task-1")
    monkeypatch.setattr(nb_mod, "wait_artifact", lambda *a, **k: True)

    def fake_download(nb_id, task_id, out):
        Path(out).write_text("synthesis body", encoding="utf-8")
        return True

    monkeypatch.setattr(nb_mod, "download_report", fake_download)
    monkeypatch.setattr(nb_mod, "ask", lambda *a, **k: {"answer": "EN digest"})

    assert pipeline.synthesize_committee(committee_by_key(key), db_path=db) is True

    row = store.get_committee(key, db_path=db)
    assert reported == ["nb-123"]
    assert row.running_summary_md == "synthesis body"
    assert row.running_digest_en_md == "EN digest"
    assert row.last_synth_meeting == 4
    assert row.source_count == 1
    # Recovered → no longer stalled; a further pass with nothing new is a no-op.
    assert store.stalled_synthesis_committees(db_path=db) == []
    assert pipeline.synthesize_committee(committee_by_key(key), db_path=db) is False


def test_synthesize_committee_rolls_over_at_source_cap(monkeypatch, tmp_path):
    """At the NotebookLM source cap the synthesis continues in a NEW notebook
    instead of dropping the briefings: the full notebook is left untouched, the
    watermark records where it stops, and new meetings land in the fresh one."""
    db = str(tmp_path / "t.db")
    key = "emissions_trading"
    store.sync_committees(db_path=db)
    monkeypatch.setattr(store, "POLICY_DIR", tmp_path / "policy")
    monkeypatch.setattr(pipeline, "NOTEBOOKLM_SOURCE_CAP", 2)

    def _done(num, *, folded=False):
        store.record_meeting(key, num, None, db_path=db)
        mid = next(m["id"] for m in store.pending_meetings(key, db_path=db)
                   if m["meeting_num"] == num)
        store.update_meeting(mid, db_path=db, state="done",
                             briefing_md=f"briefing {num}", synth_done=folded)

    # Two briefings already folded in → the live notebook sits at the cap; one
    # newly-done meeting is waiting to be synthesized.
    _done(5, folded=True)
    _done(6, folded=True)
    _done(7)
    store.update_committee(key, db_path=db, synthesis_notebook_id="nb-full", source_count=2)

    created: list[str] = []
    added: list[tuple[str, str]] = []
    monkeypatch.setattr(nb_mod, "create_notebook",
                        lambda title: (created.append(title), "nb-new")[1])
    monkeypatch.setattr(nb_mod, "add_source",
                        lambda nb_id, path: (added.append((nb_id, path)), "src-1")[1])
    monkeypatch.setattr(nb_mod, "generate_report", lambda *a, **k: "task-1")
    monkeypatch.setattr(nb_mod, "wait_artifact", lambda *a, **k: True)

    def fake_download(nb_id, task_id, out):
        Path(out).write_text("rolled-over synthesis", encoding="utf-8")
        return True

    monkeypatch.setattr(nb_mod, "download_report", fake_download)
    monkeypatch.setattr(nb_mod, "ask", lambda *a, **k: {"answer": "EN"})

    assert pipeline.synthesize_committee(committee_by_key(key), db_path=db) is True
    row = store.get_committee(key, db_path=db)
    assert row.synthesis_notebook_id == "nb-new"  # rolled over
    assert row.archive_watermark_meeting == 6  # the full notebook stops here
    assert created == ["emissions_trading synthesis (第7回〜)"]
    assert [nb_id for nb_id, _ in added] == ["nb-new"]  # nothing added to the full one
    assert row.source_count == 1  # fresh notebook holds just the new briefing
    assert row.running_summary_md == "rolled-over synthesis"
    # The briefing is no longer stranded: it is folded into the new notebook.
    assert store.meetings_for_synthesis(key, db_path=db) == []


def test_synthesis_source_count_survives_a_stale_cached_value(monkeypatch, tmp_path):
    """``source_count`` is only a cached mirror — an interrupted run can leave it
    stale, so the live notebook's size is derived from the synth_done meetings
    above the watermark instead."""
    db = str(tmp_path / "t.db")
    key = "emissions_trading"
    store.sync_committees(db_path=db)
    monkeypatch.setattr(store, "POLICY_DIR", tmp_path / "policy")
    monkeypatch.setattr(pipeline, "NOTEBOOKLM_SOURCE_CAP", 2)

    for num in (5, 6):
        store.record_meeting(key, num, None, db_path=db)
        mid = next(m["id"] for m in store.pending_meetings(key, db_path=db)
                   if m["meeting_num"] == num)
        store.update_meeting(mid, db_path=db, state="done",
                             briefing_md=f"briefing {num}", synth_done=True)
    store.record_meeting(key, 7, None, db_path=db)
    mid7 = next(m["id"] for m in store.pending_meetings(key, db_path=db)
                if m["meeting_num"] == 7)
    store.update_meeting(mid7, db_path=db, state="done", briefing_md="briefing 7")
    # NULL cached count, as an interrupted run leaves it — the cap must still bite.
    store.update_committee(key, db_path=db, synthesis_notebook_id="nb-full", source_count=None)

    monkeypatch.setattr(nb_mod, "create_notebook", lambda title: "nb-new")
    monkeypatch.setattr(nb_mod, "add_source", lambda *a, **k: "src-1")
    monkeypatch.setattr(nb_mod, "generate_report", lambda *a, **k: "task-1")
    monkeypatch.setattr(nb_mod, "wait_artifact", lambda *a, **k: True)
    monkeypatch.setattr(nb_mod, "download_report",
                        lambda nb_id, task_id, out: Path(out).write_text("s", encoding="utf-8") or True)
    monkeypatch.setattr(nb_mod, "ask", lambda *a, **k: {"answer": "EN"})

    assert pipeline.synthesize_committee(committee_by_key(key), db_path=db) is True
    assert store.get_committee(key, db_path=db).synthesis_notebook_id == "nb-new"


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


def test_search_committees_query_and_tracked_flag():
    root = "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/"

    def fake_fetch(u):
        return ("ok", METI_ROOT_INDEX.encode("utf-8"))

    # Japanese-name query.
    cands = discover_mod.search_committees(
        "CCS", roots=(root,), fetch=fake_fetch, tracked_urls=set(), tracked_keys=set())
    assert [c.key for c in cands] == ["ccus_jigyo"]

    # already_tracked is flagged when the key is in the registry.
    cands = discover_mod.search_committees(
        "", roots=(root,), fetch=fake_fetch,
        tracked_urls=set(), tracked_keys={"system_review"})
    tracked = {c.key: c.already_tracked for c in cands}
    assert tracked["system_review"] is True and tracked["ccus_jigyo"] is False


def test_search_english_query_bridges_to_japanese():
    root = "https://www.occto.or.jp/iinkai/"

    def fake_fetch(u):
        return ("ok", OCCTO_ROOT_INDEX.encode("utf-8"))

    # "capacity" (EN) should match 容量市場… via the EN→JA hint bridge.
    cands = discover_mod.search_committees(
        "capacity", roots=(root,), fetch=fake_fetch, tracked_urls=set(), tracked_keys=set())
    assert [c.key for c in cands] == ["youryou_kentoukai"]
    assert cands[0].source == "OCCTO"


def test_search_committees_default_fetch_survives_cached_root(monkeypatch, tmp_path):
    """Regression: the default fetch must force a body. The index roots overlap
    the catalog/detect crawls, so a plain conditional GET of an already-cached
    root 304s with no content — and the second search over the same root used to
    silently return zero candidates."""
    db = str(tmp_path / "t.db")
    root = "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/"
    calls = {"n": 0}

    def fake_fetch(url, *, db_path=None, force=False):
        calls["n"] += 1
        if force or calls["n"] == 1:  # conditional_get: force=True always yields a body
            return ("ok", METI_ROOT_INDEX.encode("utf-8"))
        return ("not_modified", None)  # warm cache → 304, no body

    monkeypatch.setattr(discover_mod, "_fetch", fake_fetch)
    first = discover_mod.search_committees("", db_path=db, roots=(root,))
    second = discover_mod.search_committees("", db_path=db, roots=(root,))
    assert {c.key for c in first} == {"system_review", "saisei_kano", "ccus_jigyo"}
    assert {c.key for c in second} == {c.key for c in first}


def test_guess_key_egc_shape_and_others_unchanged():
    # EGC pages are flat files under /activity/ — the key must be emsc_<slug>
    # (aligned with catalog.parse_egc_committees), not a collapsed "activity".
    assert discover_mod.guess_key(
        "https://www.egc.meti.go.jp/activity/index_system.html") == "emsc_system"
    assert discover_mod.guess_key(
        "https://www.egc.meti.go.jp/activity/index_systemsurveillance.html"
    ) == "emsc_systemsurveillance"
    # OCCTO / METI behaviour is unchanged.
    assert discover_mod.guess_key(
        "https://www.occto.or.jp/iinkai/chousei_jukyu/index.html") == "chousei_jukyu"
    assert discover_mod.guess_key(
        "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/system_review/") == "system_review"


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
        fetch=lambda u: ("ok", "<html><title>新しい委員会</title></html>".encode()),
        validate=True, tracked_urls=set(), tracked_keys=set(),
    )
    assert cand.source == "OCCTO" and "3 meeting" in cand.note


def test_probe_url_rejects_non_http():
    assert discover_mod.probe_url("not a url", validate=False,
                                  tracked_urls=set(), tracked_keys=set()) is None


def test_probe_url_default_path_survives_cached_url(monkeypatch, tmp_path):
    """Regression: probe_url fetches the pasted URL, then its validation
    (discover_meetings) re-fetches it — so both must force a body, or the
    second (conditional) GET 304s and the meeting-count preview breaks."""
    db = str(tmp_path / "t.db")
    url = "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/system_review/"
    fetched = {"n": 0}

    def fake_fetch(u, *, db_path=None, force=False):
        fetched["n"] += 1
        if force or fetched["n"] == 1:
            return ("ok", "<html><title>制度検討作業部会</title></html>".encode())
        return ("not_modified", None)

    monkeypatch.setattr(discover_mod, "_fetch", fake_fetch)
    seen: dict = {}

    def fake_discover(c, **kw):
        seen.update(kw)
        # Mirror the real METI path: only a forced fetch has a body to parse.
        return Discovery("ok", [3, 2, 1]) if kw.get("force") else Discovery("unchanged", [])

    monkeypatch.setattr(discover_mod, "discover_meetings", fake_discover)
    cand = discover_mod.probe_url(url, db_path=db, validate=True)
    assert cand is not None and cand.name_ja == "制度検討作業部会"
    assert seen.get("force") is True
    # The OCCTO by-number scan is capped on the preview path only.
    assert seen.get("max_probes") == discover_mod.PROBE_PREVIEW_MAX
    assert "3 meeting" in cand.note


def test_probe_url_flags_unreachable():
    """A fetch that errors (or raises) must yield a Candidate noted 'unreachable',
    not a silent empty note — the UI distinguishes it from a parse failure."""
    def boom(u):
        raise OSError("network down")

    for fetch in (lambda u: ("error", None), boom):
        cand = discover_mod.probe_url(
            "https://www.meti.go.jp/shingikai/nowhere/", fetch=fetch, validate=False,
            tracked_urls=set(), tracked_keys=set())
        assert cand is not None and cand.note == "unreachable"


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


def test_disabled_committee_detected_but_not_summarised(monkeypatch, tmp_path):
    """Detection is decoupled from tracking: detect() scans *every* committee — so
    discovered/untracked ones get their meetings recorded as pending — while the
    ``enabled`` flag only gates summarisation (the daily worklist)."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.set_committee_enabled("santeii", False, db_path=db)

    tracked_keys = {c.key for c in store.tracked_committees(db_path=db)}
    assert "santeii" not in tracked_keys  # enabled-only helper still excludes it
    assert "system_review" in tracked_keys

    # detect() now scans the whole catalog — including the disabled committee — and
    # records a new (pending) meeting for it.
    seen: list[str] = []

    def fake_discover(c, **kw):
        seen.append(c.key)
        return Discovery("ok", [1]) if c.key == "santeii" else Discovery("unchanged", [])

    monkeypatch.setattr(detect_mod, "discover_meetings", fake_discover)
    monkeypatch.setattr(detect_mod, "list_materials", lambda c, n, **kw: [])
    detect_mod.detect(db_path=db)
    assert "santeii" in seen and "system_review" in seen

    # …but the disabled committee is kept out of the summarisation worklist, while
    # it still shows up when the enabled filter is off (e.g. the deep-dive feed).
    q_enabled = {w["committee_key"] for w in store.pending_meetings(db_path=db, only_enabled=True)}
    q_all = {w["committee_key"] for w in store.pending_meetings(db_path=db, only_enabled=False)}
    assert "santeii" not in q_enabled
    assert "santeii" in q_all


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


# ── Fetch-failure attribution (`policy doctor`) ──────────────────────────────
def test_collateral_failures_are_grouped_by_host_not_committee():
    """`circuit_open` means "some *other* committee on this host tripped the
    breaker" — it is fallout, not a fault. A pass where one host goes hostile
    produced 32 of these, and counting them as 32 problems hid the 2 that were
    real. They must be attributed to the host and excluded from the count."""
    from repower.cli import _COLLATERAL_KINDS, _fetch_host

    assert "circuit_open" in _COLLATERAL_KINDS
    # The kinds that describe a committee's *own* failure must not be swept in.
    assert not _COLLATERAL_KINDS & {"not_found", "parse_error", "blocked_403"}

    rows = [
        {"last_fetch_url": "https://www.meti.go.jp/shingikai/a/index.html", "url": ""},
        {"last_fetch_url": "https://WWW.METI.GO.JP:443/other.html", "url": ""},
        {"last_fetch_url": "https://www.egc.meti.go.jp/x.html", "url": ""},
    ]
    hosts = [_fetch_host(r) for r in rows]
    # Case and an explicit default port are the same server — grouping must agree,
    # or one hostile host reports as two.
    assert hosts == ["www.meti.go.jp", "www.meti.go.jp", "www.egc.meti.go.jp"]


def test_fetch_host_falls_back_to_the_configured_url():
    """A pass can fail before any request is issued (open circuit), leaving
    last_fetch_url empty. The committee's homepage still identifies the host, so
    the row is attributed rather than dumped into an unhelpful '?' bucket."""
    from repower.cli import _fetch_host

    assert _fetch_host({"last_fetch_url": None, "url": "https://www.meti.go.jp/a.html"}) == (
        "www.meti.go.jp"
    )
    assert _fetch_host({"last_fetch_url": "", "url": ""}) == "?"


def test_remedies_do_not_advise_slowing_down():
    """Measured: 6s spacing got fewer committees through than 1s (1/12 vs 4/43),
    because METI's WAF is stateful rather than rate-based. Advice to 'slow the
    pass down' or 'widen the retry delays' is therefore actively wrong, and this
    pins it so it can't drift back in."""
    from repower.cli import _FETCH_REMEDIES

    joined = " ".join(_FETCH_REMEDIES.values()).lower()
    for phrase in ("slow the pass down", "widen _challenge_retry_delays"):
        assert phrase not in joined
    assert "circuit_open" in _FETCH_REMEDIES
    assert "collateral" in _FETCH_REMEDIES["circuit_open"].lower()


def test_archived_committees_are_not_reported_as_failing(monkeypatch, capsys):
    """`doctor`'s own remedy for a retired committee is `policy archive`. Archiving
    stops it being fetched, so its last recorded failure never changes — reporting
    it forever would mean following the advice never clears the warning.

    ``list_committees`` is stubbed rather than backed by a temp DB because
    ``policy_doctor`` resolves its own DB path; the field names used here match the
    real return shape (verified against the live DB).
    """
    import repower.cli as cli_mod

    def _row(key, archived, kind="not_found"):
        return {
            "key": key, "committee_key": key, "source": "OCCTO", "enabled": 0,
            "archived": archived, "url": f"https://www.occto.or.jp/iinkai/{key}/",
            "last_fetch_status": "error", "last_fetch_kind": kind,
            "last_fetch_detail": "gone", "last_fetch_url": None,
            "last_fetch_at": "2026-01-01", "last_ok_at": None, "consecutive_failures": 3,
        }

    monkeypatch.setattr(store, "sync_committees", lambda *a, **k: None)
    monkeypatch.setattr(
        store, "list_committees", lambda *a, **k: [_row("dead_one", 1), _row("live_one", 0)]
    )

    cli_mod.policy_doctor(failing_only=True, history=False)
    out = capsys.readouterr().out

    head, _, tail = out.partition("archived committee(s) excluded")
    assert "live_one" in head, "a non-archived failure must still be reported"
    assert "dead_one" not in head, "an archived committee must not be listed as failing"
    assert "1 archived committee(s) excluded" in out
    assert "dead_one" in tail
    # Denominator excludes it too, so the ratio doesn't imply a fetch that never happens.
    assert "1/1 committee(s) need attention" in out


def test_partial_download_is_refused_rather_than_summarised(monkeypatch, tmp_path):
    """A briefing written from a subset of a meeting's papers reads exactly like a
    complete one, so a shortfall must abort the meeting. The real failure: 11 of 12
    documents blocked, the one that landed was the *list* of documents, and
    NotebookLM summarised a table of contents."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key, num = "doji_shijo", 9
    # Minutes sort first, so the order the batch is walked in is deterministic.
    store.record_meeting(
        key, num,
        [Material(num, "009_min", "https://x/9_gijiroku.pdf", "議事録", "minutes"),
         Material(num, "009_h1", "https://x/9_01_00.pdf", "資料1", "handout"),
         Material(num, "009_h2", "https://x/9_02_00.pdf", "資料2", "handout")],
        db_path=db,
    )
    # The first document lands; the host then turns on us.
    monkeypatch.setattr(pipeline, "_download_pdf",
                        lambda url, *a, **k: "ok" if "gijiroku" in url else "circuit_open")
    # Nothing may reach NotebookLM.
    monkeypatch.setattr(pipeline.nb, "create_notebook",
                        lambda *a, **k: pytest.fail("notebook created from a partial source set"))

    assert pipeline.summarize_meeting(committee_by_key(key), num, db_path=db) == "blocked"
    row = _meeting_row(key, num, db)
    assert row["quality_flag"] == "download_blocked"
    assert row["retry_count"] == 0  # host trouble, not a dead meeting
    assert "2 of 3" in row["last_error"]
    # The batch stopped at the first hostile response instead of spending two more
    # doomed requests — each of which is a strike towards opening the host breaker.
    assert "1 not attempted" in row["last_error"]
    # Still queued, so a calm day picks it up whole.
    assert any(m["meeting_num"] == num for m in store.pending_meetings(key, db_path=db))

    # Per-document outcomes are recorded, so "did the briefing see everything?" is
    # answerable from the DB rather than only from the briefing's own prose.
    mats = {m["pdf_id"]: m for m in store.meeting_materials(key, num, db_path=db)}
    assert mats["009_min"]["status"] == "downloaded"
    assert mats["009_h1"]["status"] == "error"
    assert mats["009_h2"]["status"] == "detected"  # never attempted
    assert all(m["nblm_source_id"] is None for m in mats.values())


def test_missing_document_burns_a_retry_even_when_others_download(monkeypatch, tmp_path):
    """A permanently-gone document is the meeting's own problem, so the strict rule
    must still let it leave the worklist rather than retry forever."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key, num = "doji_shijo", 10
    store.record_meeting(
        key, num,
        [Material(num, "010_min", "https://x/10_gijiroku.pdf", "議事録", "minutes"),
         Material(num, "010_h1", "https://x/10_01_00.pdf", "資料1", "handout")],
        db_path=db,
    )
    monkeypatch.setattr(pipeline, "_download_pdf",
                        lambda url, *a, **k: "ok" if "gijiroku" in url else "not_found")

    for expected in range(1, store.MAX_RETRIES + 1):
        assert pipeline.summarize_meeting(committee_by_key(key), num, db_path=db) == "error"
        row = _meeting_row(key, num, db)
        assert row["quality_flag"] == "download_failed" and row["retry_count"] == expected
        assert "1 of 2" in row["last_error"]
    assert not any(m["meeting_num"] == num for m in store.pending_meetings(key, db_path=db))


def test_run_skips_committees_whose_host_is_cooling_down(monkeypatch, tmp_path):
    """One hostile host must not consume the round: its committees are skipped
    without a request, and committees elsewhere still get their turn."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    for key, num in (("doji_shijo", 11), ("chousei_jukyu", 12)):
        store.record_meeting(
            key, num,
            [Material(num, f"{num:03d}_min", f"https://x/{num}_gijiroku.pdf", "議事録", "minutes")],
            db_path=db,
        )
    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)
    # doji_shijo lives on meti.go.jp; chousei_jukyu on occtonet.occto.or.jp.
    monkeypatch.setattr(pipeline, "circuit_cooldown",
                        lambda url: 300.0 if "meti.go.jp" in (url or "") else 0.0)
    attempted: list[str] = []

    def fake_summarize(committee, meeting_num, **kw):
        attempted.append(committee.key)
        return "done"

    monkeypatch.setattr(pipeline, "summarize_meeting", fake_summarize)

    summary = pipeline.run(db_path=db)
    assert "doji_shijo" not in attempted  # never even asked the blocked host
    assert "chousei_jukyu" in attempted
    assert summary["skipped"] >= 1
    assert any("meti.go.jp" in h for h in summary["skipped_hosts"])


def test_meeting_num_targets_one_meeting_and_re_runs_a_done_one(monkeypatch, tmp_path):
    """"Run now" on an already-summarised meeting must re-summarise exactly it, and
    let the corrected briefing back into the committee synthesis."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    key = "doji_shijo"
    for num in (5, 6):
        store.record_meeting(
            key, num,
            [Material(num, f"{num:03d}_min", f"https://x/{num}_gijiroku.pdf", "議事録", "minutes")],
            db_path=db,
        )
    by_num = {m["meeting_num"]: m["id"] for m in store.pending_meetings(key, db_path=db)}
    store.update_meeting(by_num[5], db_path=db, state="done", briefing_md="## thin")
    store.mark_synthesized(key, 5, db_path=db)

    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda *a, **k: False)
    seen: list[int] = []
    monkeypatch.setattr(pipeline, "summarize_meeting",
                        lambda c, n, **kw: (seen.append(n), "done")[1])

    pipeline.run([key], db_path=db, meeting_num=5)
    # Only meeting 5 — the pending meeting 6 is untouched, and `done` was no bar.
    assert seen == [5]
    assert 5 not in store.synthesized_meeting_nums(key, db_path=db)

    with pytest.raises(ValueError):
        pipeline.run(db_path=db, meeting_num=5)  # needs exactly one committee


def test_batch_pace_widens_with_the_number_of_documents():
    """The 2s floor is sized for one-page-per-host sweeps. A meeting is a dozen
    files from the same host, and METI's edge treats that as a burst — so the gap
    grows with the batch and is capped so a huge meeting still finishes."""
    assert pipeline._batch_interval(1) == 2.0
    assert pipeline._batch_interval(4) == 2.0      # unchanged for small meetings
    assert pipeline._batch_interval(6) == 4.0
    assert pipeline._batch_interval(12) == 10.0    # the observed failure case
    assert pipeline._batch_interval(40) == pipeline._BATCH_PACE_CAP
    # Monotonic, and never faster than the politeness floor.
    vals = [pipeline._batch_interval(n) for n in range(1, 40)]
    assert vals == sorted(vals)
    assert min(vals) >= min_host_interval()


def test_blocked_meeting_keeps_its_downloads_for_the_next_attempt(monkeypatch, tmp_path):
    """Re-downloading files we already have spends the few requests the host allows
    on bytes that are already on disk — which is why a large meeting could never
    finish: every attempt re-burned the same budget and failed at the same place."""
    db = str(tmp_path / "t.db")
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(pipeline, "_scratch", lambda: scratch)
    store.sync_committees(db_path=db)
    key, num = "doji_shijo", 13
    store.record_meeting(
        key, num,
        [Material(num, "013_min", "https://x/13_gijiroku.pdf", "議事録", "minutes"),
         Material(num, "013_h1", "https://x/13_01_00.pdf", "資料1", "handout")],
        db_path=db,
    )

    asked: list[str] = []

    def fake_download(url, dest, **kw):
        asked.append(url)
        if "gijiroku" in url:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"%PDF-1.4 minutes")
            return "ok"
        return "challenge_unresolved"

    monkeypatch.setattr(pipeline, "_download_pdf", fake_download)
    assert pipeline.summarize_meeting(committee_by_key(key), num, db_path=db) == "blocked"
    assert len(asked) == 2
    staged = scratch / key / str(num) / "013_min.pdf"
    assert staged.exists()  # kept, not wiped

    # Second attempt: the host is calm now. Only the missing document is requested.
    asked.clear()
    monkeypatch.setattr(pipeline, "_download_pdf", lambda url, dest, **kw: (
        asked.append(url), dest.parent.mkdir(parents=True, exist_ok=True),
        dest.write_bytes(b"%PDF-1.4 handout"), "ok")[-1])
    monkeypatch.setattr(pipeline.nb, "create_notebook", lambda *a, **k: "nb1")
    monkeypatch.setattr(pipeline.nb, "add_source", lambda nb_id, path: f"src:{Path(path).name}")
    monkeypatch.setattr(pipeline.nb, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(pipeline, "_ocr_guard", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.nb, "generate_report", lambda *a, **k: "task1")
    monkeypatch.setattr(pipeline.nb, "wait_artifact", lambda *a, **k: True)

    def fake_download_report(nb_id, task_id, out):
        out.write_text("## 論点\n" + "x" * 500, encoding="utf-8")
        return True

    monkeypatch.setattr(pipeline.nb, "download_report", fake_download_report)
    monkeypatch.setattr(pipeline.nb, "ask", lambda *a, **k: {"answer": "ok"})
    monkeypatch.setattr(pipeline.nb, "delete_notebook", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "regenerate_running_doc", lambda *a, **k: None)

    assert pipeline.summarize_meeting(committee_by_key(key), num, db_path=db) == "done"
    assert asked == ["https://x/13_01_00.pdf"]  # the minutes were NOT re-fetched
    # Both documents are recorded as ingested, so the status table's N/M is honest.
    mats = {m["pdf_id"]: m for m in store.meeting_materials(key, num, db_path=db)}
    assert {m["status"] for m in mats.values()} == {"ingested"}
    assert all(m["nblm_source_id"] for m in mats.values())
    # A finished meeting cleans up after itself.
    assert not (scratch / key / str(num)).exists()


def test_notebooklm_timeout_keeps_the_downloads_it_already_paid_for(monkeypatch, tmp_path):
    """A NotebookLM stall hands the meeting back to a later run — so its documents
    must be handed back with it. Wiping them meant the retry re-ran the whole burst
    against a rate-limited WAF to re-fetch bytes that were already on disk."""
    db = str(tmp_path / "t.db")
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(pipeline, "_scratch", lambda: scratch)
    store.sync_committees(db_path=db)
    key, num = "doji_shijo", 14
    store.record_meeting(
        key, num,
        [Material(num, "014_min", "https://x/14_gijiroku.pdf", "議事録", "minutes"),
         Material(num, "014_h1", "https://x/14_01_00.pdf", "資料1", "handout")],
        db_path=db,
    )

    def fake_download(url, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 body")
        return "ok"

    monkeypatch.setattr(pipeline, "_download_pdf", fake_download)
    monkeypatch.setattr(pipeline.nb, "create_notebook", lambda *a, **k: "nb1")
    monkeypatch.setattr(pipeline.nb, "delete_notebook", lambda *a, **k: None)
    # The first upload lands; the second dies with the connection (what happened).
    calls: list[str] = []

    def flaky_add(nb_id, path):
        calls.append(path)
        if len(calls) == 1:
            return "src1"
        raise nb_mod.NotebookLMTimeout("timeout after 180s: notebooklm source add")

    monkeypatch.setattr(pipeline.nb, "add_source", flaky_add)

    with pytest.raises(nb_mod.NotebookLMTimeout):
        pipeline.summarize_meeting(committee_by_key(key), num, db_path=db)

    # Handed back for a later run …
    row = _meeting_row(key, num, db)
    assert row["state"] == "detected" and row["retry_count"] == 0
    # … with both PDFs still on disk.
    staged = sorted(pp.name for pp in (scratch / key / str(num)).glob("*.pdf"))
    assert staged == ["014_h1.pdf", "014_min.pdf"]

    # The next attempt makes no HTTP requests at all.
    monkeypatch.setattr(pipeline, "_download_pdf",
                        lambda *a, **k: pytest.fail("re-downloaded a file already on disk"))
    monkeypatch.setattr(pipeline.nb, "add_source", lambda nb_id, path: f"src:{Path(path).name}")
    monkeypatch.setattr(pipeline.nb, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(pipeline, "_ocr_guard", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.nb, "generate_report", lambda *a, **k: "t1")
    monkeypatch.setattr(pipeline.nb, "wait_artifact", lambda *a, **k: True)
    monkeypatch.setattr(pipeline.nb, "download_report",
                        lambda n, t, out: (out.write_text("## 論点\n" + "x" * 500, encoding="utf-8"), True)[1])
    monkeypatch.setattr(pipeline.nb, "ask", lambda *a, **k: {"answer": "ok"})
    monkeypatch.setattr(pipeline, "regenerate_running_doc", lambda *a, **k: None)
    assert pipeline.summarize_meeting(committee_by_key(key), num, db_path=db) == "done"


def test_discarded_staging_stops_claiming_the_files_are_downloaded(monkeypatch, tmp_path):
    """`downloaded` is a claim about disk. When the staging is wiped, the status
    table must not keep reporting documents it no longer has."""
    db = str(tmp_path / "t.db")
    monkeypatch.setattr(pipeline, "_scratch", lambda: tmp_path / "scratch")
    store.sync_committees(db_path=db)
    key, num = "doji_shijo", 15
    store.record_meeting(
        key, num,
        [Material(num, "015_min", "https://x/15_gijiroku.pdf", "議事録", "minutes"),
         Material(num, "015_h1", "https://x/15_01_00.pdf", "資料1", "handout")],
        db_path=db,
    )
    # One document lands, the other is permanently gone: a hard error, staging wiped.
    monkeypatch.setattr(pipeline, "_download_pdf",
                        lambda url, dest, **k: "ok" if "gijiroku" in url else "not_found")
    assert pipeline.summarize_meeting(committee_by_key(key), num, db_path=db) == "error"
    mats = {m["pdf_id"]: m["status"] for m in store.meeting_materials(key, num, db_path=db)}
    assert mats["015_min"] == "detected"  # was 'downloaded', but the file is gone
    assert mats["015_h1"] == "error"


def test_add_source_retries_a_dropped_upload_once(monkeypatch):
    """A dropped upload used to halt the run, discarding every PDF already fetched
    for the meeting. One retry is far cheaper than the re-download it prevents."""
    calls = []

    def fake_json(args, *, timeout):
        calls.append(args)
        if len(calls) == 1:
            raise nb_mod.NotebookLMTimeout("timeout after 180s")
        return {"source": {"id": "src-2"}}

    monkeypatch.setattr(nb_mod, "_json", fake_json)
    monkeypatch.setattr(nb_mod.time, "sleep", lambda *_: None)
    assert nb_mod.add_source("nb1", "C:/tmp/a.pdf") == "src-2"
    assert len(calls) == 2

    # A genuinely dead session still halts rather than looping.
    calls.clear()
    monkeypatch.setattr(nb_mod, "_json", lambda *a, **k: (
        calls.append(1), (_ for _ in ()).throw(nb_mod.NotebookLMTimeout("dead")))[0])
    with pytest.raises(nb_mod.NotebookLMTimeout):
        nb_mod.add_source("nb1", "C:/tmp/a.pdf")
    assert len(calls) == 2
