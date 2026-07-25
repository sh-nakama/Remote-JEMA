"""Tests for the upcoming-committees feature: meeting-date extraction, the
forward-schedule scraper (METI committee calendar), committee matching, and
the ``policy_meeting.meeting_date`` / ``policy_upcoming`` store helpers.

Network-free: parse functions run on inline HTML fixtures; DB helpers use a
temporary SQLite path; ``backfill_dates`` mocks the networked fetchers.
"""

from __future__ import annotations

import datetime

from repower.policy import detect as detect_mod
from repower.policy import schedule as sched
from repower.policy import store
from repower.policy.scraper import (
    parse_egc_meeting_dates,
    parse_jp_date,
    parse_meti_meeting_dates,
    parse_page_date,
)


# ── Meeting-date parsing (no network) ─────────────────────────────────────────
def test_parse_jp_date_gregorian_and_eras():
    assert parse_jp_date("2026年5月8日　第114回") == datetime.date(2026, 5, 8)
    assert parse_jp_date("令和6年8月27日 第100回") == datetime.date(2024, 8, 27)
    assert parse_jp_date("令和元年5月1日") == datetime.date(2019, 5, 1)
    assert parse_jp_date("平成31年4月30日") == datetime.date(2019, 4, 30)
    assert parse_jp_date("2026/6/22") == datetime.date(2026, 6, 22)
    # era form wins even when a stray year digit appears
    assert parse_jp_date("開催 令和7年1月9日 (2024年度)") == datetime.date(2025, 1, 9)


def test_parse_jp_date_rejects_garbage():
    assert parse_jp_date("no date here") is None
    assert parse_jp_date("2026年13月40日") is None  # out of range
    assert parse_jp_date(None) is None
    assert parse_jp_date("令和0年3月3日") is None  # era years start at 1/元


METI_DATE_INDEX = """
<html><body><ul>
  <li>2026年5月8日　第114回 <a href="114.html">議事次第</a></li>
  <li>2026年4月3日　第113回 <a href="113.html">議事次第</a></li>
  <li><a href="../top/index.html">委員会トップ</a></li>
</ul></body></html>
"""

EGC_DATE_TABLE = """
<html><body><table>
  <tr><td>令和6年8月27日</td><td>第100回</td><td>議事概要</td></tr>
  <tr><td>令和6年7月30日</td><td>第99回</td><td>議事録</td></tr>
  <tr><td>第1回～第5回</td><td>(過去ログ)</td><td>—</td></tr>
</table></body></html>
"""


def test_parse_meti_meeting_dates():
    d = parse_meti_meeting_dates(METI_DATE_INDEX, "https://www.meti.go.jp/x/")
    assert d == {114: datetime.date(2026, 5, 8), 113: datetime.date(2026, 4, 3)}


def test_parse_egc_meeting_dates():
    d = parse_egc_meeting_dates(EGC_DATE_TABLE)
    assert d == {100: datetime.date(2024, 8, 27), 99: datetime.date(2024, 7, 30)}


def test_parse_page_date_prefers_labelled():
    html = "<div>公表日 2026年7月1日</div><div>開催日時 令和8年6月22日 10:00～12:00</div>"
    assert parse_page_date(html) == datetime.date(2026, 6, 22)


# ── Forward schedule: relevance + matching ────────────────────────────────────
def test_is_energy_relevant_filters_non_energy():
    assert sched.is_energy_relevant("電力・ガス基本政策小委員会")
    assert sched.is_energy_relevant("調整力及び需給バランス評価等に関する委員会")
    assert not sched.is_energy_relevant("健康経営推進検討会")
    # shares 電気 with 電気通信 but is telecoms → excluded
    assert not sched.is_energy_relevant("情報通信審議会 電気通信事業政策部会")


def test_match_committee_to_tracked():
    assert sched.match_committee("第105回 調整力及び需給バランス評価等に関する委員会") == "chousei_jukyu"
    assert sched.match_committee("第102回調達価格等算定委員会") == "santeii"
    assert sched.match_committee("原子力損害賠償紛争審査会") is None


METI_CALENDAR = """
<html><body>
  <p>2026年7月7日(火)</p><p>審議会</p>
  <p>総合資源エネルギー調査会 電力・ガス事業分科会 第85回電力・ガス基本政策小委員会</p>
  <p>2026年7月8日(水)</p><p>審議会</p>
  <p>第37回 産業構造転換分野ワーキンググループ</p>
  <p>2026年7月13日(月)</p><p>審議会</p>
  <p>健康経営推進検討会（第6回）</p>
</body></html>
"""

def test_parse_meti_calendar_keeps_energy_only():
    items = sched.parse_meti_calendar(METI_CALENDAR)
    names = [i.name_ja for i in items]
    assert any("電力・ガス基本政策" in n for n in names)
    assert not any("産業構造転換" in n for n in names)
    assert not any("健康経営" in n for n in names)
    energy = next(i for i in items if "電力・ガス基本政策" in i.name_ja)
    assert energy.date == datetime.date(2026, 7, 7)
    assert energy.meeting_num == 85


def test_parse_meti_calendar_name_starting_with_year_is_not_a_date_header():
    # A meeting name that begins with a fiscal/target year AND carries an embedded
    # date must not be mistaken for a date header (which would drop the real entry).
    cal = (
        "<html><body>"
        "<p>2026年7月7日(火)</p><p>審議会</p>"
        "<p>2030年度電力需給見通し検討会（2030年3月1日中間とりまとめ）</p>"
        "</body></html>"
    )
    items = sched.parse_meti_calendar(cal)
    assert len(items) == 1
    assert items[0].date == datetime.date(2026, 7, 7)
    assert "2030年度電力需給見通し" in items[0].name_ja


def test_dedupe_future_drops_past_and_prefers_matched():
    today = datetime.date(2026, 7, 6)
    past = sched.Upcoming(datetime.date(2026, 6, 1), "調整力…委員会", "OCCTO", "meti", "u", None, None)
    fut_unmatched = sched.Upcoming(
        datetime.date(2026, 7, 10), "電力・ガス基本政策小委員会", "METI", "meti", "u", None, None
    )
    fut_matched = sched.Upcoming(
        datetime.date(2026, 7, 10), "電力・ガス基本政策小委員会", "METI", "meti", "u", 85, "chousei_jukyu"
    )
    out = sched._dedupe_future([past, fut_unmatched, fut_matched], today)
    assert len(out) == 1  # past dropped, dup collapsed
    assert out[0].committee_key == "chousei_jukyu"  # matched wins


# ── Store: meeting_date + upcoming snapshot ───────────────────────────────────
def test_set_meeting_dates_and_missing(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.record_meeting("santeii", 114, None, db_path=db)
    store.record_meeting("santeii", 113, None, db_path=db)
    assert set(store.meetings_missing_date("santeii", db_path=db)) == {114, 113}
    n = store.set_meeting_dates("santeii", {114: datetime.date(2026, 2, 2), 999: datetime.date(2020, 1, 1)}, db_path=db)
    assert n == 1  # only the existing meeting updated
    assert store.meetings_missing_date("santeii", db_path=db) == [113]
    # idempotent: re-setting the same date is a no-op
    assert store.set_meeting_dates("santeii", {114: datetime.date(2026, 2, 2)}, db_path=db) == 0


def test_replace_and_list_upcoming(tmp_path):
    db = str(tmp_path / "t.db")
    rows = [
        sched.Upcoming(datetime.date(2026, 7, 7), "電力・ガス基本政策小委員会", "METI", "meti", "http://x", 85, None),
        sched.Upcoming(
            datetime.date(2026, 7, 10), "調整力及び需給バランス評価等に関する委員会",
            "OCCTO", "meti", "http://y", 106, "chousei_jukyu",
        ),
    ]
    assert store.replace_upcoming(rows, db_path=db) == 2
    got = store.list_upcoming(db_path=db)
    assert [g["date"] for g in got] == ["2026-07-07", "2026-07-10"]  # soonest first
    assert got[1]["committee_key"] == "chousei_jukyu"
    # replace is a full rewrite, not an append
    assert store.replace_upcoming(rows[:1], db_path=db) == 1
    assert len(store.list_upcoming(db_path=db)) == 1


# ── backfill_dates orchestration (fetchers mocked) ────────────────────────────
def test_backfill_dates_meti_only_missing(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    store.record_meeting("santeii", 114, None, db_path=db)
    store.record_meeting("santeii", 113, None, db_path=db)
    store.set_meeting_dates("santeii", {113: datetime.date(2026, 1, 20)}, db_path=db)

    monkeypatch.setattr(
        detect_mod, "fetch_committee_dates",
        lambda c, **kw: {114: datetime.date(2026, 2, 2), 113: datetime.date(2026, 1, 20)},
    )
    monkeypatch.setattr(detect_mod.time, "sleep", lambda *_: None)
    res = detect_mod.backfill_dates(["santeii"], db_path=db, only_missing=True)
    assert res[0]["dated"] == 1  # only 114 was missing
    assert store.meetings_missing_date("santeii", db_path=db) == []
