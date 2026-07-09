"""Tests for the energy-board.xvps.jp backup + cross-check integration.

Network-free: `parse_feed` runs on an inline fixture; the backup/cross-check and
the scraper fallback monkeypatch the networked fetchers.
"""

from __future__ import annotations

import datetime

from repower.policy import energy_board as eb
from repower.policy import scraper, store
from repower.policy.committees import committee_by_key

# A 2-row energy-board feed: one committee we track (doji_shijo) + one we don't
# (水素保安小委員会 under sankoshin/hoan_shohi/hydrogen).
FEED_HTML = """
<table><tbody>
<tr>
  <td class="date-col" data-label="開催日">2026-07-08</td>
  <td class="council-col"><span class="council-link" onclick="selectCouncil('同時市場の在り方等に関する検討会')">同時市場の在り方等に関する検討会</span></td>
  <td class="meeting-content">
    <div class="meeting-title"><a href="https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/012.html" target="_blank">第12回 同時市場の在り方等に関する検討会</a> <span class="badge-new">NEW</span></div>
    <ol class="doc-list">
      <li><a class="doc-link" href="https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/pdf/012_00_00.pdf">議事次第</a></li>
      <li><a class="doc-link" href="https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/pdf/012_03_00.pdf">資料3 論点</a></li>
    </ol>
  </td>
</tr>
<tr>
  <td class="date-col">2026-07-05</td>
  <td class="council-col"><span class="council-link">水素保安小委員会</span></td>
  <td class="meeting-content">
    <div class="meeting-title"><a href="https://www.meti.go.jp/shingikai/sankoshin/hoan_shohi/hydrogen/009.html">第9回 水素保安小委員会</a></div>
    <ol class="doc-list"><li><a class="doc-link" href="https://www.meti.go.jp/shingikai/sankoshin/hoan_shohi/hydrogen/pdf/009_01_00.pdf">資料1</a></li></ol>
  </td>
</tr>
</tbody></table>
"""


def test_parse_feed_extracts_dir_num_date_pdfs():
    entries = eb.parse_feed(FEED_HTML)
    assert len(entries) == 2
    e = entries[0]
    assert e.meti_dir == "energy_environment/doji_shijo_kento"
    assert e.meeting_num == 12
    assert e.date == datetime.date(2026, 7, 8)
    assert [p["url"].rsplit("/", 1)[-1] for p in e.pdfs] == ["012_00_00.pdf", "012_03_00.pdf"]
    assert entries[1].meti_dir == "sankoshin/hoan_shohi/hydrogen"
    assert entries[1].meeting_num == 9


def test_recent_meeting_nums_and_materials(monkeypatch):
    entries = eb.parse_feed(FEED_HTML)
    monkeypatch.setattr(eb, "fetch_feed", lambda **kw: entries)
    doji = committee_by_key("doji_shijo")  # METI committee we track
    assert eb.recent_meeting_nums(doji) == [12]
    mats = eb.materials_for(doji, 12)
    assert [m.url.rsplit("/", 1)[-1] for m in mats] == ["012_00_00.pdf", "012_03_00.pdf"]
    # a non-METI committee isn't on the aggregator
    occto = committee_by_key("chousei_jukyu")
    assert eb.recent_meeting_nums(occto) == []


def test_cross_check_flags_untracked(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)  # doji_shijo is a tracked config committee
    monkeypatch.setattr(eb, "fetch_feed", lambda **kw: eb.parse_feed(FEED_HTML))
    res = eb.cross_check(db_path=db)
    assert res["theirs"] == 2
    assert res["matched"] == 1  # doji_shijo is in our catalog
    dirs = [m["dir"] for m in res["missing"]]
    assert dirs == ["sankoshin/hoan_shohi/hydrogen"]  # the one we don't track


def test_cross_check_persists_missing_as_discovered(monkeypatch, tmp_path):
    """A committee energy-board surfaces that we don't track is accumulated into the
    catalog as a discovered / untracked METI row, so it reaches the Manage modal and
    committees.json — the fix for crosscheck findings vanishing instead of sticking."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)  # doji_shijo tracked; hydrogen not known
    monkeypatch.setattr(eb, "fetch_feed", lambda **kw: eb.parse_feed(FEED_HTML))

    res = eb.cross_check(db_path=db)
    assert res["added"] == 1  # hydrogen accumulated
    cat = {c["key"]: c for c in store.list_committees(db_path=db)}
    assert "hydrogen" in cat
    assert cat["hydrogen"]["enabled"] is False  # discovered → visible but not tracked
    assert cat["hydrogen"]["source"] == "METI"
    assert cat["hydrogen"]["url"] == "https://www.meti.go.jp/shingikai/sankoshin/hoan_shohi/hydrogen/"

    # Idempotent + accumulating: a second run finds it already in the catalog, so it
    # counts as matched and nothing new is added (no duplicate rows).
    res2 = eb.cross_check(db_path=db)
    assert res2["added"] == 0
    assert res2["matched"] == 2 and res2["missing"] == []


def test_cross_check_persist_false_is_pure(monkeypatch, tmp_path):
    """persist=False keeps cross_check a read-only diff (no rows written)."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    monkeypatch.setattr(eb, "fetch_feed", lambda **kw: eb.parse_feed(FEED_HTML))
    before = len(store.list_committees(db_path=db))
    res = eb.cross_check(db_path=db, persist=False)
    assert res["added"] == 0
    assert [m["dir"] for m in res["missing"]] == ["sankoshin/hoan_shohi/hydrogen"]
    assert len(store.list_committees(db_path=db)) == before  # nothing written


def test_scraper_falls_back_to_energy_board_on_meti_failure(monkeypatch):
    entries = eb.parse_feed(FEED_HTML)
    monkeypatch.setattr(eb, "fetch_feed", lambda **kw: entries)
    # Simulate the direct METI fetch failing.
    monkeypatch.setattr(scraper, "_fetch", lambda *a, **k: ("error", None))
    doji = committee_by_key("doji_shijo")
    disc = scraper.discover_meetings(doji)
    assert disc.status == "ok" and disc.meeting_nums == [12]  # recovered via backup
    mats = scraper.list_materials(doji, 12)
    assert {m.url.rsplit("/", 1)[-1] for m in mats} == {"012_00_00.pdf", "012_03_00.pdf"}
