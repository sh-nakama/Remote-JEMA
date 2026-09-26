"""Hugging Face Dataset sync — push/pull the SQLite DB + EPRX Parquet files.

EPRX balancing/tieline data lives in compressed Parquet (not SQLite); both the
DB and the Parquet files are synced so the deployed Space has everything while
the per-file transfers stay small.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

from repower.config import (
    DB_PATH,
    EPRX_BALANCING_PARQUET,
    EPRX_TIELINE_PARQUET,
    HF_DATASET_REPO,
    HF_TOKEN,
)
from repower.db import dispose_engines

logger = logging.getLogger(__name__)

# (local path, repo filename) for every synced artifact. The DB is required;
# the Parquet files are optional (older snapshots predate them).
_DB_FILE = "repower.db"
_SYNC_FILES = [
    (DB_PATH, _DB_FILE),
    (EPRX_BALANCING_PARQUET, "eprx_balancing.parquet"),
    (EPRX_TIELINE_PARQUET, "eprx_tieline.parquet"),
]


def _snapshot_db(db_path: Path, dest: Path) -> None:
    """Copy *db_path* to *dest* via SQLite's backup API, refusing a damaged DB.

    The backup holds committed pages only, so it is safe beside a writer; opening
    the source also rolls back any hot journal a killed process left behind.
    """
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            result = dst.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if result != "ok":
        raise RuntimeError(f"{db_path} failed PRAGMA quick_check: {result}")


def push_db_to_hf() -> None:
    """Upload a checked DB snapshot and the EPRX Parquet files in one Hub commit.

    One commit keeps the DB (which holds the ETags) and the Parquet rows those
    ETags vouch for from landing out of step.
    """
    if not HF_TOKEN or not HF_DATASET_REPO:
        raise RuntimeError("HF_TOKEN and HF_DATASET_REPO must be set in environment")

    db_path = next(local for local, name in _SYNC_FILES if name == _DB_FILE)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        snapshot = Path(tmp) / _DB_FILE
        _snapshot_db(db_path, snapshot)
        ops = [CommitOperationAdd(path_in_repo=_DB_FILE, path_or_fileobj=str(snapshot))]
        for local_path, repo_name in _SYNC_FILES:
            if repo_name == _DB_FILE:
                continue
            if not local_path.exists():
                logger.info("Skip push (missing locally): %s", repo_name)
                continue
            ops.append(CommitOperationAdd(path_in_repo=repo_name, path_or_fileobj=str(local_path)))

        names = ", ".join(op.path_in_repo for op in ops)
        api = HfApi(token=HF_TOKEN)
        api.create_repo(repo_id=HF_DATASET_REPO, repo_type="dataset", exist_ok=True, private=True)
        api.create_commit(
            repo_id=HF_DATASET_REPO,
            repo_type="dataset",
            operations=ops,
            commit_message=f"Update {names}",
        )
    logger.info("Pushed %s", names)


def pull_db_from_hf() -> None:
    """Download the SQLite DB and EPRX Parquet files from the HF Dataset repo.

    A Parquet is skipped only when the repo lacks it; any other failure raises, since
    a scrape into a missing Parquet rebuilds it from one fiscal year and push-hf would
    upload that over the full history.
    """
    if not HF_TOKEN or not HF_DATASET_REPO:
        raise RuntimeError("HF_TOKEN and HF_DATASET_REPO must be set in environment")

    remote = set(HfApi(token=HF_TOKEN).list_repo_files(repo_id=HF_DATASET_REPO, repo_type="dataset"))
    dispose_engines()  # on Windows the download overwrites the DB in place, under open connections
    for local_path, repo_name in _SYNC_FILES:
        if repo_name not in remote:
            if repo_name == _DB_FILE:
                raise FileNotFoundError(f"{repo_name} is not in dataset {HF_DATASET_REPO}")
            logger.info("Skip pull (%s not in repo yet)", repo_name)
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded = Path(hf_hub_download(
            repo_id=HF_DATASET_REPO,
            repo_type="dataset",
            filename=repo_name,
            token=HF_TOKEN,
            local_dir=str(local_path.parent),
        ))
        # The download lands at <dir>/<repo_name>. When the configured local
        # filename differs (e.g. a custom REPOWER_DB_PATH), move it into place
        # so the app reads what was pulled — the repo filename stays stable.
        if downloaded.name != local_path.name:
            downloaded.replace(local_path)
        logger.info("Pulled %s -> %s", repo_name, local_path)
    # Connections opened meanwhile still read the replaced file (POSIX keeps its inode).
    dispose_engines()
