"""The TSO scrapers' URL probing: the cheap path first, the full probe as the safety net."""

from __future__ import annotations

import re
from datetime import date

from repower.scrapers import area_base
from repower.scrapers.areas import ALL_SCRAPERS, TepcoScraper


def test_every_probing_scraper_tries_its_area_code_first():
    for cls in ALL_SCRAPERS:
        urls = cls().csv_urls(2026, 10)
        if len(urls) == 1:
            continue  # a fixed URL (Chugoku, Kyushu): nothing to probe
        assert cls.AREA_CODE, f"{cls.AREA} probes without an AREA_CODE"
        assert re.search(rf"_{cls.AREA_CODE}\.csv$", urls[0]), (cls.AREA, urls[0])
        # The other suffixes are still there, should a TSO ever rename its files.
        assert len(urls) == len(set(urls)) == 12


def test_a_month_found_at_the_area_code_costs_one_request(monkeypatch):
    seen = []

    def fake_get(url, **_):
        seen.append(url)
        return ("not_modified", None)

    monkeypatch.setattr(area_base, "conditional_get", fake_get)

    assert TepcoScraper().fetch_csv(2026, 10) is area_base._UNCHANGED
    assert seen == ["https://www.tepco.co.jp/forecast/html/images/eria_jukyu_202610_03.csv"]


def test_a_renamed_file_is_still_found_by_the_probe(monkeypatch):
    monkeypatch.setattr(area_base, "today_jst", lambda: date(2026, 10, 22))
    seen = []

    def fake_get(url, **_):
        seen.append(url)
        return ("not_modified", None) if url.endswith("_11.csv") else ("not_found", None)

    monkeypatch.setattr(area_base, "conditional_get", fake_get)

    assert TepcoScraper().fetch_csv(2026, 10) is area_base._UNCHANGED
    assert [u[-6:-4] for u in seen] == ["03", "12", "11"]


def test_a_past_month_missing_at_its_area_code_is_not_probed(monkeypatch):
    """Chubu serves two months live: an older month 404s at every suffix, so the probe
    there only ever cost 11 paced requests."""
    monkeypatch.setattr(area_base, "today_jst", lambda: date(2026, 10, 22))
    seen = []

    def fake_get(url, **_):
        seen.append(url)
        return ("not_found", None)

    monkeypatch.setattr(area_base, "conditional_get", fake_get)

    assert TepcoScraper().fetch_csv(2026, 8) is None
    assert [u[-6:-4] for u in seen] == ["03"]


def test_force_reaches_every_request(monkeypatch):
    forced = []

    def fake_get(url, *, force=False, **_):
        forced.append(force)
        return ("not_modified", None)

    monkeypatch.setattr(area_base, "conditional_get", fake_get)

    TepcoScraper().scrape(months_back=2, force=True)

    assert forced and all(forced)


def test_an_html_notice_served_as_200_is_not_cached_as_the_month(monkeypatch):
    monkeypatch.setattr(area_base, "today_jst", lambda: date(2026, 10, 22))
    dropped = []
    monkeypatch.setattr(area_base, "conditional_get",
                        lambda url, **_: ("ok", b"\n<!DOCTYPE html><html>notice</html>"))
    monkeypatch.setattr(area_base, "invalidate", lambda url, **_: dropped.append(url))

    assert TepcoScraper().fetch_csv(2026, 10) is None
    assert len(dropped) == 12  # every probed URL answered with the page
