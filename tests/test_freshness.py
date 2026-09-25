"""Freshness gate: per-source lag limits, and the CLI exit code the daily cron alerts on."""

from __future__ import annotations

from datetime import date

import pandas as pd
from typer.testing import CliRunner

from repower import freshness
from repower.db import DemandSupply30m, FuelDaily, JepxAreaPrice30m, JepxSpot30m, get_session, init_db
from repower.scrapers.areas import AREA_NAMES

TODAY = date(2026, 9, 25)


def test_source_ages_flag_what_is_late_or_missing(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    s = get_session(db)
    s.add(JepxSpot30m(date=date(2026, 9, 25), time="00:00", system_price=10.0))
    s.add(JepxAreaPrice30m(area="tepco", date=date(2026, 9, 24), time="00:00", price=10.0))
    s.add(FuelDaily(date=date(2026, 9, 19), ticker="BZ=F", close=80.0))  # 6 days: a long weekend is fine
    for area in AREA_NAMES:
        if area == "kyushu":
            continue  # an area that has gone dark
        d = date(2026, 8, 10) if area == "tohoku" else date(2026, 9, 23)  # Tohoku publishes monthly
        s.add(DemandSupply30m(area=area, date=d, time="00:00", area_demand_mw=1.0))
    s.commit()
    s.close()
    balancing = tmp_path / "bal.parquet"
    pd.DataFrame({"date": ["2026-09-18"]}).to_parquet(balancing)
    monkeypatch.setattr(freshness, "EPRX_BALANCING_PARQUET", balancing)
    monkeypatch.setattr(freshness, "EPRX_TIELINE_PARQUET", tmp_path / "missing.parquet")

    rows = {r["source"]: r for r in freshness.source_ages(db, today=TODAY)}

    assert {k for k, r in rows.items() if r["stale"]} == {"EPRX balancing", "EPRX tieline", "Supply (kyushu)"}
    assert rows["EPRX balancing"]["age"] == 7
    assert rows["Supply (tohoku)"]["age"] == 46 and not rows["Supply (tohoku)"]["stale"]
    assert rows["Supply (newest area)"]["latest"] == date(2026, 9, 23)


def test_check_freshness_exits_nonzero_only_when_something_is_stale(monkeypatch):
    from repower.cli import app

    def fake(stale: bool):
        return lambda: [{"source": "JEPX system price", "latest": TODAY, "age": 0, "limit": 3, "stale": False},
                        {"source": "EPRX tieline", "latest": None, "age": None, "limit": 5, "stale": stale}]

    monkeypatch.setattr(freshness, "source_ages", fake(stale=False))
    assert CliRunner().invoke(app, ["check-freshness"]).exit_code == 0

    monkeypatch.setattr(freshness, "source_ages", fake(stale=True))
    result = CliRunner().invoke(app, ["check-freshness"])
    assert result.exit_code == 1
    assert "EPRX tieline" in result.output
