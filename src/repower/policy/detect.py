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

import time

from repower.policy.scraper import (
    POLITE_DELAY,
    discover_meetings,
    fetch_committee_dates,
    fetch_occto_meeting_date,
    list_materials,
)
from repower.policy.store import (
    committee_or_config,
    enabled_committees,
    known_meeting_nums,
    meetings_missing_date,
    record_meeting,
    set_committee_checked,
    set_meeting_dates,
    sync_committees,
)


def _select_committees(keys: list[str] | None, db_path: str | None):
    """Committees to process: the given *keys* (resolved DB-first so runtime-added
    ones work), or all tracked (``enabled=1``) committees when *keys* is None."""
    if keys:
        return [c for c in (committee_or_config(k, db_path=db_path) for k in keys) if c is not None]
    return enabled_committees(db_path)

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

    committees = _select_committees(keys, db_path)
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


def backfill_dates(
    keys: list[str] | None = None,
    *,
    db_path: str | None = None,
    only_missing: bool = True,
    occto_limit: int | None = None,
) -> list[dict]:
    """Populate ``policy_meeting.meeting_date`` from the committees' official pages.

    METI/EGC dates come from one index (+ EGC log pages) fetch per committee, so
    they are cheap and always refreshed. OCCTO dates live on per-meeting subpages,
    so they are fetched one page at a time (polite delay) and, by default, only for
    meetings that still lack a date — making the steady-state daily cost tiny while
    a first run backfills everything. ``occto_limit`` caps OCCTO subpage fetches per
    committee per run (None = no cap). Returns one result dict per committee.
    """
    sync_committees(db_path)
    committees = _select_committees(keys, db_path)
    results: list[dict] = []

    for c in committees:
        updated = 0
        if c.is_occto:
            nums = meetings_missing_date(c.key, db_path) if only_missing else known_meeting_nums(c.key, db_path)
            nums = sorted(nums, reverse=True)
            if occto_limit is not None:
                nums = nums[:occto_limit]
            dates = {}
            for n in nums:
                d = fetch_occto_meeting_date(c, n, db_path=db_path)
                if d is not None:
                    dates[n] = d
                time.sleep(POLITE_DELAY)
            updated = set_meeting_dates(c.key, dates, db_path=db_path)
        else:
            dates = fetch_committee_dates(c, db_path=db_path)
            if only_missing:
                missing = set(meetings_missing_date(c.key, db_path))
                dates = {n: d for n, d in dates.items() if n in missing}
            updated = set_meeting_dates(c.key, dates, db_path=db_path)
        results.append({"key": c.key, "source": c.source, "dated": updated})
        logger.info("policy dates %-26s updated=%d", c.key, updated)
        time.sleep(POLITE_DELAY)  # be gentle on meti.go.jp between committees

    return results
