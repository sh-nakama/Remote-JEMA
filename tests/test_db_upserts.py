"""Tests for DB idempotency and engine memoization.

All tests use synthetic data and a temporary SQLite path via pytest's
``tmp_path``. No network access is performed.
"""

from __future__ import annotations

import datetime as dt
import threading

from sqlalchemy import func, select

from repower.db import (
    DemandSupply30m,
    FuelDaily,
    NewsItem,
    get_engine,
    get_session,
)
from repower.scrapers.area_base import BaseAreaScraper
from repower.scrapers.fuels_futures import upsert_fuels
from repower.scrapers.news_rss import upsert_news

import pandas as pd


# ── #4: get_engine memoization ─────────────────────────────────────────────
def test_get_engine_memoization(tmp_path):
    path_a = str(tmp_path / "a.db")
    path_b = str(tmp_path / "b.db")

    eng_a1 = get_engine(path_a)
    eng_a2 = get_engine(path_a)
    eng_b = get_engine(path_b)

    # Same path → same cached object.
    assert eng_a1 is eng_a2
    # Different path → different object.
    assert eng_a1 is not eng_b


def test_get_engine_thread_safe(tmp_path):
    """Concurrent get_engine() calls on an uncached path return one shared engine."""
    path = str(tmp_path / "concurrent.db")
    n_threads = 16
    start = threading.Barrier(n_threads)
    results: list = []
    results_lock = threading.Lock()

    def worker():
        start.wait()  # maximize contention on the cache-population path
        engine = get_engine(path)
        with results_lock:
            results.append(engine)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == n_threads
    # The lock must guarantee every thread observes the same single engine.
    assert all(e is results[0] for e in results)


# ── Fuel upsert idempotency ────────────────────────────────────────────────
def test_upsert_fuels_idempotent(tmp_path):
    db_path = str(tmp_path / "t.db")
    rows = [
        {"date": dt.date(2026, 1, 1), "ticker": "BZ=F", "close": 80.5, "currency": "USD"},
        {"date": dt.date(2026, 1, 1), "ticker": "NG=F", "close": 3.2, "currency": "USD"},
    ]

    upsert_fuels(rows, db_path=db_path)
    session = get_session(db_path)
    try:
        count_first = session.execute(select(func.count()).select_from(FuelDaily)).scalar_one()
    finally:
        session.close()

    # Second upsert with identical rows must not add new rows.
    upsert_fuels(rows, db_path=db_path)
    session = get_session(db_path)
    try:
        count_second = session.execute(select(func.count()).select_from(FuelDaily)).scalar_one()
    finally:
        session.close()

    assert count_first == 2
    assert count_second == count_first


# ── News upsert dedup ──────────────────────────────────────────────────────
def test_upsert_news_dedup(tmp_path):
    db_path = str(tmp_path / "t.db")
    now = dt.datetime(2026, 1, 1, 12, 0, 0)
    items = [
        {
            "url_hash": "hash_one",
            "source": "METI",
            "title": "Power market update",
            "summary": "synthetic summary one",
            "published_at": now,
            "fetched_at": now,
        },
        {
            "url_hash": "hash_two",
            "source": "OCCTO",
            "title": "Grid notice",
            "summary": "synthetic summary two",
            "published_at": now,
            "fetched_at": now,
        },
    ]

    first_new = upsert_news(items, db_path=db_path)
    assert first_new == 2

    session = get_session(db_path)
    try:
        count_first = session.execute(select(func.count()).select_from(NewsItem)).scalar_one()
    finally:
        session.close()

    # Second upsert of the same items: dedup by url_hash → 0 new.
    second_new = upsert_news(items, db_path=db_path)
    assert second_new == 0

    session = get_session(db_path)
    try:
        count_second = session.execute(select(func.count()).select_from(NewsItem)).scalar_one()
    finally:
        session.close()

    assert count_first == 2
    assert count_second == count_first


# ── Area upsert idempotency ────────────────────────────────────────────────
class _TestAreaScraper(BaseAreaScraper):
    AREA = "testarea"


def test_area_upsert_idempotent(tmp_path):
    db_path = str(tmp_path / "t.db")
    scraper = _TestAreaScraper()

    df = pd.DataFrame(
        [
            {
                "date": dt.date(2026, 1, 1),
                "time": "00:00",
                "area_demand_mw": 1000.0,
                "nuclear": 200.0,
                "lng": 300.0,
            },
            {
                "date": dt.date(2026, 1, 1),
                "time": "00:30",
                "area_demand_mw": 1050.0,
                "nuclear": 210.0,
                "lng": 310.0,
            },
        ]
    )

    scraper.upsert(df, db_path=db_path)

    def _count():
        session = get_session(db_path)
        try:
            return session.execute(
                select(func.count())
                .select_from(DemandSupply30m)
                .where(DemandSupply30m.area == "testarea")
            ).scalar_one()
        finally:
            session.close()

    count_first = _count()

    # Second upsert with identical data: keyed on (area, date, time) → stable.
    scraper.upsert(df, db_path=db_path)
    count_second = _count()

    assert count_first == 2
    assert count_second == count_first
