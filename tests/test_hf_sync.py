"""Hugging Face sync against a faked Hub — no network.

The pull must never quietly drop a file the dataset holds: a scrape into a
missing EPRX Parquet rebuilds it from one fiscal year, and the next push would
upload that fragment over the full history.
"""

from __future__ import annotations

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
    )

    class FakeApi:
        def __init__(self, token=None):
            pass

        def list_repo_files(self, repo_id, *, repo_type=None, **_):
            return list(state.remote)

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
