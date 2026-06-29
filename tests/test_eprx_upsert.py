"""Offline upsert idempotency tests for the EPRX scraper.

Uses a temporary SQLite path via pytest's ``tmp_path``. No network access.
Mirrors ``tests/test_db_upserts.py`` style.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from repower.db import EprxBalancing, EprxTieline, get_session, init_db
from repower.scrapers.eprx import upsert_eprx, upsert_eprx_tieline


def _bal_rows(value: float) -> list[dict]:
    return [
        {
            "product_code": "1-0",
            "product": "Primary",
            "area": "tepco",
            "date": dt.date(2026, 4, 1),
            "time": "00:00",
            "block_num": 1,
            "blocks_per_day": 48,
            "metric": "demand_mw",
            "value": value,
            "jfy": 2026,
            "source_file": "f1.csv",
        },
        {
            "product_code": "1-0",
            "product": "Primary",
            "area": "kansai",
            "date": dt.date(2026, 4, 1),
            "time": "00:00",
            "block_num": 1,
            "blocks_per_day": 48,
            "metric": "demand_mw",
            "value": value,
            "jfy": 2026,
            "source_file": "f1.csv",
        },
    ]


def _tie_rows(value: float) -> list[dict]:
    return [
        {
            "market": "DCM",
            "pair": "Hokkaido → Tohoku",
            "date": dt.date(2026, 4, 1),
            "time": "00:00",
            "block_num": 1,
            "blocks_per_day": 48,
            "metric": "reserved_fwd",
            "value": value,
            "is_combined": False,
            "jfy": 2026,
            "source_file": "t1.csv",
        },
    ]


def test_upsert_eprx_idempotent_and_updates(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)

    upsert_eprx(_bal_rows(10.0), db_path=db_path)

    def _count():
        session = get_session(db_path)
        try:
            return session.execute(
                select(func.count()).select_from(EprxBalancing)
            ).scalar_one()
        finally:
            session.close()

    def _tepco_value():
        session = get_session(db_path)
        try:
            return session.execute(
                select(EprxBalancing.value).where(
                    EprxBalancing.area == "tepco",
                    EprxBalancing.metric == "demand_mw",
                )
            ).scalar_one()
        finally:
            session.close()

    assert _count() == 2
    assert _tepco_value() == 10.0

    # Second upsert with a NEW value on the same unique key: count stable,
    # value updated on conflict.
    upsert_eprx(_bal_rows(42.0), db_path=db_path)
    assert _count() == 2
    assert _tepco_value() == 42.0


def test_upsert_eprx_tieline_idempotent_and_updates(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)

    upsert_eprx_tieline(_tie_rows(5.0), db_path=db_path)

    def _count():
        session = get_session(db_path)
        try:
            return session.execute(
                select(func.count()).select_from(EprxTieline)
            ).scalar_one()
        finally:
            session.close()

    def _value():
        session = get_session(db_path)
        try:
            return session.execute(select(EprxTieline.value)).scalar_one()
        finally:
            session.close()

    assert _count() == 1
    assert _value() == 5.0

    upsert_eprx_tieline(_tie_rows(7.5), db_path=db_path)
    assert _count() == 1
    assert _value() == 7.5


def test_upsert_eprx_empty_returns_zero(tmp_path):
    db_path = str(tmp_path / "t.db")
    assert upsert_eprx([], db_path=db_path) == 0
    assert upsert_eprx_tieline([], db_path=db_path) == 0
