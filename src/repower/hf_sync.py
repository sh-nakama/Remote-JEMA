"""Hugging Face Dataset sync — push/pull the SQLite DB file."""

from __future__ import annotations

import logging

from huggingface_hub import HfApi, hf_hub_download

from repower.config import DB_PATH, HF_DATASET_REPO, HF_TOKEN

logger = logging.getLogger(__name__)


def push_db_to_hf() -> None:
    """Upload the local SQLite DB to the HF Dataset repo."""
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

    api.upload_file(
        path_or_fileobj=str(DB_PATH),
        path_in_repo="repower.db",
        repo_id=HF_DATASET_REPO,
        repo_type="dataset",
        commit_message=f"Update repower.db",
    )
    logger.info("Pushed %s to %s", DB_PATH, HF_DATASET_REPO)


def pull_db_from_hf() -> None:
    """Download the SQLite DB from HF Dataset repo to local path."""
    if not HF_TOKEN or not HF_DATASET_REPO:
        raise RuntimeError("HF_TOKEN and HF_DATASET_REPO must be set in environment")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    hf_hub_download(
        repo_id=HF_DATASET_REPO,
        repo_type="dataset",
        filename="repower.db",
        token=HF_TOKEN,
        local_dir=str(DB_PATH.parent),
    )
    logger.info("Pulled DB to %s", DB_PATH)
