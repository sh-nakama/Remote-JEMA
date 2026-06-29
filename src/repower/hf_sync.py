"""Hugging Face Dataset sync — push/pull the SQLite DB + EPRX Parquet files.

EPRX balancing/tieline data lives in compressed Parquet (not SQLite); both the
DB and the Parquet files are synced so the deployed Space has everything while
the per-file transfers stay small.
"""

from __future__ import annotations

import logging

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
_SYNC_FILES = [
    (DB_PATH, "repower.db"),
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

    The DB is required; the Parquet files are optional (older snapshots may not
    have them yet) and are skipped if absent from the repo.
    """
    if not HF_TOKEN or not HF_DATASET_REPO:
        raise RuntimeError("HF_TOKEN and HF_DATASET_REPO must be set in environment")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    for local_path, repo_name in _SYNC_FILES:
        required = repo_name == "repower.db"
        try:
            hf_hub_download(
                repo_id=HF_DATASET_REPO,
                repo_type="dataset",
                filename=repo_name,
                token=HF_TOKEN,
                local_dir=str(local_path.parent),
            )
            logger.info("Pulled %s", repo_name)
        except Exception as e:  # noqa: BLE001
            if required:
                raise
            logger.info("Skip pull (%s not in repo yet): %s", repo_name, e)
