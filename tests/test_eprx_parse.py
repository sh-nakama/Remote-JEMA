"""Offline parse tests for the EPRX scraper.

All fixtures are synthetic CP932-encoded bytes reproducing the EPRX 4-line
(H / P / T / data) CSV structure. No network access is performed.
"""

from __future__ import annotations

import datetime as dt

from repower.scrapers.eprx import (
    METRIC_MAP,
    parse_product_csv,
    parse_tieline_csv,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────
# 9 regions + 合計(Total), in CSV column order, after [block_id, metric].
_HEADER_REGIONS = "北海道,東北,東京,中部,北陸,関西,中国,四国,九州,合計"

# Two metrics we exercise: demand_mw and price_avg.
_DEMAND_JP = "募集量（TSO別）[MW]"
_PRICE_JP = "平均落札価格（TSO別）[円/kW・30分]"


def _product_csv_48() -> bytes:
    """48-block product CSV, 2 blocks, 2 metrics, 9 regions + Total.

    Block 1 -> 00:00, block 2 -> 00:30. One blank cell (中国 in block 1 demand)
    to exercise blank-cell handling. Total column carries a value that must be
    dropped.
    """
    h = "H,EPRX,Primary,prompt"
    # P line: field [4] holds blocks/day for products.
    p = "P,,,,48,extra"
    t = "T,block_id,metric," + _HEADER_REGIONS
    # data: block_id, metric, <9 region values>, total
    # block 1 demand: 中国 (8th value, index 7) left blank -> 0.0
    d1 = "20260401B01," + _DEMAND_JP + ",10,20,30,40,50,60,,80,90,1000"
    d2 = "20260401B01," + _PRICE_JP + ",1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0,99.0"
    d3 = "20260401B02," + _DEMAND_JP + ",11,21,31,41,51,61,71,81,91,1100"
    d4 = "20260401B02," + _PRICE_JP + ",1.1,2.1,3.1,4.1,5.1,6.1,7.1,8.1,9.1,99.1"
    text = "\n".join([h, p, t, d1, d2, d3, d4]) + "\n"
    return text.encode("cp932")


def _product_csv_8() -> bytes:
    """8-block product CSV, 1 block, demand metric only."""
    h = "H,EPRX,Tertiary 1,prompt"
    p = "P,,,,8,extra"
    t = "T,block_id,metric," + _HEADER_REGIONS
    d1 = "20260401B02," + _DEMAND_JP + ",10,20,30,40,50,60,70,80,90,1000"
    text = "\n".join([h, p, t, d1]) + "\n"
    return text.encode("cp932")


# ── Tests: product parse ─────────────────────────────────────────────────────
def test_metric_map_covers_eight_metrics():
    assert len(METRIC_MAP) == 8
    assert METRIC_MAP[_DEMAND_JP] == "demand_mw"
    assert METRIC_MAP[_PRICE_JP] == "price_avg"


def test_parse_product_48_block_basic():
    rows = parse_product_csv(_product_csv_48(), "1-0", "Primary", "202604_1-0.csv")

    # 9 regions (Total dropped) * 2 metrics * 2 blocks = 36 rows.
    assert len(rows) == 36

    # Tokyo maps to 'tepco'; Total never appears.
    areas = {r["area"] for r in rows}
    assert "tepco" in areas
    assert "Total" not in areas
    assert "tokyo" not in areas
    assert areas == {
        "hokkaido", "tohoku", "tepco", "chubu", "hokuriku",
        "kansai", "chugoku", "shikoku", "kyushu",
    }


def test_parse_product_48_tokyo_to_tepco_value():
    rows = parse_product_csv(_product_csv_48(), "1-0", "Primary", "f.csv")
    # 東京 is the 3rd region -> value 30 for demand in block 1.
    tepco_demand_b1 = [
        r for r in rows
        if r["area"] == "tepco" and r["metric"] == "demand_mw" and r["block_num"] == 1
    ]
    assert len(tepco_demand_b1) == 1
    r = tepco_demand_b1[0]
    assert r["value"] == 30.0
    assert r["product_code"] == "1-0"
    assert r["product"] == "Primary"
    assert r["source_file"] == "f.csv"
    assert r["date"] == dt.date(2026, 4, 1)
    assert r["jfy"] == 2026
    assert r["blocks_per_day"] == 48


def test_parse_product_48_time_derivation():
    rows = parse_product_csv(_product_csv_48(), "1-0", "Primary", "f.csv")
    # 48 blocks -> 30-min steps. Block 1 = 00:00, block 2 = 00:30.
    b1 = next(r for r in rows if r["block_num"] == 1)
    b2 = next(r for r in rows if r["block_num"] == 2)
    assert b1["time"] == "00:00"
    assert b2["time"] == "00:30"


def test_parse_product_blank_cell_is_zero():
    rows = parse_product_csv(_product_csv_48(), "1-0", "Primary", "f.csv")
    # 中国 -> chugoku had a blank demand cell in block 1 -> 0.0.
    chugoku = next(
        r for r in rows
        if r["area"] == "chugoku" and r["metric"] == "demand_mw" and r["block_num"] == 1
    )
    assert chugoku["value"] == 0.0


def test_parse_product_8_block_time_derivation():
    rows = parse_product_csv(_product_csv_8(), "3-1", "Tertiary 1", "f.csv")
    # 9 regions * 1 metric * 1 block.
    assert len(rows) == 9
    assert all(r["blocks_per_day"] == 8 for r in rows)
    # 8 blocks -> 3-hour steps. Block 2 -> 03:00.
    assert all(r["time"] == "03:00" for r in rows)
    assert all(r["block_num"] == 2 for r in rows)


def test_parse_product_too_short_returns_empty():
    assert parse_product_csv(b"H,only\nP,one\n", "1-0", "Primary", "f.csv") == []


# ── Tieline fixture + test ───────────────────────────────────────────────────
def _tieline_csv() -> bytes:
    """Synthetic DCM tieline CSV: 1 block, 2 pairs (one known, one sub-route)."""
    h = "H,EPRX,tieline_DCM,prompt"
    # P line: field [3] holds blocks/day for tieline.
    p = "P,,,48,extra"
    # T line is index-aligned with the data lines: cols 0-2 are
    # block_id/from/to headers, cols 3+ are the metric headers.
    t = ("ブロック,連系方向,,"
         "連系線確保量上限値（順方向）,連系線確保量上限値（逆方向）,"
         "連系線確保量（順方向）,連系線確保量（逆方向）")
    # Known pair 北海道 -> 東北
    d1 = "20260401B01,北海道,東北,100,110,50,55"
    # Sub-route region that must be dropped
    d2 = "20260401B01,関西_関西-中国間(東),中国,1,2,3,4"
    # Unknown pair (no mapping) must be dropped
    d3 = "20260401B01,九州,北海道,9,9,9,9"
    text = "\n".join([h, p, t, d1, d2, d3]) + "\n"
    return text.encode("cp932")


def test_parse_tieline_basic():
    rows = parse_tieline_csv(_tieline_csv(), "DCM", "202604_tieline_DCM.csv")

    # Only the one known pair survives -> 4 metrics.
    assert len(rows) == 4
    pairs = {r["pair"] for r in rows}
    assert pairs == {"Hokkaido → Tohoku"}

    metrics = {r["metric"]: r["value"] for r in rows}
    assert metrics == {
        "upper_limit_fwd": 100.0,
        "upper_limit_rev": 110.0,
        "reserved_fwd": 50.0,
        "reserved_rev": 55.0,
    }

    r = rows[0]
    assert r["market"] == "DCM"
    assert r["date"] == dt.date(2026, 4, 1)
    assert r["time"] == "00:00"
    assert r["blocks_per_day"] == 48
    assert r["is_combined"] is False
    assert r["jfy"] == 2026
    assert r["source_file"] == "202604_tieline_DCM.csv"
