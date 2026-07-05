"""Unit tests for the curated capacity-market data + formatters (pure — no
DB / network). Guards the shapes the web Capacity screen consumes and the
integrity of the curated OCCTO figures."""

from __future__ import annotations

from repower.dashboard import capacity_data as c


def test_main_auction_covers_fy2024_to_fy2029():
    fys = [e["fy"] for e in c.MAIN_AUCTION]
    assert fys == [2024, 2025, 2026, 2027, 2028, 2029]


def test_main_auction_rows_shape_and_formatting():
    rows = c.main_auction_rows()
    assert len(rows) == 6
    r0, r5 = rows[0], rows[-1]
    # FY2024 cleared at a uniform national price, no zonal split.
    assert r0["fy"] == "FY2024"
    assert r0["natl"] == "¥14,137"
    assert r0["hok"] == "—" and r0["kyu"] == "—"
    assert r0["proc"].endswith(" GW")
    # FY2029 has zonal prices and the record carries an OCCTO source URL.
    assert r5["fy"] == "FY2029"
    assert r5["natl"] == "¥13,303"
    assert r5["hok"].startswith("¥") and r5["kyu"].startswith("¥")
    assert "occto.or.jp" in r5["source"]


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


def test_ltda_rows_passthrough_shape():
    rows = c.ltda_rows()
    assert len(rows) == 5
    assert {"en", "ja", "r1", "r2", "r3", "cum", "share", "c", "cd"} <= set(rows[0])
    # share percentages should sum to ~100.
    assert 95 <= sum(r["share"] for r in rows) <= 105
