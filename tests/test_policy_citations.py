"""Citation deep-links: finding the document + page behind a NotebookLM citation.

The locator is pure and tested on synthetic page texts; the PDF layer on tiny generated
PDFs; the resolver with the network faked (``_download_pdf`` writes a generated PDF
instead of fetching), so nothing here touches meti.go.jp.
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from repower.dashboard.export_web import build_cites, build_policy_snapshot, meeting_cites
from repower.policy import citation_resolver, citations, pipeline, store
from repower.policy.citations import Doc, locate, normalize, resolve_refs
from repower.policy.scraper import Material
from repower.web_api import _Handler

pymupdf = pytest.importorskip("pymupdf")

# Distinct, same-length-ish "slides": each has its own sentence plus a footer that is on every page.
FOOTER = "第２回再生可能エネルギー主力電源化小委員会資料より抜粋"


def _pages(*bodies: str) -> list[str]:
    return [normalize(b + " " + FOOTER) for b in bodies]


BODY = [
    "太陽光発電の支援重点化について、地上設置の事業用太陽光は二〇二七年度以降新規支援の対象外とする方針",
    "地域共生が図られた形での屋根設置太陽光の導入促進について、類型の検討を小委員会で行うこととする",
    "洋上風力の入札上限価格の設定方法について、事務局から三つの案が示され委員から意見が出された",
    "容量市場の約定結果を踏まえた制度見直しの論点として、供給力確保と国民負担の両立が挙げられた",
]


# ── locate: pure ──────────────────────────────────────────────────────────────
def test_locate_finds_the_page_holding_the_passage():
    pages = _pages(*BODY)
    loc = locate(BODY[2], pages)
    assert (loc.page, loc.page_end) == (3, 3)


def test_boilerplate_on_every_page_does_not_move_the_answer():
    """A footer shared by all pages gives every page the same shingles — it must not win ties."""
    pages = _pages(*BODY)
    passage = BODY[3] + " " + FOOTER  # the cited chunk happens to include the footer too
    assert locate(passage, pages).page == 4


def test_whitespace_and_width_differences_are_ignored():
    pages = _pages(*BODY)
    # NotebookLM puts spaces where the PDF has line breaks, and full-width digits survive NFKC.
    spaced = " ".join(BODY[1][i:i + 7] for i in range(0, len(BODY[1]), 7))
    assert locate(spaced, pages).page == 2
    assert normalize("ＡＢＣ　１２３\n ４") == "ABC1234"


def test_a_chunk_straddling_a_page_break_becomes_a_range():
    pages = _pages(BODY[0] + " " + BODY[1][:30], BODY[1][30:] + " " + BODY[2], BODY[3])
    straddling = BODY[0][-40:] + BODY[1][:30] + BODY[1][30:] + BODY[2][:40]
    loc = locate(straddling, pages)
    assert (loc.page, loc.page_end) == (1, 2)


def test_an_unlocatable_passage_has_no_page_rather_than_a_guess():
    pages = _pages(*BODY)
    assert locate("まったく別の文書にしか書かれていない内容についての記述がここに入ります", pages) is None
    assert locate("", pages) is None
    assert locate(BODY[0], []) is None
    assert locate(BODY[0], ["", ""]) is None  # a scanned PDF: pages with no text layer


def test_short_passages_are_trusted_only_when_unambiguous():
    pages = _pages(*BODY)
    assert locate("洋上風力の入札上限価格", pages).page == 3
    assert locate("再生可能エネルギー主力電源化", pages) is None  # the footer: on every page


def test_a_fragment_too_short_to_identify_anything_gets_no_link():
    # Seen for real: a citation whose whole text was "4" matched the one-page agenda uniquely —
    # trivially, since a single page holds it exactly once — and was attributed to it.
    assert locate("4", _pages("議事次第 4 その他")) is None
    assert locate("・", _pages(*BODY)) is None


def test_a_repeated_passage_is_attributed_to_its_first_page():
    pages = _pages(BODY[0], BODY[0], BODY[1])
    assert locate(BODY[0], pages).page == 1


# ── resolve_refs ───────────────────────────────────────────────────────────────
def _doc(url: str, bodies: list[str], source_id: str | None = None) -> Doc:
    d = Doc(url=url, title=url, source_id=source_id)
    d._pages = _pages(*bodies)  # bypass the PDF reader: this layer is about attribution
    return d


def _ref(n: int, text: str, source_id: str | None = None) -> dict:
    return {"citation_number": n, "cited_text": text, "source_id": source_id}


def test_a_known_source_id_attributes_the_document_even_when_the_page_is_not_found():
    docs = [_doc("https://x/a.pdf", BODY[:2], "sid-a"), _doc("https://x/b.pdf", BODY[2:], "sid-b")]
    nowhere = "どこにも書かれていない長い文章がここにあります、本当に"
    items = resolve_refs([_ref(1, BODY[3], "sid-b"), _ref(2, nowhere, "sid-a")], docs)
    assert items[0] == {"n": 1, "url": "https://x/b.pdf", "doc": "https://x/b.pdf", "page": 2}
    assert items[1] == {"n": 2, "url": "https://x/a.pdf", "doc": "https://x/a.pdf"}  # doc known, page not


def test_without_a_source_id_the_text_picks_the_document():
    docs = [_doc("https://x/a.pdf", BODY[:2]), _doc("https://x/b.pdf", BODY[2:])]
    items = resolve_refs([_ref(1, BODY[0]), _ref(2, BODY[2])], docs)
    assert [(i["url"], i["page"]) for i in items] == [("https://x/a.pdf", 1), ("https://x/b.pdf", 1)]


def test_a_short_passage_found_in_two_documents_is_not_attributed_to_either():
    heading = "洋上風力の入札上限価格"  # short, and printed in both documents
    docs = [_doc("https://x/a.pdf", [heading, BODY[0]]), _doc("https://x/b.pdf", [BODY[1], heading])]
    assert resolve_refs([_ref(1, heading)], docs) == []
    # ...but the same passage with a source id is attributed, since the document is known.
    docs[0].source_id = "sid-a"
    assert resolve_refs([_ref(1, heading, "sid-a")], docs)[0]["url"] == "https://x/a.pdf"


def test_a_reference_found_nowhere_is_left_out_not_misattributed():
    docs = [_doc("https://x/a.pdf", BODY[:2])]
    assert resolve_refs([_ref(1, "どの資料にも載っていない文章がここに長めに入ります、ご確認ください")], docs) == []
    assert resolve_refs([{"cited_text": BODY[0]}], docs) == []  # no citation number: nothing to key a chip on


# ── PDF text extraction ──────────────────────────────────────────────────────────
def _make_pdf(path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


EN = [
    "Solar support will be refocused: ground-mounted commercial solar leaves the FIT scheme after FY2027.",
    "Offshore wind: the Secretariat proposed three options for the ceiling price of the fourth auction.",
    "Capacity market: balancing security of supply against the burden placed on consumers.",
]


def test_pdf_page_texts_are_one_normalised_string_per_page(tmp_path):
    texts = citations.pdf_page_texts(_make_pdf(tmp_path / "a.pdf", EN))
    assert len(texts) == 3
    assert texts[1].startswith("Offshorewind:")
    assert " " not in texts[0]


def test_a_real_pdf_resolves_end_to_end(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", EN)
    doc = Doc(url="https://x/a.pdf", title="資料1　テスト（PDF形式：10KB）", path=pdf, source_id="sid")
    items = resolve_refs([_ref(1, "the Secretariat proposed three options for the ceiling price", "sid")], [doc])
    assert items == [{"n": 1, "url": "https://x/a.pdf", "doc": doc.title, "page": 2}]


# ── persistence ────────────────────────────────────────────────────────────────
def test_dump_and_load_round_trip_and_tolerate_garbage():
    items = [{"n": 3, "url": "https://x/a.pdf", "doc": "資料1", "page": 4, "pageEnd": 5}]
    assert citations.load_items(citations.dump(items, "2026-10-03T00:00:00+00:00"))[3]["pageEnd"] == 5
    assert citations.load_items(None) == {}
    assert citations.load_items("not json") == {}
    assert citations.load_items('{"items": [{"no_n": 1}]}') == {}


def _seed(tmp_path, *, refs: list[dict], source_ids: dict[str, str | None] | None = None) -> str:
    """A done meeting (emissions_trading 第5回) with a digest citing *refs* and three PDFs."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.record_meeting(
        "emissions_trading", 5,
        [Material(5, "005_01", "https://www.meti.go.jp/a/005_01.pdf", "資料1　太陽光（PDF形式：10KB）", "handout"),
         Material(5, "005_02", "https://www.meti.go.jp/a/005_02.pdf", "資料2　洋上風力（PDF形式：10KB）", "handout"),
         Material(5, "005_03", "https://www.meti.go.jp/a/005_03.pdf", "資料3　容量市場（PDF形式：10KB）", "handout")],
        db_path=db,
    )
    for pdf_id, sid in (source_ids or {}).items():
        store.set_material_state("emissions_trading", pdf_id, db_path=db, nblm_source_id=sid)
    row = store.pending_meetings("emissions_trading", db_path=db)[0]["id"]
    store.update_meeting(row, db_path=db, state="done", briefing_md="## 論点\n概要。",
                         digest_en_json=json.dumps({"answer": "Lead [1].", "references": refs}))
    return db


PDF_TEXT = {
    "005_01": [EN[0], "Slide two: the second page of document one, about rooftop solar."],
    "005_02": [EN[1]],
    "005_03": [EN[2]],
}


def _stage(dest: Path) -> str:
    """What a successful download leaves behind: the material's generated PDF at *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(dest, PDF_TEXT[dest.stem])
    return "ok"


@pytest.fixture
def fake_download(monkeypatch):
    calls: list[str] = []

    def download(url, dest, *, db_path=None, timeout=180.0):
        calls.append(url)
        return _stage(dest)

    monkeypatch.setattr(citation_resolver, "_download_pdf", download)
    return calls


@pytest.fixture(autouse=True)
def _cache_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(citation_resolver, "POLICY_DIR", tmp_path / "policy")


def test_resolve_meeting_by_text_when_no_source_ids_are_known(tmp_path, fake_download):
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "gone-1"),
            _ref(2, "Slide two: the second page of document one, about rooftop solar.", "gone-2")]
    db = _seed(tmp_path, refs=refs)  # a legacy digest: no material carries a source id
    res = citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db)
    assert res == {"status": "resolved", "items": 2, "pages": 2, "refs": 2}
    cites = {c["n"]: c for c in meeting_cites("emissions_trading", 5, db_path=db)}
    assert (cites[1]["doc"], cites[1]["page"]) == ("資料2", 1)
    assert (cites[2]["doc"], cites[2]["page"]) == ("資料1", 2)
    assert len(fake_download) == 3  # nothing to narrow it down: every selected document was read


def test_known_source_ids_fetch_only_the_cited_documents(tmp_path, fake_download):
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "sid-2")]
    db = _seed(tmp_path, refs=refs, source_ids={"005_01": "sid-1", "005_02": "sid-2", "005_03": "sid-3"})
    res = citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db)
    assert res["status"] == "resolved"
    assert fake_download == ["https://www.meti.go.jp/a/005_02.pdf"]


def test_a_second_resolution_reuses_the_cached_pdfs(tmp_path, fake_download):
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "sid-2")]
    db = _seed(tmp_path, refs=refs, source_ids={"005_02": "sid-2"})
    citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db)
    citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db)
    assert len(fake_download) == 1


def test_a_sweep_does_not_keep_the_pdfs(tmp_path, fake_download):
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "sid-2")]
    db = _seed(tmp_path, refs=refs, source_ids={"005_02": "sid-2"})
    citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db, keep_pdfs=False)
    assert not citation_resolver.pdf_cache_dir("emissions_trading", 5).exists()


def test_a_blocked_host_stores_nothing_and_stops_asking(tmp_path, monkeypatch):
    seen: list[str] = []

    def download(url, dest, *, db_path=None, timeout=180.0):
        seen.append(url)
        return "challenge_unresolved"

    monkeypatch.setattr(citation_resolver, "_download_pdf", download)
    db = _seed(tmp_path, refs=[_ref(1, "anything at all, long enough to matter here", "x")])
    res = citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db)
    assert res["status"] == "blocked"
    assert len(seen) == 1  # abandoned at the first hostile answer, not one strike per document
    assert store.meetings_missing_citations(db) == [("emissions_trading", 5)]  # still on the worklist


def test_a_permanently_missing_document_does_not_pin_the_meeting(tmp_path, monkeypatch):
    def download(url, dest, *, db_path=None, timeout=180.0):
        return "not_found" if url.endswith("005_01.pdf") else _stage(dest)

    monkeypatch.setattr(citation_resolver, "_download_pdf", download)
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price")]
    db = _seed(tmp_path, refs=refs)
    res = citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db)
    assert res["status"] == "resolved" and res["pages"] == 1
    assert store.meetings_missing_citations(db) == []  # off the worklist, so the sweep moves on


def test_resolving_does_not_make_an_old_meeting_look_newly_summarised(tmp_path, fake_download):
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "sid-2")]
    db = _seed(tmp_path, refs=refs, source_ids={"005_02": "sid-2"})
    before = build_policy_snapshot(db)["meetings"][0]["updatedAt"]
    citation_resolver.resolve_meeting("emissions_trading", 5, db_path=db)
    assert build_policy_snapshot(db)["meetings"][0]["updatedAt"] == before


def test_backfill_is_resumable_and_reports_why_it_stopped(tmp_path, fake_download):
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "sid-2")]
    db = _seed(tmp_path, refs=refs, source_ids={"005_02": "sid-2"})
    first = citation_resolver.backfill(db, max_meetings=5)
    assert (first["resolved"], first["pending"], first["stopped_early"]) == (1, 1, None)
    assert citation_resolver.backfill(db, max_meetings=5)["pending"] == 0


def test_backfill_stops_when_the_host_budget_is_spent(tmp_path, fake_download, monkeypatch):
    db = _seed(tmp_path, refs=[_ref(1, "x" * 30)])
    monkeypatch.setattr(citation_resolver, "budget_exhausted", lambda url: True)
    res = citation_resolver.backfill(db)
    assert res["stopped_early"] == "budget_exhausted" and res["attempted"] == 0 and fake_download == []


# ── export shape ───────────────────────────────────────────────────────────────
def test_build_cites_carries_document_and_page_and_skips_empty_text():
    refs = [_ref(1, "  a cited\n passage  "), _ref(2, ""), _ref(3, "x" * 400), _ref(4, "unresolved text")]
    stored = citations.dump([
        {"n": 1, "url": "https://x/a.pdf", "doc": "資料3　再エネ（PDF形式：1,272KB）", "page": 6, "pageEnd": 7},
        {"n": 3, "url": "javascript:alert(1)", "doc": "資料9", "page": 2},
    ], "t")
    cites = {c["n"]: c for c in build_cites(refs, stored)}
    assert set(cites) == {1, 3, 4}  # the empty citation is dropped
    assert cites[1] == {"n": 1, "text": "a cited passage", "url": "https://x/a.pdf", "doc": "資料3",
                        "page": 6, "pageEnd": 7}
    assert "url" not in cites[3] and len(cites[3]["text"]) == 241  # a non-http(s) link is never exported
    assert cites[4] == {"n": 4, "text": "unresolved text"}


def test_snapshot_meetings_carry_cites(tmp_path):
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "sid-2")]
    db = _seed(tmp_path, refs=refs)
    store.set_meeting_citations(
        "emissions_trading", 5,
        citations.dump([{"n": 1, "url": "https://www.meti.go.jp/a/005_02.pdf", "doc": "資料2", "page": 1}], "t"),
        db_path=db,
    )
    m = build_policy_snapshot(db)["meetings"][0]
    assert m["cites"][0]["page"] == 1 and m["cites"][0]["doc"] == "資料2"
    assert m["refs"][0].startswith("[1]")  # the string form stays for an older web build


# ── pipeline hook ──────────────────────────────────────────────────────────────
def test_ingest_time_resolution_is_best_effort(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", EN)
    digest = json.dumps({"references": [_ref(1, "the Secretariat proposed three options for the ceiling price", "s")]})
    out = pipeline._resolve_citations_json(digest, [Doc("https://x/a.pdf", "資料1", pdf, "s")])
    assert citations.load_items(out)[1]["page"] == 2
    assert pipeline._resolve_citations_json(None, []) is None
    assert pipeline._resolve_citations_json("{not json", []) is None  # logged, left for the sweep
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 truncated")
    assert pipeline._resolve_citations_json(digest, [Doc("https://x/b.pdf", "資料2", broken, "s")]) is None


# ── local API ──────────────────────────────────────────────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv("REPOWER_API_TOKEN", raising=False)
    refs = [_ref(1, "the Secretariat proposed three options for the ceiling price", "sid-2")]
    db = _seed(tmp_path, refs=refs, source_ids={"005_02": "sid-2"})
    monkeypatch.setattr(_Handler, "db_path", db)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def post(body: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=20)
        conn.request("POST", "/api/policy/citations/resolve", json.dumps(body))
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return resp.status, data

    yield post
    httpd.shutdown()
    httpd.server_close()


def test_api_resolves_a_meeting_and_returns_its_chips(api, fake_download):
    status, body = api({"com": "emissions_trading", "num": 5})
    assert status == 200 and body["ok"] is True
    assert body["cites"][0]["page"] == 1 and body["cites"][0]["url"].endswith("005_02.pdf")


def test_api_reports_a_blocked_host_without_pretending(api, monkeypatch):
    monkeypatch.setattr(citation_resolver, "_download_pdf", lambda *a, **k: "blocked_403")
    status, body = api({"com": "emissions_trading", "num": 5})
    assert status == 200 and body["ok"] is False and body["status"] == "blocked" and "cites" not in body


def test_api_validates_its_input(api):
    assert api({"com": "emissions_trading", "num": "x"})[0] == 400
    assert api({"num": 5})[0] == 400
    assert api({"com": "emissions_trading", "num": 99})[0] == 404
