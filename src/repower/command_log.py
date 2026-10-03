"""A short log of the commands run from the local app, so the pull/push order is *checked*.

``pull-hf`` and ``push-hf`` each replace a whole database, last write wins, with no locking
(see docs/GOTCHAS.md). Two mistakes follow from running them out of order, and both are
silent: pushing a copy that is older than what the daily runs have since written erases
their work, and pulling while holding un-pushed local work erases yours. Documenting the
order does not stop either, so the Commands pane asks this log before it confirms:

* **before a pull** — which successful local writes have happened since the last pull or
  push (those are what the pull would discard);
* **before a push** — how long ago this machine last pulled (a stale copy is what a push
  would overwrite the daily runs' newer data with).

It only knows about commands run *from the app*. A command typed in a terminal leaves no
trace here, and the pane says so rather than implying a clean bill of health.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repower import commands
from repower.config import POLICY_DIR

logger = logging.getLogger(__name__)

PATH = POLICY_DIR / ".cli_runs.json"  # gitignored with the rest of data/policy
KEEP = 60
# The daily runs write to the shared dataset around 06:30 JST; a copy pulled earlier than this is
# likely to be missing something. A heuristic, so the pane warns rather than refuses.
PULL_FRESH_HOURS = 12

# Jobs that are not in the registry (they have their own endpoint) but still change local data.
_EXTRA_WRITES = frozenset({"refresh-web"})
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict) and "cmd" in r and "at" in r]
    except (OSError, ValueError, TypeError):
        return []


def record(cmd_id: str, ok: bool, *, at: datetime | None = None, path: Path | None = None) -> None:
    """Remember that *cmd_id* finished (``ok`` = exit 0). Never raises: a log that cannot be
    written must not turn a finished job into a failed one."""
    target = path or PATH
    entry = {"cmd": cmd_id, "ok": bool(ok), "at": (at or _now()).isoformat(timespec="seconds")}
    try:
        with _lock:
            runs = [*_read(target), entry][-KEEP:]
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(runs), encoding="utf-8")
            os.replace(tmp, target)  # a half-written log would read as "never pulled"
    except OSError:
        logger.warning("could not write the command log", exc_info=True)


def _level(cmd_id: str) -> str | None:
    cmd = commands.BY_ID.get(cmd_id)
    if cmd is not None:
        return cmd.level
    return commands.WRITES if cmd_id in _EXTRA_WRITES else None


def guards(*, now: datetime | None = None, path: Path | None = None) -> dict[str, Any]:
    """What the pane needs to warn before a pull or a push."""
    now = now or _now()
    runs = [r for r in _read(path or PATH) if r.get("ok")]

    def latest(cmd_id: str) -> datetime | None:
        times = [datetime.fromisoformat(r["at"]) for r in runs if r["cmd"] == cmd_id]
        return max(times) if times else None

    last_pull, last_push = latest("pull-hf"), latest("push-hf")
    baseline = max((t for t in (last_pull, last_push) if t is not None), default=None)
    unpushed: dict[str, str] = {}
    for r in runs:
        if _level(r["cmd"]) != commands.WRITES:
            continue
        if baseline is None or datetime.fromisoformat(r["at"]) > baseline:
            unpushed[r["cmd"]] = max(unpushed.get(r["cmd"], r["at"]), r["at"])
    age = (now - last_pull).total_seconds() / 3600 if last_pull else None
    return {
        "lastPull": last_pull.isoformat(timespec="seconds") if last_pull else None,
        "lastPush": last_push.isoformat(timespec="seconds") if last_push else None,
        "unpushed": [{"cmd": c, "at": t} for c, t in sorted(unpushed.items(), key=lambda kv: kv[1])],
        "pullAgeHours": round(age, 1) if age is not None else None,
        "pullStale": age is None or age > PULL_FRESH_HOURS,
        "freshHours": PULL_FRESH_HOURS,
    }
