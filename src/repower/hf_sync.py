"""Hugging Face Dataset sync — push/pull the SQLite DB + EPRX Parquet files.

EPRX balancing/tieline data lives in compressed Parquet (not SQLite); both the
DB and the Parquet files are synced so the deployed Space has everything while
the per-file transfers stay small.

``pull_db_from_hf`` / ``push_db_to_hf`` replace a whole copy, last write wins.
``sync_from_hf`` is the local-startup path: one metadata call decides whether the Hub
holds anything newer, only changed files are downloaded, and the local edits listed in
:mod:`repower.sync_merge` are carried onto the pulled DB. All three leave a stamp
(``sync_merge.stamp_path``) recording which Hub commit this copy matches.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
from repower.sync_merge import (
    Edits,
    apply_edits,
    local_edits,
    read_stamp,
    stamp_path,
    user_state,
    write_stamp,
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


def _require_hub() -> None:
    if not HF_TOKEN or not HF_DATASET_REPO:
        raise RuntimeError("HF_TOKEN and HF_DATASET_REPO must be set in environment")


def _db_path() -> Path:
    return next(local for local, name in _SYNC_FILES if name == _DB_FILE)


def _file_id(sibling) -> str | None:
    """A content id for one repo file: the LFS sha256 (what ``_sha256`` of the local
    file gives when they match), else the git blob id."""
    lfs = getattr(sibling, "lfs", None)
    sha = getattr(lfs, "sha256", None) if lfs is not None else None
    return sha or getattr(sibling, "blob_id", None)


def remote_revision(api: HfApi, revision: str | None = None) -> tuple[str, dict[str, str | None]]:
    """``(commit sha, {repo filename: content id})`` of the dataset — one metadata call."""
    info = api.dataset_info(HF_DATASET_REPO, revision=revision, files_metadata=True)
    return info.sha, {s.rfilename: _file_id(s) for s in info.siblings or ()}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(repo_name: str, commit: str, dest_dir: Path) -> Path:
    return Path(hf_hub_download(
        repo_id=HF_DATASET_REPO,
        repo_type="dataset",
        filename=repo_name,
        revision=commit,
        token=HF_TOKEN,
        local_dir=str(dest_dir),
    ))


def _stamp(commit: str, files: dict, *, data_commit: str | None, remote_state: dict | None) -> None:
    write_stamp({
        "commit": commit,
        "files": files,
        # The commit whose market data this copy holds — what the web snapshots are built
        # from (export_web records it), so a push alone does not mark them stale.
        "data_commit": data_commit,
        "remote_state": remote_state,
        "synced_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }, stamp_path(_db_path()))


def _state_or_none(db: Path) -> dict | None:
    """``user_state`` for the stamp; an unreadable DB must not fail the pull or push itself
    (the next sync then compares against the local copy instead)."""
    try:
        return user_state(db)
    except sqlite3.DatabaseError:
        logger.warning("could not read the policy state of %s for the sync stamp", db, exc_info=True)
        return None


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


def push_db_to_hf(parent_commit: str | None = None) -> str:
    """Upload a checked DB snapshot and the EPRX Parquet files in one Hub commit.

    One commit keeps the DB (which holds the ETags) and the Parquet rows those
    ETags vouch for from landing out of step. With *parent_commit* the Hub refuses
    the commit if the dataset has moved past it, so the push cannot overwrite a
    newer copy. Returns the new commit sha.
    """
    _require_hub()

    db_path = _db_path()
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
        info = api.create_commit(
            repo_id=HF_DATASET_REPO,
            repo_type="dataset",
            operations=ops,
            commit_message=f"Update {names}",
            parent_commit=parent_commit,
        )
        pushed_state = _state_or_none(snapshot)
    logger.info("Pushed %s", names)
    previous = read_stamp(stamp_path(db_path)) or {}
    commit, files = remote_revision(api, revision=info.oid)
    _stamp(commit, files, data_commit=previous.get("data_commit"), remote_state=pushed_state)
    return commit


def pull_db_from_hf() -> None:
    """Download the SQLite DB and EPRX Parquet files from the HF Dataset repo.

    A Parquet is skipped only when the repo lacks it; any other failure raises, since
    a scrape into a missing Parquet rebuilds it from one fiscal year and push-hf would
    upload that over the full history.
    """
    _require_hub()

    commit, remote = remote_revision(HfApi(token=HF_TOKEN))
    dispose_engines()  # on Windows the download overwrites the DB in place, under open connections
    for local_path, repo_name in _SYNC_FILES:
        if repo_name not in remote:
            if repo_name == _DB_FILE:
                raise FileNotFoundError(f"{repo_name} is not in dataset {HF_DATASET_REPO}")
            logger.info("Skip pull (%s not in repo yet)", repo_name)
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded = _download(repo_name, commit, local_path.parent)
        # The download lands at <dir>/<repo_name>. When the configured local
        # filename differs (e.g. a custom REPOWER_DB_PATH), move it into place
        # so the app reads what was pulled — the repo filename stays stable.
        if downloaded.name != local_path.name:
            downloaded.replace(local_path)
        logger.info("Pulled %s -> %s", repo_name, local_path)
    # Connections opened meanwhile still read the replaced file (POSIX keeps its inode).
    dispose_engines()
    _stamp(commit, remote, data_commit=commit, remote_state=_state_or_none(_db_path()))


class SyncConflict(RuntimeError):
    """The Hub has a newer DB, but this copy holds summaries it lacks: replacing the
    local DB would lose them, and keeping it would miss the daily runs' work."""

    def __init__(self, summaries: list[str]):
        self.summaries = summaries
        shown = ", ".join(summaries[:8]) + (" …" if len(summaries) > 8 else "")
        super().__init__(
            f"Hugging Face has a newer database, but {len(summaries)} meeting summaries here "
            f"are not on it ({shown}). Nothing was changed. Push them first if the Hub has "
            "nothing newer you need (`repower push-hf`), or sync with --discard-local "
            "(the current DB is kept as a .presync.db backup)."
        )


@dataclass
class SyncResult:
    commit: str  # the Hub commit this copy now matches
    downloaded: list[str] = field(default_factory=list)  # repo files replaced locally
    edits: Edits = field(default_factory=Edits)  # local edits the Hub copy lacks (kept)
    backup: Path | None = None  # the DB as it was before the pull
    pushed: str | None = None  # the new commit, when push=True published the edits
    dry_run: bool = False


def _stale_files(remote: dict, stamp: dict | None, commit: str) -> list[tuple[Path, str]]:
    """The synced files whose local copy differs from the Hub's at *commit*.

    The stamp answers without reading anything; with no stamp (a first sync) each
    local file is hashed against the Hub's LFS sha256 (~0.2 s for the DB).
    """
    if stamp is not None and stamp.get("commit") == commit:
        return [(p, n) for p, n in _SYNC_FILES if n in remote and not p.exists()]
    known = (stamp or {}).get("files") or {}
    stale = []
    for local_path, name in _SYNC_FILES:
        if name not in remote:
            continue
        if not local_path.exists() or (known.get(name) or _sha256(local_path)) != remote[name]:
            stale.append((local_path, name))
    return stale


def _quick_check(db: Path) -> None:
    con = sqlite3.connect(db)
    try:
        result = con.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        con.close()
    if result != "ok":
        raise RuntimeError(f"downloaded {db.name} failed PRAGMA quick_check: {result}")


def _copy_db(src: Path, dest: Path) -> None:
    """Overwrite *dest* with *src*'s pages through SQLite's backup API.

    Unlike a rename, this works while other processes hold *dest* open (Windows will
    not replace an open file — a running ``web-api`` always has the DB open). It runs as
    one write transaction under SQLite's locking, and every other connection sees the
    new contents at its next read.
    """
    s = sqlite3.connect(src)
    try:
        d = sqlite3.connect(dest, timeout=30)  # wait out a writer mid-transaction
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def _swap_in(fetched: dict[str, Path], stale: list[tuple[Path, str]]) -> Path | None:
    """Put the downloads in place of the live files; the old DB is kept as ``*.presync.db``."""
    backup = None
    dispose_engines()
    try:
        for local_path, name in stale:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if name == _DB_FILE and local_path.exists():
                backup = local_path.with_name(f"{local_path.stem}.presync{local_path.suffix}")
                backup.unlink(missing_ok=True)
                _copy_db(local_path, backup)
                _copy_db(fetched[name], local_path)
            else:
                os.replace(fetched[name], local_path)
    except PermissionError as e:
        raise RuntimeError(
            f"could not replace {e.filename}: another program has it open. Close it and sync again."
        ) from e
    except sqlite3.OperationalError as e:  # "database is locked": a writer held it past the timeout
        raise RuntimeError(f"could not write the pulled DB into {_db_path()}: {e}. Sync again.") from e
    finally:
        dispose_engines()  # reopen on the new contents
    return backup


def sync_from_hf(*, push: bool = False, discard_local: bool = False, dry_run: bool = False) -> SyncResult:
    """Bring this copy up to the Hub's latest without losing local edits.

    1. One metadata call; if the stamp already matches the Hub's commit, nothing is read
       or downloaded.
    2. Only files whose content differs are downloaded, into a temp dir beside the DB.
    3. A newer DB is checked, the local edits (:mod:`repower.sync_merge`) are re-applied
       to it, and it replaces the live file; the old one is kept as ``*.presync.db``.
       Local summaries the Hub lacks raise :class:`SyncConflict` before anything changes.
    4. With *push*, edits the Hub lacks are pushed, on condition that the Hub is still at
       the commit just synced to (so the push can never overwrite a newer copy).
    """
    _require_hub()
    api = HfApi(token=HF_TOKEN)
    commit, remote = remote_revision(api)
    if _DB_FILE not in remote:
        raise FileNotFoundError(f"{_DB_FILE} is not in dataset {HF_DATASET_REPO}")
    db_path = _db_path()
    stamp = read_stamp(stamp_path(db_path))
    stale = _stale_files(remote, stamp, commit)
    db_stale = any(name == _DB_FILE for _, name in stale)
    local_state = user_state(db_path)
    if db_stale:
        remote_state = None  # read from the download below
    elif stamp is not None and stamp.get("remote_state") is not None:
        remote_state = stamp["remote_state"]
    else:
        remote_state = local_state  # no stamp, but the hashes match: the copies are identical

    result = SyncResult(commit=commit, dry_run=dry_run)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Beside the DB, so the final moves are same-volume renames.
    with tempfile.TemporaryDirectory(dir=db_path.parent, ignore_cleanup_errors=True) as tmp:
        fetched = {name: _download(name, commit, Path(tmp)) for _, name in stale}
        if db_stale:
            _quick_check(fetched[_DB_FILE])
            remote_state = user_state(fetched[_DB_FILE])
        result.edits = local_edits(local_state, remote_state)
        result.downloaded = [name for _, name in stale]
        if db_stale and result.edits.unpushed_summaries and not discard_local:
            raise SyncConflict(result.edits.unpushed_summaries)
        if dry_run:
            return result
        if db_stale and result.edits and db_path.exists():
            apply_edits(fetched[_DB_FILE], db_path, result.edits)
        if fetched:
            result.backup = _swap_in(fetched, stale)

    data_commit = commit if fetched or stamp is None else stamp.get("data_commit")
    _stamp(commit, remote, data_commit=data_commit, remote_state=remote_state)
    logger.info("Synced to %s (downloaded: %s)", commit[:8], ", ".join(result.downloaded) or "nothing")

    if push and (result.edits or result.edits.unpushed_summaries):
        result.pushed = push_db_to_hf(parent_commit=commit)
    return result


def export_is_stale(manifest_path: Path) -> bool:
    """Whether the web snapshots predate the market data this copy last synced."""
    stamp = read_stamp(stamp_path(_db_path()))
    if stamp is None or not stamp.get("data_commit"):
        return False  # never synced: nothing says the snapshots are behind
    try:
        built_from = json.loads(manifest_path.read_text(encoding="utf-8")).get("data_rev")
    except (OSError, ValueError):
        return True
    return built_from != stamp["data_commit"]
