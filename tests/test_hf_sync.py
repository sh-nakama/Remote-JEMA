"""Hugging Face sync against a faked Hub — no network.

The pull must never quietly drop a file the dataset holds: a scrape into a
missing EPRX Parquet rebuilds it from one fiscal year, and the next push would
upload that fragment over the full history.
"""

from __future__ import annotations

import hashlib
import json
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
        parents=[],  # parent_commit passed to each create_commit
        downloads=[],  # repo filenames, per hf_hub_download
    )
    # The commit sha is a digest of the contents, so any change to `remote` moves the head.
    state.head = lambda: hashlib.sha1(repr(sorted(state.remote.items())).encode()).hexdigest()

    class FakeApi:
        def __init__(self, token=None):
            pass

        def dataset_info(self, repo_id, *, revision=None, files_metadata=False, **_):
            state.hub_calls.append("dataset_info")
            return SimpleNamespace(sha=state.head(), siblings=[
                SimpleNamespace(rfilename=n, blob_id=None,
                                lfs=SimpleNamespace(sha256=hashlib.sha256(b).hexdigest()))
                for n, b in state.remote.items()
            ])

        def create_repo(self, **_):
            state.hub_calls.append("create_repo")

        def create_commit(self, *, operations, parent_commit=None, **_):
            state.hub_calls.append("create_commit")
            if parent_commit is not None and parent_commit != state.head():
                raise RuntimeError("412 Precondition Failed: the branch moved")
            # The DB snapshot lives in a temp dir that is gone once the push returns.
            files = {op.path_in_repo: Path(op.path_or_fileobj).read_bytes() for op in operations}
            state.commits.append(files)
            state.remote.update(files)
            state.parents.append(parent_commit)
            return SimpleNamespace(oid=state.head())

    def fake_download(*, repo_id, repo_type, filename, token, local_dir, revision=None):
        if filename in state.failing:
            raise OSError("connection reset by peer")
        state.downloads.append(filename)
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

    def replacing_download(*, repo_id, repo_type, filename, token, local_dir, revision=None):
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


# ── sync_from_hf: pull only what changed, keep the local edits ───────────────────


def _policy_db(path: Path) -> Path:
    from repower.db import dispose_engines
    from repower.policy import store

    store.sync_committees(db_path=str(path))
    store.record_meeting("doji_shijo", 10, None, db_path=str(path))
    store.record_meeting("doji_shijo", 11, None, db_path=str(path))
    dispose_engines()  # the tests edit these files with sqlite3 and swap them around
    return path


def _sql(db: Path, sql: str, *args) -> list[tuple]:
    con = sqlite3.connect(db)
    try:
        with con:
            return con.execute(sql, args).fetchall()
    finally:
        con.close()


@pytest.fixture
def synced(hub, tmp_path):
    """Local and Hub hold the same policy DB, and the local copy has been synced once."""
    remote = _policy_db(tmp_path / "remote-src.db")
    hub.remote = {"repower.db": remote.read_bytes()}
    hub.local["repower.db"].write_bytes(remote.read_bytes())
    hf_sync.sync_from_hf()
    hub.hub_calls.clear()
    hub.downloads.clear()
    hub.src = remote
    return hub


def _cron_writes(hub, sql: str, *args) -> None:
    """A daily run changes the Hub's copy."""
    _sql(hub.src, sql, *args)
    hub.remote["repower.db"] = hub.src.read_bytes()


def test_a_first_sync_downloads_nothing_whose_hash_already_matches(hub, tmp_path):
    db = _policy_db(tmp_path / "remote-src.db")
    hub.remote = {"repower.db": db.read_bytes(), "eprx_tieline.parquet": b"tie"}
    hub.local["repower.db"].write_bytes(db.read_bytes())
    hub.local["eprx_tieline.parquet"].write_bytes(b"tie")

    result = hf_sync.sync_from_hf()

    assert hub.downloads == [] and result.downloaded == []
    assert not result.edits


def test_an_up_to_date_copy_costs_one_metadata_call(synced):
    result = hf_sync.sync_from_hf()

    assert synced.hub_calls == ["dataset_info"]
    assert synced.downloads == [] and result.downloaded == []


def test_only_the_changed_file_is_downloaded(synced):
    synced.remote["eprx_balancing.parquet"] = b"bal"

    result = hf_sync.sync_from_hf()

    assert synced.downloads == ["eprx_balancing.parquet"]
    assert result.downloaded == ["eprx_balancing.parquet"]
    assert synced.local["eprx_balancing.parquet"].read_bytes() == b"bal"


def test_a_newer_hub_copy_is_pulled_with_the_local_tracking_edits_reapplied(synced):
    local = synced.local["repower.db"]
    _sql(local, "UPDATE policy_committee SET enabled = 1 - enabled, priority = 4 WHERE committee_key = 'santeii'")
    _sql(local, "UPDATE policy_committee SET archived = 1 WHERE committee_key = 'saisei_kano'")
    _sql(local, "UPDATE policy_meeting SET gen_requested = 1 WHERE meeting_num = 10")
    _sql(local, "INSERT INTO policy_committee (committee_key, name_ja, url, source, enabled, user_added, "
                "archived, consecutive_failures) VALUES ('my_wg', 'WG', 'https://x', 'METI', 1, 1, 0, 0)")
    _sql(local, "INSERT INTO policy_meeting (committee_key, meeting_num, state) VALUES ('my_wg', 1, 'detected')")
    tracked = _sql(local, "SELECT enabled FROM policy_committee WHERE committee_key = 'santeii'")[0][0]
    _cron_writes(synced, "UPDATE policy_meeting SET title = 'from the cron' WHERE meeting_num = 11")

    result = hf_sync.sync_from_hf()

    assert result.downloaded == ["repower.db"]
    assert result.backup is not None and result.backup.exists()
    assert _sql(local, "SELECT title FROM policy_meeting WHERE meeting_num = 11") == [("from the cron",)]
    assert _sql(local, "SELECT enabled, priority FROM policy_committee WHERE committee_key = 'santeii'") == [
        (tracked, 4)]
    assert _sql(local, "SELECT archived FROM policy_committee WHERE committee_key = 'saisei_kano'") == [(1,)]
    assert _sql(local, "SELECT gen_requested FROM policy_meeting WHERE meeting_num = 10") == [(1,)]
    assert _sql(local, "SELECT meeting_num FROM policy_meeting WHERE committee_key = 'my_wg'") == [(1,)]
    assert result.edits.new_committees == ["my_wg"]
    assert set(result.edits.committees) == {"santeii", "saisei_kano"}
    # Still not on the Hub: the next start reports them again, without downloading.
    synced.downloads.clear()
    again = hf_sync.sync_from_hf()
    assert synced.downloads == []
    assert again.edits.describe() == result.edits.describe()


def test_a_request_the_hub_has_since_summarised_is_dropped(synced):
    local = synced.local["repower.db"]
    _sql(local, "UPDATE policy_meeting SET gen_requested = 1 WHERE meeting_num = 10")
    _cron_writes(synced, "UPDATE policy_meeting SET state = 'done', summarised_at = '2026-10-22 01:00:00' "
                         "WHERE meeting_num = 10")

    result = hf_sync.sync_from_hf()

    assert _sql(local, "SELECT state, gen_requested FROM policy_meeting WHERE meeting_num = 10") == [("done", 0)]
    assert not result.edits


def test_a_flag_the_hub_raised_survives_an_unchanged_local_copy(synced):
    _cron_writes(synced, "UPDATE policy_meeting SET resummarise_requested = 1 WHERE meeting_num = 11")

    hf_sync.sync_from_hf()

    local = synced.local["repower.db"]
    assert _sql(local, "SELECT resummarise_requested FROM policy_meeting WHERE meeting_num = 11") == [(1,)]


def test_local_summaries_the_hub_lacks_stop_the_pull(synced):
    local = synced.local["repower.db"]
    _sql(local, "UPDATE policy_meeting SET state = 'done', briefing_md = 'mine', "
                "summarised_at = '2026-10-22 03:00:00' WHERE meeting_num = 11")
    before = local.read_bytes()
    _cron_writes(synced, "UPDATE policy_meeting SET title = 'x' WHERE meeting_num = 10")

    with pytest.raises(hf_sync.SyncConflict, match="doji_shijo #11"):
        hf_sync.sync_from_hf()

    assert local.read_bytes() == before
    result = hf_sync.sync_from_hf(discard_local=True)
    assert _sql(local, "SELECT briefing_md FROM policy_meeting WHERE meeting_num = 11") == [(None,)]
    assert _sql(result.backup, "SELECT briefing_md FROM policy_meeting WHERE meeting_num = 11") == [("mine",)]


def test_a_dry_run_changes_nothing(synced):
    local = synced.local["repower.db"]
    _sql(local, "UPDATE policy_committee SET priority = 2 WHERE committee_key = 'santeii'")
    before = local.read_bytes()
    _cron_writes(synced, "UPDATE policy_meeting SET title = 'x' WHERE meeting_num = 10")

    result = hf_sync.sync_from_hf(dry_run=True)

    assert result.downloaded == ["repower.db"] and set(result.edits.committees) == {"santeii"}
    assert local.read_bytes() == before


def test_push_publishes_the_edits_only_onto_the_commit_it_synced_to(synced):
    local = synced.local["repower.db"]
    _sql(local, "UPDATE policy_committee SET priority = 2 WHERE committee_key = 'santeii'")
    head = synced.head()

    result = hf_sync.sync_from_hf(push=True)

    assert synced.parents == [head]
    assert result.pushed == synced.head()
    assert hf_sync.sync_from_hf().edits.describe() == []  # the Hub has them now


def test_push_does_nothing_without_edits(synced):
    hf_sync.sync_from_hf(push=True)

    assert "create_commit" not in synced.hub_calls


def test_the_snapshots_are_stale_until_exported_from_the_synced_data(synced, tmp_path):
    manifest = tmp_path / "manifest.json"
    assert hf_sync.export_is_stale(manifest)  # never exported
    stamp = hf_sync.read_stamp(hf_sync.stamp_path(synced.local["repower.db"]))
    manifest.write_text(json.dumps({"data_rev": stamp["data_commit"]}), encoding="utf-8")
    assert not hf_sync.export_is_stale(manifest)

    _cron_writes(synced, "UPDATE policy_meeting SET title = 'x' WHERE meeting_num = 10")
    hf_sync.sync_from_hf()
    assert hf_sync.export_is_stale(manifest)


def test_a_sync_lands_under_another_process_holding_the_db_open(synced):
    """A running web-api keeps the DB open; Windows will not rename over it, so the pull
    has to go in through SQLite, and the open connection must see the new rows."""
    local = synced.local["repower.db"]
    reader = sqlite3.connect(local)
    try:
        assert reader.execute("SELECT title FROM policy_meeting WHERE meeting_num = 11").fetchall() == [(None,)]
        _cron_writes(synced, "UPDATE policy_meeting SET title = 'from the cron' WHERE meeting_num = 11")

        hf_sync.sync_from_hf()

        assert reader.execute("SELECT title FROM policy_meeting WHERE meeting_num = 11").fetchall() == [
            ("from the cron",)]
    finally:
        reader.close()
