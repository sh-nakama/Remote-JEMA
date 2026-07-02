"""No-auth new-meeting detection across committees.

Cheap enough to run daily: for each committee it does one (cached) index fetch or
a bounded OCCTO probe, diffs the online meeting numbers against the DB, and
records any new meetings. Materials are enumerated only for the newest few new
meetings (``enumerate_window``) — or for everything at/after ``backfill_to`` when
priming a backfill — so the daily pass stays light. NotebookLM is never touched
here; summarisation is a separate, authenticated step.
"""

from __future__ import annotations

import logging

from repower.policy.scraper import discover_meetings, list_materials
from repower.policy.store import (
    known_meeting_nums,
    record_meeting,
    resolve_committee,
    set_committee_checked,
    sync_committees,
    tracked_committees,
)

logger = logging.getLogger(__name__)


def detect(
    keys: list[str] | None = None,
    *,
    db_path: str | None = None,
    enumerate_window: int = 8,
    backfill_to: int | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Run detection over the selected committees (default: all).

    Returns one result dict per committee::

        {"key", "source", "status", "latest_online", "known_latest", "new", "enumerated"}

    ``status`` is ``ok`` / ``unchanged`` (index 304'd) / ``error``.
    """
    if not dry_run:
        sync_committees(db_path)

    # DB-backed registry: honour the enabled flag + include user-added committees.
    # Already synced above for non-dry runs, so avoid a second sync here.
    if keys:
        committees = [resolve_committee(k, db_path=db_path) for k in keys]
    else:
        committees = tracked_committees(db_path=db_path, sync=False)
    results: list[dict] = []

    for c in committees:
        known = known_meeting_nums(c.key, db_path)
        known_latest = max(known) if known else None

        disc = discover_meetings(c, db_path=db_path, known_latest=known_latest)
        res = {
            "key": c.key,
            "source": c.source,
            "status": disc.status,
            "latest_online": disc.meeting_nums[0] if disc.meeting_nums else None,
            "known_latest": known_latest,
            "new": 0,
            "enumerated": 0,
        }

        if disc.status != "ok":
            if disc.status == "unchanged" and not dry_run:
                set_committee_checked(c.key, known_latest, db_path=db_path)
            results.append(res)
            logger.info("policy detect %-26s %s", c.key, disc.status)
            continue

        new_nums = [n for n in disc.meeting_nums if n not in known]

        if backfill_to is not None:
            to_enum = {n for n in new_nums if n >= backfill_to}
        else:
            to_enum = set(sorted(new_nums, reverse=True)[:enumerate_window])

        for n in sorted(new_nums):
            mats = None
            if n in to_enum:
                mats = list_materials(c, n, db_path=db_path)
                res["enumerated"] += 1
            if dry_run:
                res["new"] += 1
                continue
            if record_meeting(c.key, n, mats, db_path=db_path):
                res["new"] += 1

        if not dry_run:
            set_committee_checked(c.key, res["latest_online"], db_path=db_path)

        results.append(res)
        logger.info(
            "policy detect %-26s online=%s known=%s new=%d enumerated=%d",
            c.key, res["latest_online"], known_latest, res["new"], res["enumerated"],
        )

    return results
