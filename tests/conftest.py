"""Shared test fixtures."""

from __future__ import annotations

import pytest

from repower.policy import store


@pytest.fixture
def policy_db(tmp_path) -> str:
    """Path to a fresh SQLite DB with the committee catalog synced."""
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    return db
