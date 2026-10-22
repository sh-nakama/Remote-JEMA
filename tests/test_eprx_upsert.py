"""Offline merge-idempotency tests for the EPRX Parquet writer.

EPRX data lives in compressed Parquet (not SQLite). These tests write to a
temporary Parquet path via pytest's ``tmp_path``. No network access.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

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


def test_upsert_eprx_crash_mid_write_keeps_the_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "bal.parquet"
    upsert_eprx(_bal_rows(10.0), path=str(path))

    def torn_write(self, target, *args, **kwargs):
        Path(target).write_bytes(b"PAR1 torn")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", torn_write)
    with pytest.raises(OSError, match="disk full"):
        upsert_eprx(_bal_rows(42.0), path=str(path))

    assert _tepco_demand(str(path)) == 10.0
    assert [p.name for p in tmp_path.iterdir()] == ["bal.parquet"]


def test_a_zip_is_merged_once_and_its_later_csv_still_wins(tmp_path, monkeypatch):
    """Each merge rewrites the whole Parquet, so a ZIP's CSVs go in as one batch —
    in _select_csvs order, so a later file still overrides an earlier one."""
    from repower.scrapers import eprx

    def csv(value: int) -> bytes:
        lines = ["H,EPRX,Primary,prompt", "P,,,,48,extra",
                 "T,block_id,metric,北海道,東北,東京,中部,北陸,関西,中国,四国,九州,合計",
                 f"20260401B01,募集量（TSO別）[MW],1,2,{value},4,5,6,7,8,9,99"]
        return ("\n".join(lines) + "\n").encode("cp932")

    zips = {"1-0": [("202604_a.csv", csv(30)), ("202604_b.csv", csv(31))]}
    monkeypatch.setattr(eprx, "_build_urls", lambda code, jfy_since=None: [(2026, code)])
    monkeypatch.setattr(eprx, "_fetch_zip_csvs", lambda url, **_: zips.get(url))
    path = tmp_path / "bal.parquet"
    merges = []

    def counting_upsert(rows, path_=None):
        merges.append(len(rows))
        return upsert_eprx(rows, path)

    monkeypatch.setattr(eprx, "upsert_eprx", counting_upsert)

    eprx._scrape_products(jfy_since=2026)

    assert merges == [18]  # 9 areas x 2 CSVs, in one merge
    assert _tepco_demand(str(path)) == 31.0
