"""Unit tests for the curated capacity-market data + formatters (pure — no
DB / network). Guards the shapes the web Capacity screen consumes and the
integrity of the curated OCCTO figures."""

from __future__ import annotations

from repower.dashboard import capacity_data as c


def test_main_auction_covers_fy2024_to_fy2029():
    fys = [e["fy"] for e in c.MAIN_AUCTION]
    assert fys == [2024, 2025, 2026, 2027, 2028, 2029]


def test_every_auction_prices_every_occto_area():
    assert c.AREA_KEYS == [
        "hokkaido", "tohoku", "tepco", "chubu", "hokuriku",
        "kansai", "chugoku", "shikoku", "kyushu",
    ]
    for e in c.MAIN_AUCTION:
        assert list(e["prices"]) == c.AREA_KEYS
        assert list(e["capacity_kw"]) == c.AREA_KEYS
        assert all(p > 0 for p in e["prices"].values())
        assert all(kw > 0 for kw in e["capacity_kw"].values())


def test_procured_totals_match_occto_published_capacity():
    # 約定総容量 as published in each press release — the per-area 約定容量 must
    # sum to it exactly, which is what makes the per-area split auditable.
    published = {
        2024: 167_691_648, 2025: 165_342_148, 2026: 162_710_879,
        2027: 167_447_465, 2028: 166_213_742, 2029: 166_079_863,
    }
    for e in c.MAIN_AUCTION:
        assert c.procured_kw(e) == published[e["fy"]]


def test_national_unit_price_matches_occto_average():
    # 約定総額（経過措置控除後）÷ 約定総容量, rounded to the yen.
    expected = {2024: 9534, 2025: 3109, 2026: 5226, 2027: 7847, 2028: 11134, 2029: 13303}
    for e in c.MAIN_AUCTION:
        assert c.national_unit_price(e) == expected[e["fy"]]


def test_zonal_split_is_wider_than_hokkaido_and_kyushu():
    # The first auction cleared uniformly; every later one split, and from
    # FY2026 the split is wider than the Hokkaido/Kyushu pair the screen used
    # to hardcode — the regression this dataset exists to prevent.
    bands = {e["fy"]: len(set(e["prices"].values())) for e in c.MAIN_AUCTION}
    assert bands[2024] == 1
    assert bands[2025] == 2
    assert all(bands[fy] >= 4 for fy in (2026, 2027, 2028, 2029))
    fy2027 = next(e for e in c.MAIN_AUCTION if e["fy"] == 2027)
    assert fy2027["prices"]["tohoku"] not in (
        fy2027["prices"]["hokkaido"],
        fy2027["prices"]["kyushu"],
        fy2027["prices"]["kansai"],
    )


def test_main_auction_rows_shape_and_formatting():
    rows = c.main_auction_rows()
    assert len(rows) == 6
    r0, r5 = rows[0], rows[-1]
    # FY2024 cleared at one uniform price across every area.
    assert r0["fy"] == "FY2024"
    assert set(r0["areas"].values()) == {14137}
    assert r0["proc"] == "167.7 GW"
    # FY2029 splits four ways and the record carries an OCCTO source URL.
    assert r5["fy"] == "FY2029"
    assert r5["natl"] == "¥13,303"
    assert r5["areas"] == {
        "hokkaido": 14972, "tohoku": 15111, "tepco": 15111, "chubu": 12388,
        "hokuriku": 12388, "kansai": 12388, "chugoku": 12388, "shikoku": 12388,
        "kyushu": 15112,
    }
    assert "occto.or.jp" in r5["source"]


def test_main_auction_rows_do_not_alias_the_source_data():
    rows = c.main_auction_rows()
    rows[0]["areas"]["hokkaido"] = 1
    assert c.MAIN_AUCTION[0]["prices"]["hokkaido"] == 14137


def test_achievement_is_a_sane_percent():
    for e in c.MAIN_AUCTION:
        assert 50 <= e["ach"] <= 100


def test_every_year_has_an_occto_source():
    for e in c.MAIN_AUCTION:
        assert c.SOURCES[e["fy"]].startswith("https://www.occto.or.jp/")


def test_price_and_gw_formatters():
    assert c._fmt_price(14137) == "¥14,137"
    assert c._fmt_price(None) == "—"
    assert c._fmt_gw(166.079) == "166.1 GW"
    assert c._fmt_gw(None) == "—"


def test_by_area_rejects_a_wrong_length_row():
    try:
        c._by_area(1, 2, 3)
    except ValueError:
        return
    raise AssertionError("_by_area accepted a short row")


def test_ltda_rows_passthrough_shape():
    rows = c.ltda_rows()
    assert len(rows) == 5
    assert {"en", "ja", "r1", "r2", "r3", "cum", "share", "c", "cd"} <= set(rows[0])
    # share percentages should sum to ~100.
    assert 95 <= sum(r["share"] for r in rows) <= 105
