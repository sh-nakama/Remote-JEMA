"""Unit tests for the period-comparison stats + export helpers in dashboard.read.

Wholesale stats read SQLite (synthetic rows via a temp DB). Balancing stats read
the EPRX Parquet (written to a temp path). No network, no Streamlit runtime.
"""

from __future__ import annotations

import datetime as dt

from repower.db import (
    DemandSupply30m,
    JepxAreaPrice30m,
    get_session,
    init_db,
)
from repower.dashboard.read import (
    balancing_period_stats,
    balancing_export_frame,
    wholesale_period_stats,
    wholesale_export_frame,
)
from repower.scrapers.eprx import upsert_eprx


# ── Wholesale (SQLite) ──────────────────────────────────────────────────────

def _seed_wholesale(db_path: str) -> None:
    """Two days of tepco data: demand 100/200 on day 1, 300/400 on day 2;
    JEPX price 10/20 on day 1, 30/40 on day 2."""
    session = get_session(db_path)
    try:
        session.add_all([
            DemandSupply30m(area="tepco", date=dt.date(2026, 4, 1), time="00:00",
                            area_demand_mw=100.0),
            DemandSupply30m(area="tepco", date=dt.date(2026, 4, 1), time="00:30",
                            area_demand_mw=200.0),
            DemandSupply30m(area="tepco", date=dt.date(2026, 4, 2), time="00:00",
                            area_demand_mw=300.0),
            DemandSupply30m(area="tepco", date=dt.date(2026, 4, 2), time="00:30",
                            area_demand_mw=400.0),
            # An unrelated area that must NOT leak into tepco stats.
            DemandSupply30m(area="kansai", date=dt.date(2026, 4, 1), time="00:00",
                            area_demand_mw=999.0),
        ])
        session.add_all([
            JepxAreaPrice30m(area="tepco", date=dt.date(2026, 4, 1), time="00:00", price=10.0),
            JepxAreaPrice30m(area="tepco", date=dt.date(2026, 4, 1), time="00:30", price=20.0),
            JepxAreaPrice30m(area="tepco", date=dt.date(2026, 4, 2), time="00:00", price=30.0),
            JepxAreaPrice30m(area="tepco", date=dt.date(2026, 4, 2), time="00:30", price=40.0),
        ])
        session.commit()
    finally:
        session.close()


def test_wholesale_period_stats(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    _seed_wholesale(db_path)

    s = wholesale_period_stats("tepco", dt.date(2026, 4, 1), dt.date(2026, 4, 1), db_path)
    assert s["avg_demand_mw"] == 150.0       # (100+200)/2
    assert s["peak_demand_mw"] == 200.0
    assert s["avg_price"] == 15.0            # (10+20)/2

    s2 = wholesale_period_stats("tepco", dt.date(2026, 4, 1), dt.date(2026, 4, 2), db_path)
    assert s2["avg_demand_mw"] == 250.0      # (100+200+300+400)/4
    assert s2["peak_demand_mw"] == 400.0
    assert s2["avg_price"] == 25.0           # (10+20+30+40)/4


def test_wholesale_period_stats_empty(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    _seed_wholesale(db_path)
    s = wholesale_period_stats("tepco", dt.date(2025, 1, 1), dt.date(2025, 1, 2), db_path)
    assert s["avg_demand_mw"] is None
    assert s["peak_demand_mw"] is None
    assert s["avg_price"] is None


def test_wholesale_export_frame(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    _seed_wholesale(db_path)
    df = wholesale_export_frame("tepco", dt.date(2026, 4, 1), dt.date(2026, 4, 2), db_path)
    assert not df.empty
    assert "datetime" in df.columns
    assert "area_demand_mw" in df.columns
    assert "price" in df.columns
    assert len(df) == 4  # 4 half-hour slots


# ── Balancing (Parquet) ─────────────────────────────────────────────────────

def _bal_row(metric: str, value: float, time: str, day: int) -> dict:
    return {
        "product_code": "1-0", "product": "Primary", "area": "tepco",
        "date": dt.date(2026, 4, day), "time": time, "block_num": 1,
        "blocks_per_day": 48, "metric": metric, "value": value,
        "jfy": 2026, "source_file": "f.csv",
    }


def _seed_balancing(path: str) -> None:
    """Primary/tepco: demand 100/200, contracted 40/60, price_avg 5/15,
    price_max 8/12 across two slots — written to a temp Parquet."""
    upsert_eprx([
        _bal_row("demand_mw", 100.0, "00:00", 1),
        _bal_row("demand_mw", 200.0, "00:30", 1),
        _bal_row("contracted_mw", 40.0, "00:00", 1),
        _bal_row("contracted_mw", 60.0, "00:30", 1),
        _bal_row("price_avg", 5.0, "00:00", 1),
        _bal_row("price_avg", 15.0, "00:30", 1),
        _bal_row("price_max", 8.0, "00:00", 1),
        _bal_row("price_max", 12.0, "00:30", 1),
    ], path=path)


def test_balancing_period_stats(tmp_path):
    path = str(tmp_path / "bal.parquet")
    _seed_balancing(path)

    s = balancing_period_stats("Primary", "tepco",
                               dt.date(2026, 4, 1), dt.date(2026, 4, 1), path)
    assert s["avg_demand_mw"] == 150.0          # (100+200)/2
    assert s["avg_contracted_mw"] == 50.0       # (40+60)/2
    assert s["avg_unprocured_mw"] == 100.0      # 150 - 50
    assert s["avg_price"] == 10.0               # (5+15)/2
    assert s["avg_max_price"] == 10.0           # (8+12)/2


def test_balancing_period_stats_empty(tmp_path):
    path = str(tmp_path / "bal.parquet")
    _seed_balancing(path)
    # A product not present in the Parquet -> all None.
    s = balancing_period_stats("Secondary 1", "tepco",
                               dt.date(2026, 4, 1), dt.date(2026, 4, 1), path)
    assert all(v is None for v in s.values())


def test_balancing_export_frame(tmp_path):
    path = str(tmp_path / "bal.parquet")
    _seed_balancing(path)
    df = balancing_export_frame("Primary", "tepco",
                                dt.date(2026, 4, 1), dt.date(2026, 4, 1), path)
    assert not df.empty
    assert "datetime" in df.columns
    assert "demand_mw" in df.columns
    assert "contracted_mw" in df.columns
    assert "missing_mw" in df.columns
    # missing_mw = demand - contracted, per slot.
    assert df["missing_mw"].tolist() == [60.0, 140.0]
