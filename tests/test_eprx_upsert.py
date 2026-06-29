"""Offline merge-idempotency tests for the EPRX Parquet writer.

EPRX data lives in compressed Parquet (not SQLite). These tests write to a
temporary Parquet path via pytest's ``tmp_path``. No network access.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from repower.scrapers.eprx import upsert_eprx, upsert_eprx_tieline


def _bal_rows(value: float) -> list[dict]:
    return [
        {
            "product_code": "1-0", "product": "Primary", "area": "tepco",
            "date": dt.date(2026, 4, 1), "time": "00:00", "block_num": 1,
            "blocks_per_day": 48, "metric": "demand_mw", "value": value,
            "jfy": 2026, "source_file": "f1.csv",
        },
        {
            "product_code": "1-0", "product": "Primary", "area": "kansai",
            "date": dt.date(2026, 4, 1), "time": "00:00", "block_num": 1,
            "blocks_per_day": 48, "metric": "demand_mw", "value": value,
            "jfy": 2026, "source_file": "f1.csv",
        },
    ]


def _tie_rows(value: float) -> list[dict]:
    return [
        {
            "market": "DCM", "pair": "Hokkaido → Tohoku",
            "date": dt.date(2026, 4, 1), "time": "00:00", "block_num": 1,
            "blocks_per_day": 48, "metric": "reserved_fwd", "value": value,
            "is_combined": False, "jfy": 2026, "source_file": "t1.csv",
        },
    ]


def _tepco_demand(path: str) -> float:
    df = pd.read_parquet(path)
    return df[(df["area"] == "tepco") & (df["metric"] == "demand_mw")]["value"].iloc[0]


def test_upsert_eprx_idempotent_and_updates(tmp_path):
    path = str(tmp_path / "bal.parquet")

    assert upsert_eprx(_bal_rows(10.0), path=path) == 2
    assert len(pd.read_parquet(path)) == 2
    assert _tepco_demand(path) == 10.0

    # Second merge with a NEW value on the same key: row count stable (de-dup),
    # value updated (last write wins).
    upsert_eprx(_bal_rows(42.0), path=path)
    assert len(pd.read_parquet(path)) == 2
    assert _tepco_demand(path) == 42.0


def test_upsert_eprx_tieline_idempotent_and_updates(tmp_path):
    path = str(tmp_path / "tie.parquet")

    assert upsert_eprx_tieline(_tie_rows(5.0), path=path) == 1
    df = pd.read_parquet(path)
    assert len(df) == 1 and df["value"].iloc[0] == 5.0

    upsert_eprx_tieline(_tie_rows(7.5), path=path)
    df = pd.read_parquet(path)
    assert len(df) == 1 and df["value"].iloc[0] == 7.5


def test_upsert_eprx_empty_returns_zero(tmp_path):
    assert upsert_eprx([], path=str(tmp_path / "b.parquet")) == 0
    assert upsert_eprx_tieline([], path=str(tmp_path / "t.parquet")) == 0
