"""Tests for analysis/features.py: per-area filtering (the daily digest must not
mix the 9 TSO areas' rows together) and all-NaN robustness (rows that exist but
carry no figures must yield no_data, not an idxmax crash)."""

from datetime import date

from repower.analysis.features import compute_features
from repower.db import DemandSupply30m, JepxSpot30m, get_session, init_db

D = date(2026, 7, 1)


def _add_ds(session, area: str, time: str, demand: float | None) -> None:
    session.add(DemandSupply30m(area=area, date=D, time=time, area_demand_mw=demand))


def test_demand_features_are_single_area(tmp_path):
    """Other areas' rows for the same date/time must not leak into the stats."""
    db = str(tmp_path / "t.db")
    init_db(db)
    session = get_session(db)
    _add_ds(session, "tepco", "09:00", 100.0)
    _add_ds(session, "tepco", "09:30", 200.0)
    _add_ds(session, "kansai", "09:00", 999.0)
    session.commit()
    session.close()

    f = compute_features(D, db_path=db)  # default area = tepco
    assert f["area"] == "tepco"
    assert f["demand"]["peak_mw"] == 200
    assert f["demand"]["min_mw"] == 100
    assert f["demand"]["peak_time"] == "09:30"

    f_kansai = compute_features(D, db_path=db, area="kansai")
    assert f_kansai["demand"]["peak_mw"] == 999


def test_all_nan_columns_yield_no_data_not_crash(tmp_path):
    """Rows whose numeric columns are all NULL (e.g. a TSO column shift) used to
    crash idxmax(); they must degrade to no_data so run-all can proceed."""
    db = str(tmp_path / "t.db")
    init_db(db)
    session = get_session(db)
    _add_ds(session, "tepco", "09:00", None)
    session.add(JepxSpot30m(date=D, time="09:00", system_price=10.0, tokyo_area_price=None))
    session.commit()
    session.close()

    f = compute_features(D, db_path=db)
    assert f["demand"] == {"status": "no_data"}
    assert f["jepx"] == {"status": "no_data"}
