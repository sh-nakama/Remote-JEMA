"""What a pull must not throw away: the local edits the daily runs never make.

``pull-hf`` replaces the whole DB, so anything changed locally and not pushed is lost.
Most of that is harmless — the daily runs re-scrape the market data and re-detect the
meetings — but the **tracked set** is set only on this machine (the Manage modal, the
``policy track/priority/archive`` CLI), and a lost "summarise this meeting" request is not
redone either. ``hf_sync.sync_from_hf`` therefore pulls a newer copy *and* re-applies these
edits to it:

* ``policy_committee`` ``enabled`` / ``priority`` / ``archived`` — local wins. Nothing in
  CI changes them on an existing row, so a difference is a local edit not yet pushed.
* committees the remote copy lacks (added by URL, or discovered locally) — copied whole,
  with their meetings and materials.
* ``gen_requested`` / ``resummarise_requested`` raised locally — kept unless the remote
  copy has summarised that meeting since (the request is then done). Only raised flags
  travel: the daily ``detect`` raises ``resummarise_requested`` itself, so a local
  ``False`` says nothing.
* hand-set topic tags (``tags_source = 'manual'``), which outrank every other source.

A summary written locally but not pushed is **not** merged: its committee's synthesis
state would have to be reconciled with the remote run's. It is reported instead
(:attr:`Edits.unpushed_summaries`), and the sync refuses to replace the DB.

This module only reads and patches SQLite files; the Hub side lives in ``hf_sync``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STAMP_SCHEMA = 1

_COMMITTEE_FIELDS = ("enabled", "priority", "archived")
_FLAG_FIELDS = ("gen_requested", "resummarise_requested")
_TAG_FIELDS = ("tags", "tags_source")
_SUMMARY_FIELDS = ("summarised_at", "resummarised_at")


def stamp_path(db: Path) -> Path:
    """Where the record of the last Hub sync lives (commit, file hashes, the remote's
    user-owned state): beside the DB, gitignored. Losing it costs one full comparison
    on the next sync, never data."""
    return db.parent / ".hf_sync.json"


def read_stamp(path: Path) -> dict[str, Any] | None:
    try:
        stamp = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return stamp if isinstance(stamp, dict) and stamp.get("schema") == STAMP_SCHEMA else None


def write_stamp(stamp: dict[str, Any], path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**stamp, "schema": STAMP_SCHEMA}), encoding="utf-8")
    os.replace(tmp, path)  # a half-written stamp would read as "never synced"


def _connect_ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


def _columns(con: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA {schema}.table_info({table})")]


def user_state(db: Path) -> dict[str, dict]:
    """The user-owned policy fields of *db*, keyed for :func:`local_edits`.

    Small enough to keep in the stamp (one entry per committee and per meeting), which
    is what lets a sync report pending edits without downloading the remote DB.
    """
    state: dict[str, dict] = {"committees": {}, "meetings": {}}
    if not db.exists():
        return state
    con = _connect_ro(db)
    try:
        if not _columns(con, "policy_committee"):
            return state
        cols: tuple[str, ...] = ("committee_key", *_COMMITTEE_FIELDS, *_TAG_FIELDS)
        for row in con.execute(f"SELECT {', '.join(cols)} FROM policy_committee"):
            state["committees"][row[0]] = dict(zip(cols[1:], row[1:], strict=True))
        cols = ("committee_key", "meeting_num", "state", *_FLAG_FIELDS, *_SUMMARY_FIELDS, *_TAG_FIELDS)
        for row in con.execute(f"SELECT {', '.join(cols)} FROM policy_meeting"):
            state["meetings"][f"{row[0]}#{row[1]}"] = dict(zip(cols[2:], row[2:], strict=True))
    finally:
        con.close()
    return state


@dataclass
class Edits:
    """Local changes the remote copy lacks (see the module docstring for the rules)."""

    committees: dict[str, dict] = field(default_factory=dict)  # key -> {column: local value}
    new_committees: list[str] = field(default_factory=list)  # copied whole
    meetings: dict[str, dict] = field(default_factory=dict)  # "key#num" -> {column: local value}
    unpushed_summaries: list[str] = field(default_factory=list)  # "key #num"

    def __bool__(self) -> bool:
        return bool(self.committees or self.new_committees or self.meetings)

    def describe(self) -> list[str]:
        lines = []
        for key, cols in sorted(self.committees.items()):
            lines.append(f"{key}: " + ", ".join(f"{c}={v}" for c, v in cols.items()))
        lines += [f"{key}: added locally" for key in self.new_committees]
        for mk, cols in sorted(self.meetings.items()):
            key, num = mk.split("#")
            lines.append(f"{key} #{num}: " + ", ".join(f"{c}={v}" for c, v in cols.items()))
        return lines


def _newer(local: str | None, remote: str | None) -> bool:
    # SQLite holds these as ISO text in one format, so text order is time order.
    if not local:
        return False
    return not remote or local > remote


def local_edits(local: dict[str, dict], remote: dict[str, dict]) -> Edits:
    """What applying *local*'s user-owned state onto *remote*'s would change."""
    edits = Edits()
    for key, lc in local["committees"].items():
        rc = remote["committees"].get(key)
        if rc is None:
            edits.new_committees.append(key)
            continue
        changed = {c: lc[c] for c in _COMMITTEE_FIELDS if lc[c] != rc.get(c)}
        if lc.get("tags_source") == "manual":
            changed |= {c: lc[c] for c in _TAG_FIELDS if lc[c] != rc.get(c)}
        if changed:
            edits.committees[key] = changed
    new = set(edits.new_committees)
    for mk, lm in local["meetings"].items():
        key, num = mk.split("#")
        if key in new:
            continue
        rm = remote["meetings"].get(mk)
        if rm is None:
            # Detected only here: the daily detect finds it again — unless it was summarised.
            if lm.get("state") == "done":
                edits.unpushed_summaries.append(f"{key} #{num}")
            continue
        if any(_newer(lm.get(c), rm.get(c)) for c in _SUMMARY_FIELDS):
            edits.unpushed_summaries.append(f"{key} #{num}")
            continue
        changed = {}
        remote_ran = any(lm.get(c) != rm.get(c) for c in _SUMMARY_FIELDS)
        if not remote_ran:
            changed |= {c: lm[c] for c in _FLAG_FIELDS if lm.get(c) and not rm.get(c)}
        if lm.get("tags_source") == "manual":
            changed |= {c: lm[c] for c in _TAG_FIELDS if lm[c] != rm.get(c)}
        if changed:
            edits.meetings[mk] = changed
    edits.new_committees.sort()
    edits.unpushed_summaries.sort()
    return edits


def apply_edits(target: Path, local: Path, edits: Edits) -> None:
    """Write *edits* (read from *local*) into the DB at *target*, in one transaction."""
    # A URI main connection, so the ATTACH below may open the local copy read-only.
    con = sqlite3.connect(f"file:{target.as_posix()}", uri=True)
    try:
        con.execute("ATTACH DATABASE ? AS loc", (f"file:{local.as_posix()}?mode=ro",))
        with con:
            for table in ("policy_committee", "policy_meeting", "policy_material"):
                # Only the columns both copies have: either side may predate a migration.
                theirs = set(_columns(con, table, "loc"))
                cols = ", ".join(c for c in _columns(con, table) if c in theirs and c != "id")
                for key in edits.new_committees:
                    con.execute(
                        f"INSERT OR IGNORE INTO main.{table} ({cols}) "
                        f"SELECT {cols} FROM loc.{table} WHERE committee_key = ?", (key,),
                    )
            for key, changed in edits.committees.items():
                sets = ", ".join(f"{c} = ?" for c in changed)
                con.execute(f"UPDATE main.policy_committee SET {sets} WHERE committee_key = ?",
                            (*changed.values(), key))
            for mk, changed in edits.meetings.items():
                key, num = mk.split("#")
                sets = ", ".join(f"{c} = ?" for c in changed)
                con.execute(
                    f"UPDATE main.policy_meeting SET {sets} WHERE committee_key = ? AND meeting_num = ?",
                    (*changed.values(), key, int(num)),
                )
    finally:
        con.close()
