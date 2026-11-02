"""Listing a meeting's documents: *read* versus *empty*.

An empty list from a committee page is two different facts. The page was read and links nothing (the
papers are not up yet): a look worth recording, after which the meeting waits a week. Or the page could
not be read at all (blocked, challenged, 404, a row the index does not carry): nothing is known, so
nothing is recorded and the meeting is asked about again, for free. Both used to read as ``[]``, so the
meeting kept looking *ready*, failed ``no_sources`` (the one charged failure that never spends a retry)
and took one of the day's ``--max-per-run`` slots every day, on every source, ahead of ready work that
never ran: an EGC row with no ※ remark and no links yet, a METI page with no papers, an OCCTO page that
was blocked.

Network-free: the sites are a fake behind ``scraper._fetch_ex`` (the lowest primitive: ``_fetch`` is a
wrapper over it), and NotebookLM is faked wherever a test needs a meeting to get that far.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from repower.dashboard.export_web import _public_error, build_policy_snapshot, build_policy_status
from repower.policy import notebook as nb_mod
from repower.policy import pipeline, scraper, store
from repower.policy.committees import Committee, committee_by_key
from repower.policy.scraper import FetchResult, Material
from repower.policy.store import AWAITING, READY
from repower.timeutil import today_jst

JST = timezone(timedelta(hours=9))


# ── A fake web ───────────────────────────────────────────────────────────────
class FakeWeb:
    """The committee sites as ``scraper._fetch_ex`` sees them.

    A URL nobody registered fails the test instead of answering 404: a lister fetching a page it
    should not have touched (or an index it was told to skip) is a bug, not a missing page.
    """

    def __init__(self) -> None:
        self.pages: dict[str, FetchResult] = {}
        self.board: list[Material] = []  # what the energy-board backup knows of any METI meeting
        self.requests: list[str] = []

    def ok(self, url: str, body: str = "<html><body></body></html>") -> None:
        self.pages[url] = FetchResult("ok", body.encode(), url=url)

    def gone(self, url: str) -> None:
        """A 404: ``conditional_get`` reports it as a status, not an exception, so it has no kind."""
        self.pages[url] = FetchResult("not_found", None, url=url)

    def fail(self, url: str, kind: str) -> None:
        self.pages[url] = FetchResult("error", None, kind=kind, detail=f"{kind} for {url}", url=url)

    def break_(self, url: str, how: str) -> None:
        """``how`` is ``"404"`` or a failure kind."""
        if how == "404":
            self.gone(url)
        else:
            self.fail(url, how)

    def __call__(self, url: str, *, db_path: str | None = None, force: bool = False) -> FetchResult:
        self.requests.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected fetch of {url}")
        return self.pages[url]


@pytest.fixture
def web(monkeypatch) -> FakeWeb:
    fake = FakeWeb()
    monkeypatch.setattr(scraper, "_fetch_ex", fake)
    monkeypatch.setattr(scraper, "POLITE_DELAY", 0.0)
    monkeypatch.setattr(scraper, "_energy_board_materials", lambda c, n, **k: list(fake.board))
    return fake


def _links(*pdfs: str) -> str:
    return "<html><body>" + "".join(f'<a href="{p}">{p}</a>' for p in pdfs) + "</body></html>"


def _table(*rows: str) -> str:
    return "<html><body><table>" + "".join(rows) + "</table></body></html>"


def _egc_row(num: int, *, giji: str | None = None, haifu: str | None = None, note: str = "") -> str:
    """date | 第N回 | 議事要旨 | 議事録 | 配布資料 | 動画 — the ※ remarks sit in the last cell."""
    cells = ["令和8年10月28日", f"第{num}回",
             f'<a href="{giji}">議事要旨</a>' if giji else "", "",
             f'<a href="{haifu}">配布資料</a>' if haifu else "", note]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _meti_index(*nums: int) -> str:
    return "<ul>" + "".join(f'<li><a href="{n:03d}.html">第{n}回</a></li>' for n in nums) + "</ul>"


def _ids(listing) -> list[str]:
    return [m.pdf_id for m in listing.materials]


# One committee per source, each with the page(s) its listing needs.
EGC_BASE = "https://www.egc.meti.go.jp/activity/"
EGC = Committee(key="egc_t", name_ja="試験", name_en="Test", url=EGC_BASE + "index_t.html",
                source="EGC", log_pages=("index_tlog1.html",))
EGC_LOG = EGC_BASE + "index_tlog1.html"
METI = Committee(key="meti_t", name_ja="試験", name_en="Test",
                 url="https://www.meti.go.jp/shingikai/t/", source="METI")
METI_PAGE = METI.url + "015.html"
OCCTO = Committee(key="occto_t", name_ja="試験", name_en="Test",
                  url="https://www.occto.or.jp/iinkai/t/", source="OCCTO")
OCCTO_PAGE = OCCTO.url + "12.html"

# Every way a fetch can fail, as `http_cache.classify` names them.
FETCH_FAILURES = ["challenge_unresolved", "blocked_403", "circuit_open", "deadline_exceeded",
                  "unexpected_status", "server_error", "network_error"]


# ── The listers: read, or not ────────────────────────────────────────────────
def test_egc_a_row_with_links_is_read(web):
    web.ok(EGC.url, _table(_egc_row(621, giji="pdf/621_giji.pdf", haifu="621_haifu.html")))
    web.ok(EGC_BASE + "621_haifu.html", _links("pdf/621_01.pdf"))

    got = scraper.list_materials_ex(EGC, 621)

    assert (got.read, got.error_kind) == (True, None)
    assert _ids(got) == ["621_621_giji", "621_621_01"]


@pytest.mark.parametrize("note", ["", "※書面開催"], ids=["no-remark", "remark"])
def test_egc_a_row_that_links_nothing_was_read_and_is_empty(web, note):
    """第621回 had no ※ remark and no links yet: the page was read, there is just nothing to list."""
    web.ok(EGC.url, _table(_egc_row(621, note=note)))

    got = scraper.list_materials_ex(EGC, 621)

    assert (got.read, got.materials, got.error_kind) == (True, [], None)
    assert web.requests == [EGC.url]  # found on the index, so the log page is not walked


def test_egc_a_log_page_answers_when_the_index_is_down(web):
    web.fail(EGC.url, "challenge_unresolved")
    web.ok(EGC_LOG, _table(_egc_row(621)))

    got = scraper.list_materials_ex(EGC, 621)

    assert (got.read, got.materials) == (True, [])  # the row's own page was read
    assert web.requests == [EGC.url, EGC_LOG]


def test_egc_a_row_on_no_page_is_not_read(web):
    web.ok(EGC.url, _table(_egc_row(622)))
    web.ok(EGC_LOG, _table(_egc_row(600)))

    got = scraper.list_materials_ex(EGC, 621)

    assert (got.read, got.materials, got.error_kind, got.error_url) == (False, [], "not_found", EGC.url)
    assert "第621回" in (got.error_detail or "")


def test_egc_a_page_that_would_not_load_explains_the_row_that_was_not_found(web):
    """The row may have been on the page that failed, so the failure is the better explanation."""
    web.fail(EGC.url, "challenge_unresolved")
    web.ok(EGC_LOG, _table(_egc_row(600)))

    got = scraper.list_materials_ex(EGC, 621)

    assert (got.read, got.error_kind, got.error_url) == (False, "challenge_unresolved", EGC.url)


@pytest.mark.parametrize("how", ["404", "blocked_403"])
def test_egc_a_handout_page_that_will_not_load_is_not_read(web, how):
    haifu = EGC_BASE + "621_haifu.html"
    web.ok(EGC.url, _table(_egc_row(621, giji="pdf/621_giji.pdf", haifu="621_haifu.html")))
    web.break_(haifu, how)

    got = scraper.list_materials_ex(EGC, 621)

    assert got.read is False
    assert (got.error_kind, got.error_url) == ("not_found" if how == "404" else how, haifu)
    # What was found before the failure rides along (detection wants it) but is not the whole list.
    assert _ids(got) == ["621_621_giji"]


def test_meti_a_linked_page_with_papers_is_read(web):
    web.ok(METI.url, _meti_index(15))
    web.ok(METI_PAGE, _links("015_01.pdf", "015_02.pdf"))

    got = scraper.list_materials_ex(METI, 15)

    assert (got.read, got.error_kind) == (True, None)
    assert _ids(got) == ["015_015_01", "015_015_02"]


def test_meti_a_linked_page_with_no_papers_was_read_and_is_empty(web):
    """The saisei_kano case: the page loads, nothing is posted, and the backup knows nothing either."""
    web.ok(METI.url, _meti_index(15))
    web.ok(METI_PAGE, _links())

    got = scraper.list_materials_ex(METI, 15)

    assert (got.read, got.materials, got.error_kind) == (True, [], None)


def test_meti_a_404_page_is_not_read(web):
    web.ok(METI.url, _meti_index(15))
    web.gone(METI_PAGE)

    got = scraper.list_materials_ex(METI, 15)

    assert (got.read, got.materials, got.error_kind, got.error_url) == (False, [], "not_found", METI_PAGE)


def test_meti_a_meeting_the_index_does_not_link_is_not_read_when_the_backup_has_nothing(web):
    web.ok(METI.url, _meti_index(14, 16))

    got = scraper.list_materials_ex(METI, 15)

    assert (got.read, got.materials, got.error_kind, got.error_url) == (False, [], "not_found", METI.url)
    assert "第15回" in (got.error_detail or "")
    assert web.requests == [METI.url]  # no page to fetch


@pytest.mark.parametrize("site", ["unlinked", "page-404", "index-down", "page-empty"])
def test_meti_documents_from_the_energy_board_backup_count_as_found(web, site):
    """Whatever kept the METI pages from answering, the backup's documents are the meeting's papers."""
    if site == "unlinked":
        web.ok(METI.url, _meti_index(14))
    elif site == "page-404":
        web.ok(METI.url, _meti_index(15))
        web.gone(METI_PAGE)
    elif site == "index-down":
        web.fail(METI.url, "challenge_unresolved")
    else:
        web.ok(METI.url, _meti_index(15))
        web.ok(METI_PAGE, _links())
    web.board = [Material(15, "015_board", "https://www.meti.go.jp/x/015_board.pdf", "資料", "handout")]

    got = scraper.list_materials_ex(METI, 15)

    assert (got.read, got.error_kind, got.error_url) == (True, None, None)
    assert _ids(got) == ["015_board"]


def test_meti_a_resolved_page_url_skips_the_index(web):
    """A caller that took the page URL from one shared index fetch reads the page and nothing else
    (the index is not registered with the fake, so fetching it would fail the test)."""
    web.ok(METI_PAGE, _links("015_01.pdf"))

    got = scraper.list_materials_ex(METI, 15, page_url=METI_PAGE)

    assert (got.read, _ids(got)) == (True, ["015_015_01"])
    assert web.requests == [METI_PAGE]

    web.fail(METI_PAGE, "server_error")
    got = scraper.list_materials_ex(METI, 15, page_url=METI_PAGE)
    assert (got.read, got.error_kind, got.error_url) == (False, "server_error", METI_PAGE)


def test_occto_a_page_with_papers_is_read(web):
    web.ok(OCCTO_PAGE, _links("t_12_01.pdf", "t_12_gijiroku.pdf"))

    got = scraper.list_materials_ex(OCCTO, 12)

    assert (got.read, got.error_kind) == (True, None)
    assert _ids(got) == ["012_t_12_01", "012_t_12_gijiroku"]


def test_occto_a_page_that_links_nothing_was_read_and_is_empty(web):
    web.ok(OCCTO_PAGE, _links())

    got = scraper.list_materials_ex(OCCTO, 12)

    assert (got.read, got.materials, got.error_kind) == (True, [], None)


def _break_the_one_page_a_source_needs(web, source: str, how: str):
    """``(committee, meeting, page)`` with the first page that source reads broken."""
    if source == "occto":
        web.break_(OCCTO_PAGE, how)
        return OCCTO, 12, OCCTO_PAGE
    if source == "meti":
        web.break_(METI.url, how)
        return METI, 15, METI.url
    web.break_(EGC.url, how)
    web.break_(EGC_LOG, how)
    return EGC, 621, EGC.url


@pytest.mark.parametrize("source", ["egc", "meti", "occto"])
@pytest.mark.parametrize("how", ["404", *FETCH_FAILURES])
def test_a_page_that_gives_no_body_is_not_read_and_keeps_its_kind(web, source, how):
    """Any fetch failure is "not read", a 404 included: a page that is not there says nothing about
    what the meeting's documents are."""
    committee, num, page = _break_the_one_page_a_source_needs(web, source, how)

    got = scraper.list_materials_ex(committee, num)

    kind = "not_found" if how == "404" else how
    assert (got.read, got.materials, got.error_kind, got.error_url) == (False, [], kind, page)
    assert page in (got.error_detail or "")  # the detail names the page it is about


def test_list_materials_still_returns_just_the_list(web):
    """Detection, the late-paper refresh and the materials backfill read ``[]`` as "found nothing"
    and are handed a list, exactly as before the verdict was split out."""
    web.ok(OCCTO_PAGE, _links("t_12_01.pdf"))
    assert [m.pdf_id for m in scraper.list_materials(OCCTO, 12)] == ["012_t_12_01"]
    web.gone(OCCTO_PAGE)
    assert scraper.list_materials(OCCTO, 12) == []

    # EGC, handout page down: the row's own PDFs, which is all it ever answered.
    web.ok(EGC.url, _table(_egc_row(621, giji="pdf/621_giji.pdf", haifu="621_haifu.html")))
    web.fail(EGC_BASE + "621_haifu.html", "challenge_unresolved")
    assert [m.pdf_id for m in scraper.list_materials(EGC, 621)] == ["621_621_giji"]
    # …and a row on no page is [].
    web.ok(EGC_LOG, _table(_egc_row(600)))
    assert scraper.list_materials(EGC, 650) == []

    # METI: nothing on its pages, the backup's documents; nothing anywhere, [].
    web.ok(METI.url, _meti_index(15))
    web.gone(METI_PAGE)
    assert scraper.list_materials(METI, 15) == []
    web.board = [Material(15, "015_board", "https://www.meti.go.jp/x/015_board.pdf", "資料", "handout")]
    assert [m.pdf_id for m in scraper.list_materials(METI, 15)] == ["015_board"]
    web.ok(METI_PAGE, _links("015_01.pdf"))
    assert [m.pdf_id for m in scraper.list_materials(METI, 15)] == ["015_015_01"]  # the page wins


# ── summarize_meeting ────────────────────────────────────────────────────────
KEY, NUM = "chousei_jukyu", 130  # an OCCTO committee: one page per meeting
PAGE = f"https://www.occto.or.jp/iinkai/{KEY}/{NUM}.html"


def _held(days: int = 5) -> date:
    return today_jst() - timedelta(days=days)


def _mat(n: int, kind: str) -> Material:
    return Material(n, f"{n:03d}_{kind}", f"https://x/{n}/{kind}.pdf", kind, kind)


def _meeting(db: str, key: str, n: int, kinds=(), **fields) -> int:
    store.record_meeting(key, n, [_mat(n, k) for k in kinds] or None, db_path=db)
    mid = pipeline._meeting_id(key, n, db)
    assert mid is not None
    if fields:
        store.update_meeting(mid, db_path=db, **fields)
    return mid


def _row(db: str, key: str, n: int) -> dict:
    from repower.db import PolicyMeeting

    with store.session_scope(db, commit=False) as session:
        m = session.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=n).one()
        return {"state": m.state, "flag": m.quality_flag, "error": m.last_error,
                "error_at": m.last_error_at, "retries": m.retry_count or 0,
                "checked": m.materials_checked_at, "requested": bool(m.gen_requested),
                "updated_at": m.updated_at}


def _readiness(db: str, key: str, n: int) -> str:
    rows = store.pending_meetings(db_path=db, ready_only=False)
    return next(m["readiness"] for m in rows if m["committee_key"] == key and m["meeting_num"] == n)


def _no_notebook(monkeypatch) -> None:
    monkeypatch.setattr(nb_mod, "create_notebook",
                        lambda *a, **k: pytest.fail("nothing here may reach NotebookLM"))


def _stub_notebooklm(monkeypatch, tmp_path: Path, dead: tuple[str, ...] = ()) -> list[str]:
    """The happy path of summarize_meeting, with NotebookLM faked and downloads of any URL containing
    one of ``dead`` answering 404. Returns the titles of the notebooks created."""
    created: list[str] = []
    monkeypatch.setattr(pipeline, "_scratch", lambda: tmp_path / "scratch")

    def download(url, dest, **kw):
        if any(d in url for d in dead):
            return "not_found"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4")
        return "ok"

    monkeypatch.setattr(pipeline, "_download_pdf", download)
    monkeypatch.setattr(pipeline.nb, "create_notebook", lambda title, **k: created.append(title) or "nb1")
    monkeypatch.setattr(pipeline.nb, "add_source", lambda nb_id, path: f"src:{Path(path).name}")
    monkeypatch.setattr(pipeline.nb, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(pipeline, "_ocr_guard", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.nb, "generate_report", lambda *a, **k: "task1")
    monkeypatch.setattr(pipeline.nb, "wait_artifact", lambda *a, **k: True)

    def download_report(nb_id, task_id, out):
        out.write_text("## 論点\n" + "x" * 500, encoding="utf-8")
        return True

    monkeypatch.setattr(pipeline.nb, "download_report", download_report)
    monkeypatch.setattr(pipeline.nb, "ask", lambda *a, **k: {"answer": "ok"})
    monkeypatch.setattr(pipeline.nb, "delete_notebook", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "regenerate_running_doc", lambda *a, **k: None)
    return created


def _quiet_run(monkeypatch) -> list[str]:
    """Take run()'s auth gate, synthesis and host breaker out of the picture. Returns the committees
    whose synthesis was refreshed (a committee is only touched when something reached NotebookLM)."""
    synthesized: list[str] = []
    monkeypatch.setattr(nb_mod, "require_auth", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "synthesize_committee", lambda c, **k: synthesized.append(c.key) or False)
    monkeypatch.setattr(pipeline, "circuit_cooldown", lambda url: 0.0)
    return synthesized


def test_a_page_read_with_nothing_on_it_records_the_look_and_defers(policy_db, web, monkeypatch):
    """"Nothing posted yet" is a fact worth recording: the gate then rates the meeting awaiting and the
    daily run leaves it alone for a week. No error, no retry, no notebook."""
    db = policy_db
    _meeting(db, KEY, NUM, meeting_date=_held())
    web.ok(PAGE)
    _no_notebook(monkeypatch)

    out = pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db)

    assert out == "deferred"
    row = _row(db, KEY, NUM)
    assert row["checked"] is not None  # the look was recorded
    assert (row["state"], row["flag"], row["error"], row["retries"]) == ("detected", None, None, 0)
    assert _readiness(db, KEY, NUM) == AWAITING
    assert store.pending_meetings(db_path=db) == []  # not offered again until RELIST_DAYS have passed


@pytest.mark.parametrize("how", ["404", "challenge_unresolved", "blocked_403"])
def test_a_page_that_could_not_be_read_flags_the_row_and_spends_nothing(policy_db, web, monkeypatch, how):
    """Not read is not "nothing posted": no look is recorded, so the meeting stays ready and is asked
    again; no retry is spent (it would age the meeting out for the host's mood); a queued request stays."""
    db = policy_db
    _meeting(db, KEY, NUM, meeting_date=_held(), retry_count=1, gen_requested=True)
    web.break_(PAGE, how)
    _no_notebook(monkeypatch)

    out = pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db)

    assert out == "blocked"
    row = _row(db, KEY, NUM)
    assert (row["state"], row["flag"], row["retries"], row["requested"]) == ("error", "listing_blocked", 1, True)
    assert row["checked"] is None
    assert row["error_at"] is not None
    kind = "not_found" if how == "404" else how
    assert f"第{NUM}回" in row["error"] and kind in row["error"] and "will be retried" in row["error"]
    assert PAGE in row["error"]  # says which page, whatever the detail carried
    assert _readiness(db, KEY, NUM) == READY


def test_the_message_names_the_page_even_when_the_error_text_does_not(policy_db, web, monkeypatch):
    """A timeout carries no URL in its text, and the status table is all an operator has."""
    db = policy_db
    _meeting(db, KEY, NUM, meeting_date=_held())
    web.pages[PAGE] = FetchResult("error", None, kind="network_error", detail="ReadTimeout", url=PAGE)
    _no_notebook(monkeypatch)

    assert pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db) == "blocked"

    assert "network_error: ReadTimeout" in _row(db, KEY, NUM)["error"] and PAGE in _row(db, KEY, NUM)["error"]


def test_a_later_successful_read_clears_a_listing_block(policy_db, web, monkeypatch):
    """Otherwise a meeting the read then defers would keep showing a red error for a week."""
    db = policy_db
    _meeting(db, KEY, NUM, meeting_date=_held())
    web.fail(PAGE, "challenge_unresolved")
    _no_notebook(monkeypatch)
    assert pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db) == "blocked"
    store.update_meeting(pipeline._meeting_id(KEY, NUM, db), db_path=db, retry_count=2)  # an earlier real failure

    web.ok(PAGE)  # readable now, and still nothing posted
    assert pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db) == "deferred"

    row = _row(db, KEY, NUM)
    assert (row["state"], row["flag"], row["error"], row["error_at"]) == ("detected", None, None, None)
    assert row["retries"] == 2  # untouched
    assert row["checked"] is not None


def test_a_recorded_look_clears_only_a_listing_block_and_leaves_summarised_meetings_in_state(policy_db):
    """The rule is the store's (``_record_look``), so it holds for whatever stamps the look."""
    db = policy_db
    _meeting(db, KEY, 131, state="error", quality_flag="download_failed", last_error="404", retry_count=2)
    _meeting(db, KEY, 132, state="done", briefing_md="# 要約", quality_flag="listing_blocked",
             last_error="Could not read the committee page")
    summarised_at = _row(db, KEY, 132)["updated_at"]

    store.mark_materials_checked(KEY, 131, db_path=db)
    store.mark_materials_checked(KEY, 132, db_path=db)

    other = _row(db, KEY, 131)  # another failure's flag is not ours to clear, whatever was read
    assert (other["state"], other["flag"], other["error"], other["retries"]) == ("error", "download_failed", "404", 2)
    assert other["checked"] is not None
    upgrade = _row(db, KEY, 132)  # a failed upgrade put back to done: keeps its briefing, state and "summarised" time
    assert (upgrade["state"], upgrade["flag"], upgrade["error"]) == ("done", None, None)
    assert upgrade["updated_at"] == summarised_at


def test_a_late_paper_refresh_that_records_only_an_agenda_clears_a_listing_block(policy_db):
    """``detect``'s refresh stamps a look too (``add_late_materials``, when it finds documents), so
    the rule cannot live in the pipeline: an agenda alone leaves the meeting ``awaiting``, and the
    error that said the page could not be read would otherwise stay up until the next re-check."""
    db = policy_db
    _meeting(db, KEY, NUM, meeting_date=_held(), state="error", quality_flag="listing_blocked",
             last_error="Could not read the committee page for 第130回 (not_found: 404) — will be retried",
             retry_count=1)
    assert _readiness(db, KEY, NUM) == READY

    got = store.add_late_materials(KEY, NUM, [_mat(NUM, "agenda")], db_path=db)

    assert got == {"added": 1, "requeued": False}
    row = _row(db, KEY, NUM)
    assert (row["state"], row["flag"], row["error"], row["error_at"], row["retries"]) == (
        "detected", None, None, None, 1)
    assert _readiness(db, KEY, NUM) == AWAITING  # read, and an agenda is all there is


def test_a_requested_meeting_that_reads_empty_still_fails_no_sources_as_unsent(policy_db, web, monkeypatch):
    """A request bypasses the gate, so an honest "nothing to read" is an error. It never got as far as
    NotebookLM, so it is 'unsent': errored, but the run charges it no slot."""
    db = policy_db
    _meeting(db, KEY, NUM, meeting_date=_held(), gen_requested=True)
    web.ok(PAGE)
    _no_notebook(monkeypatch)

    out = pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db)

    assert out == "unsent"
    row = _row(db, KEY, NUM)
    assert (row["state"], row["flag"], row["retries"]) == ("error", "no_sources", 0)
    assert "lists 0 material(s)" in row["error"]
    assert row["checked"] is not None  # the page was read, so that is recorded too


def test_a_partial_egc_listing_is_not_recorded(policy_db, web, monkeypatch):
    """The row's own PDFs came back but the handouts it links did not. Recording those would put a
    paper on file, and the next run — seeing one — would skip the read and summarise from a partial set."""
    db = policy_db
    committee = committee_by_key("emsc_system")
    _meeting(db, "emsc_system", 621, meeting_date=_held())
    haifu = EGC_BASE + "621_haifu.html"
    web.ok(committee.url, _table(_egc_row(621, giji="pdf/621_giji.pdf", haifu="621_haifu.html")))
    web.fail(haifu, "challenge_unresolved")
    _no_notebook(monkeypatch)

    assert pipeline.summarize_meeting(committee, 621, db_path=db) == "blocked"
    assert store.meeting_materials("emsc_system", 621, db_path=db) == []
    assert _row(db, "emsc_system", 621)["flag"] == "listing_blocked"

    # The next run finds the handout page readable and gets the whole list.
    web.ok(haifu, _links("pdf/621_01.pdf"))
    monkeypatch.setattr(pipeline, "_download_pdf", lambda *a, **k: "not_found")  # stops short of NotebookLM
    assert pipeline.summarize_meeting(committee, 621, db_path=db) == "unsent"
    assert {m["pdf_id"] for m in store.meeting_materials("emsc_system", 621, db_path=db)} == {
        "621_621_giji", "621_621_01"}


def test_an_unread_meeting_is_summarised_once_its_page_can_be_read(policy_db, web, monkeypatch, tmp_path):
    db = policy_db
    _meeting(db, KEY, NUM, meeting_date=_held())
    created = _stub_notebooklm(monkeypatch, tmp_path)
    web.fail(PAGE, "challenge_unresolved")

    assert pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db) == "blocked"
    assert created == []

    web.ok(PAGE, _links("chousei_130_01.pdf"))  # readable now, and a paper is up
    assert pipeline.summarize_meeting(committee_by_key(KEY), NUM, db_path=db) == "done"

    row = _row(db, KEY, NUM)
    assert (row["state"], row["flag"], row["error"]) == ("done", None, None)
    assert len(created) == 1


# ── run(): slots, requests, bounds ───────────────────────────────────────────
def test_meetings_that_fail_before_notebooklm_cost_no_slot_and_spend_their_requests(
        policy_db, web, monkeypatch, tmp_path):
    """A requested meeting with nothing posted (no_sources) and one whose documents 404 are errored
    and have their requests cleared, but nothing reached NotebookLM for either: with one slot a day
    the ready meeting behind them still runs, and only it refreshes a committee's synthesis."""
    db = policy_db
    synthesized = _quiet_run(monkeypatch)
    created = _stub_notebooklm(monkeypatch, tmp_path, dead=("dead",))
    _meeting(db, KEY, NUM, meeting_date=_held(), gen_requested=True)
    web.ok(PAGE)  # read, and nothing posted
    store.record_meeting("doji_shijo", 11, [Material(11, "011_dead", "https://x/dead.pdf", "資料", "handout")],
                         db_path=db)
    store.update_meeting(pipeline._meeting_id("doji_shijo", 11, db), db_path=db,
                         meeting_date=_held(), gen_requested=True)
    _meeting(db, "santeii", 5, kinds=("handout",), meeting_date=_held())

    out = pipeline.run(max_per_run=1, breadth_first=True, db_path=db)

    assert (out["done"], out["errored"], out["blocked"], out["processed"]) == (1, 2, 0, 3)
    assert out["unsent"] == 2  # both of the errored ones never reached NotebookLM
    assert len(created) == 1 and _row(db, "santeii", 5)["state"] == "done"
    assert synthesized == ["santeii"]  # the other two changed nothing in NotebookLM
    nothing = _row(db, KEY, NUM)
    assert (nothing["state"], nothing["flag"], nothing["retries"], nothing["requested"]) == (
        "error", "no_sources", 0, False)
    dead = _row(db, "doji_shijo", 11)  # a document that is gone still spends its retry
    assert (dead["state"], dead["flag"], dead["retries"], dead["requested"]) == ("error", "download_failed", 1, False)
    # Every key a caller read before is still there, with the same meaning.
    assert set(out) >= {"processed", "done", "errored", "blocked", "deferred", "synthesized", "skipped",
                        "skipped_hosts", "rate_limited", "stopped_early", "unsent"}


def test_a_round_stops_after_the_unsent_bound(policy_db, monkeypatch, tmp_path, caplog):
    """A bad day (documents everywhere 404) must not walk the worklist downloading dead links."""
    db = policy_db
    _quiet_run(monkeypatch)
    _stub_notebooklm(monkeypatch, tmp_path, dead=("handout",))
    monkeypatch.setattr(pipeline, "_MAX_UNSENT_ATTEMPTS", 3)
    for n in range(1, 11):
        _meeting(db, "doji_shijo", n, kinds=("handout",), meeting_date=_held(n + 3))

    with caplog.at_level(logging.WARNING, logger=pipeline.logger.name):
        out = pipeline.run(["doji_shijo"], max_per_run=8, db_path=db)

    assert (out["unsent"], out["errored"], out["processed"], out["done"]) == (3, 3, 3, 0)
    assert "stopping this round early" in caplog.text
    tried = [n for n in range(1, 11) if _row(db, "doji_shijo", n)["state"] == "error"]
    assert tried == [8, 9, 10]  # the newest three; the rest were never touched
    assert all(_row(db, "doji_shijo", n)["retries"] == 0 for n in range(1, 8))


def test_a_blocked_listing_keeps_its_request_and_counts_toward_the_blocked_bound(policy_db, web, monkeypatch):
    db = policy_db
    _quiet_run(monkeypatch)
    monkeypatch.setattr(pipeline, "_MAX_BLOCKED_ATTEMPTS", 2)
    for n in range(130, 135):
        _meeting(db, KEY, n, meeting_date=_held(), gen_requested=True)
        web.gone(f"https://www.occto.or.jp/iinkai/{KEY}/{n}.html")

    out = pipeline.run([KEY], max_per_run=8, db_path=db)

    assert (out["blocked"], out["errored"], out["done"], out["processed"]) == (2, 0, 0, 2)
    assert out["unsent"] == 0
    for n in (134, 133):  # newest first
        row = _row(db, KEY, n)
        assert (row["state"], row["flag"], row["retries"], row["requested"]) == (
            "error", "listing_blocked", 0, True)
    assert _row(db, KEY, 132)["state"] == "detected"  # past the bound: never asked


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now


def test_empty_pages_cost_no_slot_and_are_not_offered_again_for_a_week(policy_db, web, monkeypatch, tmp_path):
    """One slot a day, four meetings, nine days. An EGC row with no ※ remark and no links yet and a METI
    page with no papers were *read*: free, deferred, and not asked about again until RELIST_DAYS have
    passed. An OCCTO page that 404s was *not* read: free, flagged, and asked about every run. Ahead of all
    three in the queue, none of them may take the one slot the ready meeting needs."""
    db = policy_db
    clock = _Clock(datetime(2026, 11, 2, 0, 30, tzinfo=UTC))  # 09:30 JST
    monkeypatch.setattr(store, "_now", lambda: clock.now)
    monkeypatch.setattr(store, "today_jst", lambda: clock.now.astimezone(JST).date())
    _quiet_run(monkeypatch)
    created = _stub_notebooklm(monkeypatch, tmp_path)

    # Queue order is by priority, so the ready meeting is last behind the three that cannot run.
    for key, priority in (("emsc_system", 10), ("saisei_kano", 20), ("chousei_jukyu", 30), ("santeii", 90)):
        store.update_committee(key, db_path=db, priority=priority)
    held = date(2026, 10, 20)
    _meeting(db, "emsc_system", 621, meeting_date=held)
    _meeting(db, "saisei_kano", 99, meeting_date=held)
    _meeting(db, KEY, NUM, meeting_date=held)
    _meeting(db, "santeii", 5, kinds=("handout",), meeting_date=held)
    egc_index = committee_by_key("emsc_system").url
    meti_index = committee_by_key("saisei_kano").url
    meti_page = meti_index + "099.html"
    web.ok(egc_index, _table(_egc_row(621)))  # the row is there; it links nothing and carries no ※
    web.ok(meti_index, _meti_index(99))
    web.ok(meti_page, _links())
    web.gone(PAGE)

    everything = [egc_index, meti_index, meti_page, PAGE]
    for day in range(1, 10):
        web.requests.clear()
        out = pipeline.run(max_per_run=1, breadth_first=True, db_path=db)

        # Looked at on the first day and again once a week has passed; the 404 every day.
        assert web.requests == (everything if day in (1, 8) else [PAGE]), f"day {day}"
        assert (out["deferred"], out["blocked"], out["errored"], out["unsent"]) == (
            2 if day in (1, 8) else 0, 1, 0, 0), f"day {day}"
        assert out["done"] == (1 if day == 1 else 0), f"day {day}"
        assert out["processed"] == (2 if day == 1 else 1), f"day {day}"
        clock.now += timedelta(days=1)

    assert _row(db, "santeii", 5)["state"] == "done"  # day 1, with its one slot
    assert len(created) == 1  # and NotebookLM was never reached again
    for key, n in (("emsc_system", 621), ("saisei_kano", 99)):
        row = _row(db, key, n)
        assert (row["state"], row["flag"], row["error"], row["retries"]) == ("detected", None, None, 0)
        assert row["checked"] is not None
    blocked = _row(db, KEY, NUM)
    assert (blocked["state"], blocked["flag"], blocked["retries"], blocked["checked"]) == (
        "error", "listing_blocked", 0, None)


# ── What the readers see ─────────────────────────────────────────────────────
def test_the_export_says_in_words_why_a_listing_was_blocked(policy_db):
    db = policy_db
    _meeting(db, "santeii", 7, meeting_date=_held(), state="error", quality_flag="listing_blocked",
             last_error="Could not read the committee page for 第7回 (not_found: 404 for https://x) — will be retried")

    card = next(m for m in build_policy_snapshot(db)["meetings"] if m["com"] == "santeii" and m["num"] == 7)
    assert card["status"] == "error"
    assert "the committee page could not be read — will be retried" in card["emptySub"]
    assert "委員会ページを読めませんでした（再試行されます）" in card["emptySub"]

    status = next(m for m in build_policy_status(db)["meetings"] if m["com"] == "santeii" and m["num"] == 7)
    assert status["flag"] == "listing_blocked" and "404" in status["error"]
    # The public export drops the raw text and lets the flag speak for it (the web app words it).
    assert _public_error(status["error"], status["flag"]) is None
