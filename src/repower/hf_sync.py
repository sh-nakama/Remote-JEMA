"""Hugging Face Dataset sync — push/pull the SQLite DB + EPRX Parquet files.

EPRX balancing/tieline data lives in compressed Parquet (not SQLite); both the
DB and the Parquet files are synced so the deployed Space has everything while
the per-file transfers stay small.
"""

from __future__ import annotations

import logging
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from repower.config import (
    DB_PATH,
    EPRX_BALANCING_PARQUET,
    EPRX_TIELINE_PARQUET,
    HF_DATASET_REPO,
    HF_TOKEN,
)

logger = logging.getLogger(__name__)

# (local path, repo filename) for every synced artifact. The DB is required;
# the Parquet files are optional (older snapshots predate them).
_DB_FILE = "repower.db"
_SYNC_FILES = [
    (DB_PATH, _DB_FILE),
    (EPRX_BALANCING_PARQUET, "eprx_balancing.parquet"),
    (EPRX_TIELINE_PARQUET, "eprx_tieline.parquet"),
]


def push_db_to_hf() -> None:
    """Upload the local SQLite DB and EPRX Parquet files to the HF Dataset repo."""
    if not HF_TOKEN or not HF_DATASET_REPO:
        raise RuntimeError("HF_TOKEN and HF_DATASET_REPO must be set in environment")

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    api = HfApi(token=HF_TOKEN)

    # Ensure the dataset repo exists
    api.create_repo(
        repo_id=HF_DATASET_REPO,
        repo_type="dataset",
        exist_ok=True,
        private=True,
    )

    for local_path, repo_name in _SYNC_FILES:
        if not local_path.exists():
            logger.info("Skip push (missing locally): %s", repo_name)
            continue
        api.upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=repo_name,
            repo_id=HF_DATASET_REPO,
            repo_type="dataset",
            commit_message=f"Update {repo_name}",
        )
        logger.info("Pushed %s -> %s", local_path, repo_name)


def pull_db_from_hf() -> None:
    """Download the SQLite DB and EPRX Parquet files from the HF Dataset repo.

    A Parquet is skipped only when the repo lacks it; any other failure raises, since
    a scrape into a missing Parquet rebuilds it from one fiscal year and push-hf would
    upload that over the full history.
    """
    if not HF_TOKEN or not HF_DATASET_REPO:
        raise RuntimeError("HF_TOKEN and HF_DATASET_REPO must be set in environment")

    remote = set(HfApi(token=HF_TOKEN).list_repo_files(repo_id=HF_DATASET_REPO, repo_type="dataset"))
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
