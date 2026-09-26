"""Hugging Face sync against a faked Hub — no network.

The pull must never quietly drop a file the dataset holds: a scrape into a
missing EPRX Parquet rebuilds it from one fiscal year, and the next push would
upload that fragment over the full history.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from repower import hf_sync

_NAMES = ("repower.db", "eprx_balancing.parquet", "eprx_tieline.parquet")


@pytest.fixture
def hub(tmp_path, monkeypatch):
    """Point hf_sync at tmp paths and a fake Hub whose contents the test controls."""
    state = SimpleNamespace(
        remote={},  # repo filename -> bytes
        failing=set(),  # repo filenames whose download raises
        local={name: tmp_path / name for name in _NAMES},
        hub_calls=[],  # every create_repo / create_commit, in order
        commits=[],  # {repo filename: bytes} per create_commit
    )

    class FakeApi:
        def __init__(self, token=None):
            pass

        def list_repo_files(self, repo_id, *, repo_type=None, **_):
            return list(state.remote)

        def create_repo(self, **_):
            state.hub_calls.append("create_repo")

        def create_commit(self, *, operations, **_):
            state.hub_calls.append("create_commit")
            # The DB snapshot lives in a temp dir that is gone once the push returns.
            state.commits.append({op.path_in_repo: Path(op.path_or_fileobj).read_bytes() for op in operations})

    def fake_download(*, repo_id, repo_type, filename, token, local_dir):
        if filename in state.failing:
            raise OSError("connection reset by peer")
        dest = Path(local_dir) / filename
        dest.write_bytes(state.remote[filename])
        return str(dest)

    monkeypatch.setattr(hf_sync, "HF_TOKEN", "token")
    monkeypatch.setattr(hf_sync, "HF_DATASET_REPO", "someone/dataset")
    monkeypatch.setattr(hf_sync, "HfApi", FakeApi)
    monkeypatch.setattr(hf_sync, "hf_hub_download", fake_download)
    monkeypatch.setattr(hf_sync, "_SYNC_FILES", [(state.local[n], n) for n in _NAMES])
    return state


def test_pull_skips_a_parquet_the_repo_does_not_have(hub):
    hub.remote = {"repower.db": b"db"}

    hf_sync.pull_db_from_hf()

    assert hub.local["repower.db"].read_bytes() == b"db"
    assert not hub.local["eprx_balancing.parquet"].exists()
    assert not hub.local["eprx_tieline.parquet"].exists()


def test_pull_raises_when_a_parquet_the_repo_holds_fails_to_download(hub):
    hub.remote = {name: b"x" for name in _NAMES}
    hub.failing = {"eprx_balancing.parquet"}

    with pytest.raises(OSError, match="connection reset"):
        hf_sync.pull_db_from_hf()


def test_pull_requires_the_db(hub):
    hub.remote = {"eprx_tieline.parquet": b"x"}

    with pytest.raises(FileNotFoundError, match="repower.db"):
        hf_sync.pull_db_from_hf()


def test_pull_moves_the_db_to_a_custom_local_filename(hub, tmp_path, monkeypatch):
    custom = tmp_path / "custom.db"
    monkeypatch.setattr(hf_sync, "_SYNC_FILES", [(custom, "repower.db")])
    hub.remote = {"repower.db": b"db"}

    hf_sync.pull_db_from_hf()

    assert custom.read_bytes() == b"db"
    assert not (tmp_path / "repower.db").exists()


def test_a_pull_over_an_open_db_is_what_the_next_query_reads(hub, tmp_path, monkeypatch):
    """Pooled connections must not keep serving the file a pull just replaced."""
    from sqlalchemy import text

    from repower.db import get_engine

    db = hub.local["repower.db"]
    _make_db(db, ["old"])
    fresh = tmp_path / "fresh.db"
    _make_db(fresh, ["new"])
    hub.remote = {"repower.db": fresh.read_bytes()}

    def replacing_download(*, repo_id, repo_type, filename, token, local_dir):
        # How hf_hub_download lands a file on Linux (the Space): rename over the target.
        part = Path(local_dir) / (filename + ".incomplete")
        part.write_bytes(hub.remote[filename])
        os.replace(part, Path(local_dir) / filename)
        return str(Path(local_dir) / filename)

    monkeypatch.setattr(hf_sync, "hf_hub_download", replacing_download)
    with get_engine(str(db)).connect() as con:  # leaves a pooled connection behind
        assert con.execute(text("SELECT v FROM t")).scalar() == "old"

    hf_sync.pull_db_from_hf()

    with get_engine(str(db)).connect() as con:
        assert con.execute(text("SELECT v FROM t")).scalar() == "new"


def _make_db(path: Path, rows: list[str]) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (v TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    con.commit()
    con.close()


def _rows(db_bytes: bytes, tmp_path: Path) -> list[str]:
    copy = tmp_path / "uploaded.db"
    copy.write_bytes(db_bytes)
    con = sqlite3.connect(copy)
    try:
        return [r[0] for r in con.execute("SELECT v FROM t ORDER BY v")]
    finally:
        con.close()


def test_push_uploads_a_db_snapshot_and_the_parquets_in_one_commit(hub, tmp_path):
    _make_db(hub.local["repower.db"], ["a", "b"])
    hub.local["eprx_balancing.parquet"].write_bytes(b"bal")
    hub.local["eprx_tieline.parquet"].write_bytes(b"tie")
    # A writer mid-transaction: its row must not reach the Hub.
    writer = sqlite3.connect(hub.local["repower.db"], isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t VALUES ('uncommitted')")
    try:
        hf_sync.push_db_to_hf()
    finally:
        writer.execute("ROLLBACK")
        writer.close()

    assert len(hub.commits) == 1
    files = hub.commits[0]
    assert set(files) == set(_NAMES)
    assert files["eprx_balancing.parquet"] == b"bal"
    assert files["eprx_tieline.parquet"] == b"tie"
    assert _rows(files["repower.db"], tmp_path) == ["a", "b"]


def test_push_skips_parquets_that_do_not_exist_locally(hub):
    _make_db(hub.local["repower.db"], ["a"])

    hf_sync.push_db_to_hf()

    assert [set(c) for c in hub.commits] == [{"repower.db"}]


def test_push_refuses_a_damaged_db_before_touching_the_hub(hub):
    hub.local["repower.db"].write_bytes(b"this is not a sqlite database" * 200)

    with pytest.raises(sqlite3.DatabaseError):
        hf_sync.push_db_to_hf()

    assert hub.hub_calls == []
