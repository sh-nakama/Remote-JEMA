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
from datetime import UTC, date, datetime, timedelta

from repower.policy.scraper import (
    POLITE_DELAY,
    discover_meetings,
    fetch_committee_dates,
    fetch_meti_url_map,
    fetch_occto_meeting_date,
    list_materials,
)
from repower.policy.store import (
    add_late_materials,
    committee_or_config,
    known_meeting_nums,
    meetings_missing_date,
    meetings_missing_materials,
    recent_meeting_nums,
    record_meeting,
    reset_unready_summaries,
    set_committee_checked,
    set_committee_fetch_result,
    set_meeting_dates,
    set_meeting_index_notes,
    sync_committees,
    tracked_committees,
    watch_meeting_nums,
)
from repower.scrapers.http_cache import budget_exhausted
from repower.timeutil import today_jst


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

    A full sweep is ordered **least-recently-succeeded first** (``order="rotate"``),
    not by registry order: the WAF budget only covers a handful of committees per
    host per run, so a fixed order spends it on the same few every time and starves
    the rest permanently. Explicit *keys* keep the caller's order — that is
    deliberate user intent, not a sweep.

    Callers sync beforehand, so no second sync here."""
    if keys:
        return [c for c in (committee_or_config(k, db_path=db_path) for k in keys) if c is not None]
    return tracked_committees(
        db_path=db_path, sync=False, include_disabled=True, include_archived=False,
        order="rotate",
    )

logger = logging.getLogger(__name__)

# How far back (by meeting date) a known meeting's document list is re-read, and how
# many meetings per committee. A meeting's papers are not all up when it is first
# seen: the agenda goes out ahead of it, the handouts around it, and minutes weeks
# later. A week catches the delayed handouts; the per-committee cap keeps the cost
# at a couple of page fetches on a quiet day.
REFRESH_WINDOW_DAYS = 7
REFRESH_LIMIT_PER_COMMITTEE = 5

# The slower tier: summarised meetings with no minutes yet are re-read about weekly
# for WATCH_HORIZON_DAYS after the meeting (minutes land weeks later, and the 7-day
# window above has long closed), plus once regardless of age. See
# :func:`repower.policy.store.watch_meeting_nums`.
WATCH_HORIZON_DAYS = 90
WATCH_INTERVAL_DAYS = 7
WATCH_LIMIT_PER_COMMITTEE = 5


def detect(
    keys: list[str] | None = None,
    *,
    db_path: str | None = None,
    enumerate_window: int = 8,
    backfill_to: int | None = None,
    dry_run: bool = False,
    progress: Callable[[int, int, str], None] | None = None,
    refresh_window_days: int | None = REFRESH_WINDOW_DAYS,
    watch_horizon_days: int | None = WATCH_HORIZON_DAYS,
    today: date | None = None,
) -> list[dict]:
    """Run detection over the selected committees (default: all).

    Returns one result dict per committee::

        {"key", "source", "status", "error_kind", "error_detail", "latest_online",
         "known_latest", "new", "enumerated", "dated", "refreshed", "requeued"}

    ``status`` is ``ok`` / ``unchanged`` (index 304'd) / ``error`` / ``deferred``,
    and on error ``error_kind`` is a :data:`repower.scrapers.http_cache.FETCH_KINDS`
    slug naming the cause (blocked, challenge never cleared, circuit open, moved
    URL, …). ``deferred`` means the committee was never fetched because its host's
    request allowance was spent — not a failure, just work for a later pass. Each
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

    After discovery, the document list of every **recent known meeting** (held within
    *refresh_window_days*; ``None``/0 disables) is re-read, because the list recorded
    when a meeting was first seen goes stale — see :func:`_refresh_recent_materials`.
    ``refreshed`` counts documents added to known meetings, ``requeued`` the already
    summarised meetings flagged for a new briefing because of them.

    A second, slower tier (*watch_horizon_days*; ``None``/0 disables) re-reads
    summarised meetings that still have no minutes or brief, about weekly, out to that
    many days after the meeting — the late-minutes case the 7-day window cannot reach.
    """
    if not dry_run:
        sync_committees(db_path)

    committees = _select_committees(keys, db_path)
    results: list[dict] = []
    total = len(committees)
    just_listed: set[tuple[str, int]] = set()  # enumerated this pass — no need to re-read

    for idx, c in enumerate(committees):
        if progress is not None:
            try:
                progress(idx, total, c.key)
            except Exception:  # noqa: BLE001 — progress is best-effort UI feedback
                pass
        if budget_exhausted(c.url):
            # The host's allowance is spent. Stopping here leaves it healthy for
            # the next pass; pushing on would only collect blocked committees and
            # teach the edge to escalate sooner (docs/GOTCHAS.md).
            results.append({
                "key": c.key, "source": c.source, "status": "deferred",
                "error_kind": None, "error_detail": None, "latest_online": None,
                "known_latest": None, "new": 0, "enumerated": 0, "dated": 0, "noted": 0,
                "refreshed": 0, "requeued": 0,
            })
            continue
        known = known_meeting_nums(c.key, db_path)
        known_latest = max(known) if known else None

        # EGC's index is read in full every pass rather than conditionally: its ※ notes
        # (書面開催 / 削除済み) describe meetings that are already known, so a 304 would leave
        # them unread for as long as the index stays unchanged. It is one small page per
        # committee, on a host that has not needed the WAF-friendly pacing METI does.
        disc = discover_meetings(c, db_path=db_path, known_latest=known_latest,
                                 force=c.is_egc)

        # A 304 index means "no new meetings", but the meeting *dates* also live in
        # that body — so a committee whose index has settled can never repair
        # missing dates through the cheap path, and stays dateless forever (this is
        # what left 原子力小委員会 showing 検出 dates). Re-request the index once,
        # scoped to committees that actually lack dates, so the repair cost is
        # bounded by that shrinking set rather than by the committee count.
        # OCCTO used to be excluded here because its number probe could not report
        # a date. It no longer needs excluding: its list JSON carries dates and is
        # always fetched with a body, so it never reaches this branch anyway.
        if disc.status == "unchanged" and meetings_missing_date(c.key, db_path):
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
            "noted": 0,
            "refreshed": 0,
            "requeued": 0,
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
                just_listed.add((c.key, n))
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
            # The index's own word on whether a meeting has anything to read (EGC only; the
            # other sources hand back no notes). Recorded after the meetings exist above.
            res["noted"] = set_meeting_index_notes(c.key, disc.notes, db_path=db_path)
            set_committee_checked(c.key, db_path=db_path)

        results.append(res)
        logger.info(
            "policy detect %-26s online=%s known=%s new=%d enumerated=%d dated=%d noted=%d",
            c.key, res["latest_online"], known_latest, res["new"], res["enumerated"],
            res["dated"], res["noted"],
        )

    if not dry_run:
        # A summary written before its meeting was held (or a "no sources" failure for one
        # that has no papers yet) is not a result — see ``meeting_readiness``. Run after the
        # dates above are recorded, since a date that arrives late is how a summary can turn
        # out to predate its meeting.
        healed = reset_unready_summaries(db_path, today=today or today_jst())
        if healed["unsummarised"] or healed["cleared"]:
            logger.info("policy detect: %d summary(ies) of unheld meetings withdrawn, "
                        "%d premature failure(s) cleared", healed["unsummarised"], healed["cleared"])

    if (refresh_window_days or watch_horizon_days) and not dry_run:
        # Only committees whose host answered this pass: a blocked or deferred one
        # would just spend more of an allowance that is already gone.
        by_key = {r["key"]: r for r in results}
        day = today or datetime.now(UTC).date()
        since = day - timedelta(days=refresh_window_days) if refresh_window_days else None
        for c in committees:
            if by_key[c.key]["status"] not in ("ok", "unchanged"):
                continue
            try:
                got = _refresh_recent_materials(
                    c, since, today=day, watch_horizon_days=watch_horizon_days,
                    skip=just_listed, db_path=db_path,
                )
            except Exception:  # noqa: BLE001 — a repair pass must never fail detection
                logger.warning("policy detect %-26s document refresh failed", c.key,
                               exc_info=True)
                continue
            by_key[c.key]["refreshed"] = got["refreshed"]
            by_key[c.key]["requeued"] = got["requeued"]

    return results


def _refresh_recent_materials(
    c,
    since: date | None,
    *,
    today: date,
    watch_horizon_days: int | None,
    skip: set[tuple[str, int]],
    db_path: str | None,
    limit: int = REFRESH_LIMIT_PER_COMMITTEE,
    watch_limit: int = WATCH_LIMIT_PER_COMMITTEE,
) -> dict:
    """Re-read the document list of *c*'s known meetings held on/after *since*, plus
    summarised ones still waiting on minutes (the watch tier).

    ``detect`` lists a meeting's documents once, when the meeting is first seen, and
    :func:`~repower.policy.pipeline.summarize_meeting` then trusts that list. But a
    committee page fills in over days: chousei_jukyu 第122回 was recorded with only
    its 議事次第, summarised from that alone, and the papers appeared afterwards — so
    a briefing of a meeting that had plainly discussed three papers said nothing of
    them. Documents found now are added to the meeting; a meeting already ``done``
    that gains one is re-queued (:func:`~repower.policy.store.add_late_materials`).

    Newest *limit* recent meetings, then up to *watch_limit* watched ones — recent
    first, so a spent allowance costs the tier that matters less. Skips meetings listed
    earlier in this pass, and stops as soon as the host's request allowance is spent.
    """
    out = {"refreshed": 0, "requeued": 0}
    recent = ([n for n in recent_meeting_nums(c.key, since, db_path=db_path)
               if (c.key, n) not in skip][:limit] if since is not None else [])
    watched = ([n for n in watch_meeting_nums(c.key, today, horizon_days=watch_horizon_days,
                                              interval_days=WATCH_INTERVAL_DAYS, db_path=db_path)
                if (c.key, n) not in skip and n not in recent][:watch_limit]
               if watch_horizon_days else [])
    nums = recent + watched
    if not nums or budget_exhausted(c.url):
        return out
    # METI: one index fetch resolves every meeting's subpage. A meeting absent from it
    # is skipped rather than costing its own index fetch (list_materials would).
    meti_urls = None
    if not c.is_occto and not c.is_egc:
        meti_urls = fetch_meti_url_map(c, db_path=db_path)
        if not meti_urls:
            return out
    for n in nums:
        if budget_exhausted(c.url):
            break
        page_url = None
        if meti_urls is not None:
            page_url = meti_urls.get(n)
            if page_url is None:
                continue
        mats = list_materials(c, n, db_path=db_path, page_url=page_url)
        if mats:  # [] is "page unreachable", not "document list emptied"
            got = add_late_materials(c.key, n, mats, db_path=db_path)
            out["refreshed"] += got["added"]
            out["requeued"] += int(got["requeued"])
            if got["added"]:
                logger.info("policy detect %-26s 第%d回 +%d document(s)%s", c.key, n,
                            got["added"], " — re-queued" if got["requeued"] else "")
        time.sleep(POLITE_DELAY)
    return out


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
    cap). Returns one result dict per committee, ``deferred`` marking those left
    untouched because the host's request allowance was spent.
    """
    sync_committees(db_path)
    committees = _select_committees(keys, db_path)
    results: list[dict] = []

    for c in committees:
        updated = 0
        missing = set(meetings_missing_date(c.key, db_path)) if only_missing else None
        if missing is not None and not missing:
            results.append({"key": c.key, "source": c.source, "dated": 0, "deferred": False})
            continue  # nothing to fill — don't spend a fetch on this committee
        if budget_exhausted(c.url):
            results.append({"key": c.key, "source": c.source, "dated": 0, "deferred": True})
            continue
        if c.is_occto:
            nums = sorted(missing if missing is not None else known_meeting_nums(c.key, db_path),
                          reverse=True)
            if occto_limit is not None:
                nums = nums[:occto_limit]
            dates = {}
            for n in nums:
                if budget_exhausted(c.url):
                    break
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
        results.append({"key": c.key, "source": c.source, "dated": updated, "deferred": False})
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

        {"key", "source", "materialised", "checked", "deferred"}

    ``deferred`` counts meetings left untouched because the host's request
    allowance ran out — they are not failures, just work for the next run.
    """
    sync_committees(db_path)
    committees = _select_committees(keys, db_path)
    results: list[dict] = []

    for c in committees:
        nums = meetings_missing_materials(c.key, db_path=db_path)
        if limit_per_committee is not None:
            nums = nums[:limit_per_committee]
        if nums and budget_exhausted(c.url):
            results.append({"key": c.key, "source": c.source, "materialised": 0,
                            "checked": 0, "deferred": len(nums)})
            continue
        # METI: resolve every meeting's subpage URL from ONE index fetch, so we
        # don't re-hit the (WAF-challenged) index once per meeting. If the index is
        # unreachable this run, defer the whole committee rather than hammering it.
        meti_urls = None
        if nums and not c.is_occto and not c.is_egc:
            meti_urls = fetch_meti_url_map(c, db_path=db_path)
            if not meti_urls:
                logger.info("policy materials %-26s index unreachable; deferring", c.key)
                results.append(
                    {"key": c.key, "source": c.source, "materialised": 0, "checked": 0,
                     "deferred": len(nums)}
                )
                continue
        materialised = 0
        checked = 0
        for n in nums:
            if budget_exhausted(c.url):
                break
            checked += 1
            page_url = meti_urls.get(n) if meti_urls is not None else None
            mats = list_materials(c, n, db_path=db_path, page_url=page_url)
            if mats:
                record_meeting(c.key, n, mats, db_path=db_path)
                materialised += 1
            time.sleep(POLITE_DELAY)  # be gentle between meeting-page fetches
        results.append(
            {"key": c.key, "source": c.source, "materialised": materialised,
             "checked": checked, "deferred": len(nums) - checked}
        )
        if nums:
            logger.info("policy materials %-26s materialised=%d/%d deferred=%d",
                        c.key, materialised, checked, len(nums) - checked)

    return results
