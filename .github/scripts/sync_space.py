"""Upload the Space's deploy dir to Hugging Face and wait for the rebuild to come up.

The upload alone reports success before the Space has even started building, so a broken
image would go unnoticed; this fails the run when the build or the app start fails.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

REPO_ID = "nakama-s/repower"
FAILED = {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"}
BUILDING = {"BUILDING", "APP_STARTING", "RUNNING_BUILDING", "RUNNING_APP_STARTING"}
IDLE = {"PAUSED", "STOPPED"}


def build_deploy_dir(root: Path, deploy: Path) -> None:
    """space/* at the root (app.py, README, packages.txt), plus what the Dockerfile copies."""
    shutil.rmtree(deploy, ignore_errors=True)
    shutil.copytree(root / "space", deploy)
    shutil.copytree(root / "src", deploy / "src")
    for name in ("Dockerfile", "pyproject.toml", "constraints.txt"):
        shutil.copy(root / name, deploy / name)


def wait_for_build(
    stage_of: Callable[[], str],
    *,
    no_build_grace: float = 600,
    timeout: float = 1800,
    poll: float = 20,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Return once the Space has rebuilt and is RUNNING; exit non-zero if it fails."""
    start = clock()
    saw_build = False
    while True:
        stage = stage_of()
        print(f"Space stage: {stage}", flush=True)
        if stage in FAILED:
            sys.exit(f"Space failed after the sync: {stage}")
        if stage in IDLE:
            print(f"Space is {stage}; not waiting for a build")
            return
        if stage in BUILDING:
            saw_build = True
        elif stage == "RUNNING" and saw_build:
            return
        elapsed = clock() - start
        if not saw_build and elapsed > no_build_grace:
            print(f"::warning::No rebuild observed within {no_build_grace:.0f}s; the Space is {stage}")
            return
        if elapsed > timeout:
            sys.exit(f"Space still {stage} after {timeout:.0f}s")
        sleep(poll)


def main() -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ["HF_TOKEN"])
    deploy = Path("/tmp/space-deploy")
    build_deploy_dir(Path.cwd(), deploy)
    before = api.repo_info(REPO_ID, repo_type="space").sha
    commit = api.upload_folder(
        folder_path=str(deploy),
        repo_id=REPO_ID,
        repo_type="space",
        commit_message="Sync from GitHub",
        ignore_patterns=["*.pyc", "__pycache__", "*.egg-info"],
        # Mirror the deploy dir: files removed from the repo must leave the Space too.
        delete_patterns=["*"],
    )
    if commit.oid == before:
        print("Space already up to date; nothing to rebuild")
        return
    print(f"Space synced: {commit.oid}")

    def stage() -> str:
        s = api.get_space_runtime(REPO_ID).stage
        return str(getattr(s, "value", s))

    wait_for_build(stage)
    print("Space rebuilt and running")


if __name__ == "__main__":
    main()
