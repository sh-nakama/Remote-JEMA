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
from collections.abc import Callable

from repower.policy.scraper import (
    POLITE_DELAY,
    discover_meetings,
    fetch_committee_dates,
    fetch_meti_url_map,
    fetch_occto_meeting_date,
    list_materials,
)
from repower.policy.store import (
    committee_or_config,
    known_meeting_nums,
    meetings_missing_date,
    meetings_missing_materials,
    record_meeting,
    set_committee_checked,
    set_committee_fetch_result,
    set_meeting_dates,
    sync_committees,
    tracked_committees,
)


def _select_committees(keys: list[str] | None, db_path: str | None):
    """Committees to process: the given *keys* (resolved DB-first so runtime-added
    ones work), or **every known non-archived committee** when *keys* is None —
    tracked *and* discovered/untracked (``include_disabled=True``).

    Detection is decoupled from tracking: we scan the whole catalog so a
    newly-discovered committee's meetings are recorded (as pending) right away,
    without waiting for the user to track it. The ``enabled`` flag only gates
    *summarisation* (see ``pipeline.run``'s ``only_enabled``), not detection.

    ``archived`` committees *are* excluded — a concluded committee will never
    publish again, so re-crawling its index every day only burns budget (and, on
    METI, trips the WAF challenge ladder on every run). Naming a committee
    explicitly overrides this, so a deliberate re-crawl of an archived committee
    still works without un-archiving it.

    Callers sync beforehand, so no second sync here."""
    if keys:
        return [c for c in (committee_or_config(k, db_path=db_path) for k in keys) if c is not None]
    return tracked_committees(
        db_path=db_path, sync=False, include_disabled=True, include_archived=False,
    )

logger = logging.getLogger(__name__)


def detect(
    keys: list[str] | None = None,
    *,
    db_path: str | None = None,
    enumerate_window: int = 8,
    backfill_to: int | None = None,
    dry_run: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[dict]:
    """Run detection over the selected committees (default: all).

    Returns one result dict per committee::

        {"key", "source", "status", "error_kind", "error_detail", "latest_online",
         "known_latest", "new", "enumerated", "dated"}

    ``status`` is ``ok`` / ``unchanged`` (index 304'd) / ``error``, and on error
    ``error_kind`` is a :data:`repower.scrapers.http_cache.FETCH_KINDS` slug naming
    the cause (blocked, challenge never cleared, circuit open, moved URL, …). Each
    outcome is persisted per committee — see
    :func:`repower.policy.store.set_committee_fetch_result` — because nothing else
    records it: the HTTP cache stores no row at all for these failures.
    ``progress``, if given, is called as ``progress(done, total, key)`` at the
    start of each committee so a UI can show live "committee i of N" feedback
    during the (slow) scan.

    Meeting *dates* are recorded here too, from the same index body discovery
    already parsed (``dated``). Dates are not a separate crawl's job: METI/EGC
    indexes print them next to the meeting link, and a full second pass over the
    WAF-throttled committee pages (:func:`backfill_dates`) often doesn't finish,
    which used to leave meetings permanently dateless — the Deep Dive then shows
    a 検出 (detection) date instead of the date the meeting was held. A committee
    whose index 304s but still has dateless meetings gets one scoped forced
    re-fetch, so settled committees can still self-heal.
    """
    if not dry_run:
        sync_committees(db_path)

    committees = _select_committees(keys, db_path)
    results: list[dict] = []
    total = len(committees)

    for idx, c in enumerate(committees):
        if progress is not None:
            try:
                progress(idx, total, c.key)
            except Exception:  # noqa: BLE001 — progress is best-effort UI feedback
                pass
        known = known_meeting_nums(c.key, db_path)
        known_latest = max(known) if known else None

        disc = discover_meetings(c, db_path=db_path, known_latest=known_latest)

        # A 304 index means "no new meetings", but the meeting *dates* also live in
        # that body — so a committee whose index has settled can never repair
        # missing dates through the cheap path, and stays dateless forever (this is
        # what left 原子力小委員会 showing 検出 dates). Re-request the index once,
        # scoped to committees that actually lack dates, so the repair cost is
        # bounded by that shrinking set rather than by the committee count.
        if disc.status == "unchanged" and not c.is_occto and meetings_missing_date(c.key, db_path):
            logger.info("policy detect %-26s 304 but dates missing; re-fetching index", c.key)
            forced = discover_meetings(
                c, db_path=db_path, known_latest=known_latest, force=True
            )
            if forced.status == "ok":
                disc = forced

        res = {
            "key": c.key,
            "source": c.source,
            "status": disc.status,
            "error_kind": disc.error_kind,
            "error_detail": disc.error_detail,
            "latest_online": disc.meeting_nums[0] if disc.meeting_nums else None,
            "known_latest": known_latest,
            "new": 0,
            "enumerated": 0,
            "dated": 0,
        }

        if not dry_run:
            # Record the outcome for *every* committee, including failures. This is
            # the only durable record of why a committee could not be fetched: the
            # http_cache table stores nothing for a 403/202/circuit-open, since
            # those raise before a row is written.
            set_committee_fetch_result(
                c.key, disc.status, kind=disc.error_kind, detail=disc.error_detail,
                url=disc.error_url or c.url, db_path=db_path,
            )

        if disc.status != "ok":
            if disc.status == "unchanged" and not dry_run:
                set_committee_checked(c.key, db_path=db_path)
            results.append(res)
            if disc.status == "error":
                logger.warning("policy detect %-26s error kind=%s %s",
                               c.key, disc.error_kind, disc.error_detail or "")
            else:
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
            # Persist the dates carried by the index we just parsed. Covers newly
            # recorded meetings *and* already-known ones that never got a date,
            # so this self-heals committees the date backfill never reached.
            res["dated"] = set_meeting_dates(c.key, disc.dates, db_path=db_path)
            set_committee_checked(c.key, db_path=db_path)

        results.append(res)
        logger.info(
            "policy detect %-26s online=%s known=%s new=%d enumerated=%d dated=%d",
            c.key, res["latest_online"], known_latest, res["new"], res["enumerated"],
            res["dated"],
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

    A repair pass — the primary path is :func:`detect`, which records METI/EGC
    dates straight off the index it already fetches. This re-reads the official
    pages for meetings that are *still* dateless (e.g. an OCCTO committee, whose
    index carries no dates, or a METI/EGC index that was 304/blocked at detection
    time).

    METI/EGC dates come from one index (+ EGC log pages) fetch per committee;
    OCCTO dates live on per-meeting subpages, so they are fetched one page at a
    time (polite delay). With ``only_missing`` (the default) a committee whose
    meetings are all dated is skipped without any fetch — meti.go.jp sits behind a
    WAF whose challenge/backoff can cost minutes per page, so re-reading settled
    committees is what used to starve the ones that actually need a date.
    ``occto_limit`` caps OCCTO subpage fetches per committee per run (None = no
    cap). Returns one result dict per committee.
    """
    sync_committees(db_path)
    committees = _select_committees(keys, db_path)
    results: list[dict] = []

    for c in committees:
        updated = 0
        missing = set(meetings_missing_date(c.key, db_path)) if only_missing else None
        if missing is not None and not missing:
            results.append({"key": c.key, "source": c.source, "dated": 0})
            continue  # nothing to fill — don't spend a fetch on this committee
        if c.is_occto:
            nums = sorted(missing if missing is not None else known_meeting_nums(c.key, db_path),
                          reverse=True)
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
            if missing is not None:
                dates = {n: d for n, d in dates.items() if n in missing}
            updated = set_meeting_dates(c.key, dates, db_path=db_path)
        results.append({"key": c.key, "source": c.source, "dated": updated})
        logger.info("policy dates %-26s updated=%d", c.key, updated)
        time.sleep(POLITE_DELAY)  # be gentle on meti.go.jp between committees

    return results


def backfill_materials(
    keys: list[str] | None = None,
    *,
    db_path: str | None = None,
    limit_per_committee: int | None = 8,
) -> list[dict]:
    """Enumerate materials for meetings that were detected without any.

    ``detect`` only fetches materials for *new* meetings, so a meeting first seen
    while its committee page was unavailable stays material-less — and the Policy
    Deep Dive hides material-less, non-error meetings, so such a meeting never
    appears even though its committee is tracked. This re-fetches the meeting pages
    (newest first, capped at ``limit_per_committee`` per committee per run) and
    records whatever materials are now published, so catch-up self-heals over one or
    more runs. ``limit_per_committee=None`` processes every material-less meeting.

    Returns one result dict per committee::

        {"key", "source", "materialised", "checked"}
    """
    sync_committees(db_path)
    committees = _select_committees(keys, db_path)
    results: list[dict] = []

    for c in committees:
        nums = meetings_missing_materials(c.key, db_path=db_path)
        if limit_per_committee is not None:
            nums = nums[:limit_per_committee]
        # METI: resolve every meeting's subpage URL from ONE index fetch, so we
        # don't re-hit the (WAF-challenged) index once per meeting. If the index is
        # unreachable this run, defer the whole committee rather than hammering it.
        meti_urls = None
        if nums and not c.is_occto and not c.is_egc:
            meti_urls = fetch_meti_url_map(c, db_path=db_path)
            if not meti_urls:
                logger.info("policy materials %-26s index unreachable; deferring", c.key)
                results.append(
                    {"key": c.key, "source": c.source, "materialised": 0, "checked": 0}
                )
                continue
        materialised = 0
        for n in nums:
            page_url = meti_urls.get(n) if meti_urls is not None else None
            mats = list_materials(c, n, db_path=db_path, page_url=page_url)
            if mats:
                record_meeting(c.key, n, mats, db_path=db_path)
                materialised += 1
            time.sleep(POLITE_DELAY)  # be gentle between meeting-page fetches
        results.append(
            {"key": c.key, "source": c.source, "materialised": materialised, "checked": len(nums)}
        )
        if nums:
            logger.info("policy materials %-26s materialised=%d/%d", c.key, materialised, len(nums))

    return results
