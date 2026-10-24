"""DB read/write for the policy observer + deterministic running-document regen.

State of record lives in the three SQLite tables (``policy_committee``,
``policy_meeting``, ``policy_material``). The per-committee running document at
``data/policy/<key>.md`` is always *regenerated* from the DB (never appended), so
it can't drift from the source of truth and is safe to re-run after a crash.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_

from repower.config import POLICY_DIR
from repower.db import (
    PolicyCommittee,
    PolicyFetchEvent,
    PolicyMaterial,
    PolicyMeeting,
    PolicyUpcoming,
    get_session,
    init_db,
)
from repower.policy.committees import (
    COMMITTEES,
    Committee,
    committee_by_key,
    committee_priority,
)
from repower.policy.scraper import Material
from repower.timeutil import today_jst

logger = logging.getLogger(__name__)

# Errored meetings stay in the worklist until they've failed this many times, so
# transient failures (network/rate-limit) are retried by the next `policy run`.
MAX_RETRIES = 3

# Where a flagged *update* sits in the breadth-first order, as a backlog depth: after every
# committee's newest pending meeting (depth 0), ahead of any committee's second-newest (depth 1).
# See ``pending_meetings``.
UPDATE_DEPTH = 0.5

# The breadth-first run works meetings dated within this many trailing months before it touches
# older ones. A high-priority committee whose recent meetings are already summarised would
# otherwise keep taking the first slot every day with its oldest leftovers while other
# committees' current meetings wait. Soft: older backlog still drains once the recent work is
# done. See ``pending_meetings``.
RECENT_WINDOW_MONTHS = 12


def _months_before(d: date, months: int) -> date:
    """*d* moved back *months* calendar months (day clamped to the target month's length)."""
    y, m0 = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m0 + 1, min(d.day, calendar.monthrange(y, m0 + 1)[1]))


# Documents that carry a meeting's substance. An agenda only lists what *will* be discussed
# (and an appendix is a data sheet for a paper), so a meeting with nothing else has nothing
# to summarise yet.
CONTENT_KINDS = frozenset({"minutes", "brief", "compilation", "handout"})

READY, UPCOMING, AWAITING = "ready", "upcoming", "awaiting"

# How long a "looked, found nothing to read" verdict is trusted before the meeting's page is
# read again. Papers appear over days; a week bounds the cost to one page fetch per awaiting
# meeting per week.
RELIST_DAYS = 7


def meeting_readiness(meeting_date: date | None, kinds, *, today: date,
                      checked_at: datetime | None = None) -> str:
    """Whether a meeting is worth summarising yet: ``ready`` / ``upcoming`` / ``awaiting``.

    * ``upcoming`` — dated *today or later*. The daily run starts at 06:30 JST, before a
      same-day meeting, and committee pages post the agenda and handouts days ahead, so a
      briefing written now describes papers, not a meeting that happened.
    * ``awaiting`` — held (or undated) and *looked at recently* (``checked_at``, within
      :data:`RELIST_DAYS`) with none of :data:`CONTENT_KINDS` on file: an agenda alone, or
      nothing yet.
    * ``ready`` — held, with at least one paper to read **or not yet looked at**. Detection
      only lists the newest few meetings' documents; the rest are listed when their turn comes,
      so "no documents on file" means *unknown*, not *none* — gating on it would leave a
      backlog that has never been listed unreachable forever. ``summarize_meeting`` lists
      it, summarises if there is something to read, and otherwise defers and records the look.

    Derived from the date, the document list and the last look, never stored, so it corrects
    itself the day the date passes or a paper appears and no row can be left stuck. An undated
    meeting is judged on its documents alone: a missing date must not block real work.
    """
    if meeting_date is not None and meeting_date >= today:
        return UPCOMING
    if CONTENT_KINDS.intersection(kinds):
        return READY
    if checked_at is not None and (today - checked_at.date()).days < RELIST_DAYS:
        return AWAITING
    return READY

# Meetings one daily run takes (``policy run --max-per-run``). Mirrors the default in
# .github/workflows/policy.yml, which a test holds equal; the real limiter is usually the
# account's daily NotebookLM quota, which stops a run sooner.
DAILY_RUN_CAP = 8

# Documents to ingest per meeting, in priority order (code-enforced, not agent
# judgment), keeping a meeting to a handful of sources well under any tier cap.
INGEST_KINDS = ("minutes", "brief", "compilation", "handout", "agenda", "appendix")


def _now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def session_scope(db_path: str | None = None, *, commit: bool = True):
    """Init the DB and yield a session: commit on success (``commit=False`` for
    read-only call sites), roll back on exception, always close."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        yield session
        if commit:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Committee bootstrap / registry ───────────────────────────────────────────
def _log_pages_to_db(log_pages) -> str | None:
    """Serialize a committee's EGC ``log_pages`` tuple to the DB's JSON-array form."""
    return json.dumps(list(log_pages)) if log_pages else None


def sync_committees(db_path: str | None = None) -> int:
    """Ensure a ``policy_committee`` row exists for each code-configured committee.

    Idempotent: inserts missing rows and refreshes the static config fields
    (name/url/source + per-source scraper config) without touching dynamic state
    (latest_meeting, synthesis, etc.). ``enabled`` (tracked) and ``priority`` (the
    catch-up queue position) are **user-editable**, so they are seeded only on
    insert — plus a back-fill when a just-migrated row still has ``priority IS
    NULL`` — and never clobbered afterwards, which is what lets a committee "jump
    the queue permanently". Committees not in the config (discovered / user-added)
    are left untouched.
    """
    with session_scope(db_path) as session:
        n = 0
        for c in COMMITTEES:
            row = session.get(PolicyCommittee, c.key)
            if row is None:
                row = PolicyCommittee(committee_key=c.key, enabled=True, user_added=False)
                session.add(row)
                row.enabled = True  # config committees are tracked by default
                row.user_added = False
                row.priority = c.priority  # seed once; user-owned thereafter
                n += 1
            row.name_ja, row.name_en = c.name_ja, c.name_en
            row.url, row.source = c.url, c.source
            row.max_meeting = c.max_meeting
            row.prefix = c.prefix
            row.log_pages = _log_pages_to_db(c.log_pages)
            row.min_meeting = c.min_meeting
            # Back-fill priority for rows from before the priority column existed;
            # preserve UI/CLI edits otherwise.
            if row.priority is None:
                row.priority = c.priority
        return n


def _row_to_committee(row: PolicyCommittee) -> Committee:
    """Build a :class:`~repower.policy.committees.Committee` config object from a
    ``policy_committee`` row, so the scraper can process it whether it was seeded
    from config or added at runtime."""
    try:
        log_pages = tuple(json.loads(row.log_pages) or ()) if row.log_pages else ()
    except (ValueError, TypeError):
        log_pages = ()
    return Committee(
        key=row.committee_key,
        name_ja=row.name_ja or row.committee_key,
        name_en=row.name_en or row.committee_key,
        url=row.url or "",
        source=row.source or "METI",
        priority=row.priority if row.priority is not None else 100,
        max_meeting=row.max_meeting,
        prefix=row.prefix,
        log_pages=log_pages,
        min_meeting=row.min_meeting,
    )


def committee_or_config(key: str, db_path: str | None = None) -> Committee | None:
    """Resolve *key* to a ``Committee`` config object, DB row first (so runtime-added
    committees resolve), then the static config, else None."""
    with session_scope(db_path, commit=False) as session:
        row = session.get(PolicyCommittee, key)
        if row is not None:
            return _row_to_committee(row)
    try:
        return committee_by_key(key)
    except KeyError:
        return None


def resolve_committee(key: str, db_path: str | None = None) -> Committee:
    """Like :func:`committee_or_config`, but raises ``KeyError`` for an unknown key
    (the dashboard's strict variant)."""
    c = committee_or_config(key, db_path=db_path)
    if c is None:
        raise KeyError(key)
    return c


def enabled_committees(db_path: str | None = None) -> list[Committee]:
    """Tracked committees (``enabled=1``) as ``Committee`` config objects, in
    summarisation order (priority, then key)."""
    with session_scope(db_path, commit=False) as session:
        rows = session.query(PolicyCommittee).filter(PolicyCommittee.enabled == True).all()  # noqa: E712
        coms = [_row_to_committee(r) for r in rows]
        coms.sort(key=lambda c: (c.priority, c.key))
        return coms


def tracked_committees(
    db_path: str | None = None, *, include_disabled: bool = False, sync: bool = True,
    include_archived: bool = False, order: str = "code",
) -> list[Committee]:
    """The committees to detect/summarise, as :class:`Committee` objects.

    Reads the DB registry (so it includes user-added committees and honours the
    ``enabled`` flag). ``sync=True`` seeds the code committees first. Before the
    first sync (empty registry) it falls back to the code config so a fresh dry-run
    still sees every committee.

    ``archived`` committees (concluded, no longer meeting) are excluded unless
    ``include_archived=True`` — they are a *fetch* exclusion, orthogonal to the
    ``enabled`` tracking flag. Their stored meetings are untouched and still render.

    ``order`` is ``"code"`` (registry order — stable, what UIs and reports want) or
    ``"rotate"`` (least-recently-*succeeded* first). Use ``"rotate"`` for fetch
    passes: see :func:`_rotation_key` for why fixed order starves committees.
    """
    if sync:
        sync_committees(db_path)
    with session_scope(db_path, commit=False) as session:
        q = session.query(PolicyCommittee)
        if not include_disabled:
            q = q.filter(PolicyCommittee.enabled.is_(True))
        if not include_archived:
            # Rows predating the migration default can read NULL, so match on
            # "not true" rather than "is false".
            q = q.filter(PolicyCommittee.archived.isnot(True))
        rows = q.all()
        if not rows and not sync:
            return list(COMMITTEES)
        # Preserve the code ordering for code committees; append user-added ones.
        code_order = {c.key: i for i, c in enumerate(COMMITTEES)}

        def _code_key(r):
            return (code_order.get(r.committee_key, len(code_order)), r.committee_key)

        if order == "rotate":
            rows.sort(key=lambda r: _rotation_key(r, _code_key(r)))
        else:
            rows.sort(key=_code_key)
        return [_row_to_committee(r) for r in rows]


# Sorts before any real timestamp, so "never" always outranks "long ago".
_NEVER = ""


def _rotation_key(row, tiebreak):
    """Sort key putting the most *starved* committee first.

    A fetch pass against meti.go.jp gets roughly four committees through before the
    WAF starts challenging and the circuit breaker opens; everything after that is
    collateral that is never actually attempted. With a fixed registry order the
    same alphabetically-early committees consume that budget on every single run
    and the same later ones starve forever — which is why committees like `santeii`
    showed no meetings despite their index being perfectly reachable when fetched
    on its own.

    Ordering:

    1. ``last_ok_at`` ascending, never-succeeded first — longest without a good
       fetch gets first claim on the budget.
    2. ``last_fetch_at`` ascending, never-attempted first. This is what makes the
       rotation actually rotate: every committee is stamped on every pass
       (including the ones that only fast-failed on an open circuit), so a
       committee that just consumed the budget carries the newest timestamp and
       falls to the back of its group next run. Without it, a committee that can
       *never* succeed would hold first place forever and simply relocate the
       starvation.
    3. Registry order, so the result is deterministic.

    Timestamps are compared as strings deliberately: SQLite has no timezone type,
    so a column can read back naive even though ``_now()`` is UTC-aware, and
    comparing a naive to an aware ``datetime`` raises. The stored format is
    lexicographically ordered anyway.
    """
    return (
        str(row.last_ok_at) if row.last_ok_at else _NEVER,
        str(row.last_fetch_at) if row.last_fetch_at else _NEVER,
        tiebreak,
    )


def enabled_committee_keys(db_path: str | None = None) -> list[str]:
    """Keys of the tracked committees (``enabled=1``)."""
    return [c.key for c in enabled_committees(db_path)]


def add_committee(
    *, key: str, name_ja: str, name_en: str, url: str, source: str,
    priority: int = 100, max_meeting: int | None = None, prefix: str | None = None,
    log_pages: tuple[str, ...] | list[str] | None = None, min_meeting: int | None = None,
    enabled: bool = True, db_path: str | None = None,
) -> bool:
    """Insert (or update) a user-added committee row by key. Returns True if newly
    created. ``key`` must be unique; re-adding an existing key updates its config
    fields. (The URL-deduping variant for the web UI is :func:`add_user_committee`.)
    """
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        is_new = row is None
        if row is None:
            row = PolicyCommittee(committee_key=key, user_added=True)
            session.add(row)
        row.name_ja, row.name_en = name_ja, name_en
        row.url, row.source = url, source
        row.priority = priority
        row.max_meeting, row.prefix = max_meeting, prefix
        row.log_pages = _log_pages_to_db(log_pages)
        row.min_meeting = min_meeting
        row.enabled = enabled
        return is_new


def set_committee_enabled(key: str, enabled: bool, db_path: str | None = None) -> bool:
    """Set a committee's tracked flag. Returns True if the row existed."""
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is None:
            return False
        row.enabled = bool(enabled)
        return True


def set_committee_archived(key: str, archived: bool, db_path: str | None = None) -> bool:
    """Mark a committee as concluded (or revive it). Archived committees are skipped
    by every fetch pass — detection and both backfills — so a closed committee stops
    consuming the daily crawl budget (and, for METI, stops tripping the WAF ladder on
    every run). Existing meetings/materials are kept and still render.

    Independent of ``enabled``: archiving does not untrack, and untracking does not
    stop detection. Returns True if the row existed.
    """
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is None:
            return False
        row.archived = bool(archived)
        return True


def set_committee_priority(key: str, priority: int, db_path: str | None = None) -> bool:
    """Set a committee's summarisation priority (the catch-up queue position; lower
    is summarised first). Persisted across ``sync_committees`` so a committee can
    "jump the queue permanently". Returns True if the row existed."""
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is None:
            return False
        row.priority = int(priority)
        return True


def delete_committee(key: str, db_path: str | None = None) -> bool:
    """Delete a **user-added** committee and all its meetings/materials.

    Refuses to delete code-config committees (returns False) — disable those
    instead so the registry can't drift from the code config.
    """
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is None or not row.user_added:
            return False
        session.query(PolicyMaterial).filter_by(committee_key=key).delete()
        session.query(PolicyMeeting).filter_by(committee_key=key).delete()
        session.delete(row)
        return True


def list_committees(db_path: str | None = None) -> list[dict]:
    """All catalog committees (enabled + disabled) as plain dicts, sorted by
    source, priority, key. Rows carry both ``key`` (web API/CLI callers) and
    ``committee_key`` (dashboard/discovery callers) for the same value."""
    with session_scope(db_path, commit=False) as session:
        rows = session.query(PolicyCommittee).all()
        out = [
            {
                "key": r.committee_key,
                "committee_key": r.committee_key,
                "source": r.source or "METI",
                "name_en": r.name_en or r.committee_key,
                "name_ja": r.name_ja or r.committee_key,
                "enabled": bool(r.enabled) if r.enabled is not None else True,
                "archived": bool(r.archived),
                "user_added": bool(r.user_added),
                "priority": r.priority if r.priority is not None else 100,
                "latest_meeting": r.latest_meeting,
                "url": r.url or "",
                # Fetch health (see set_committee_fetch_result). None = never recorded.
                "last_fetch_status": r.last_fetch_status,
                "last_fetch_kind": r.last_fetch_kind,
                "last_fetch_detail": r.last_fetch_detail,
                "last_fetch_url": r.last_fetch_url,
                "last_fetch_at": r.last_fetch_at,
                "last_ok_at": r.last_ok_at,
                "consecutive_failures": r.consecutive_failures or 0,
            }
            for r in rows
        ]
        out.sort(key=lambda x: (x["source"], x["priority"], x["key"]))
        return out


def _norm_url(u: str | None) -> str:
    """Normalise a committee URL for dedup: drop fragment/query + trailing
    ``index.html`` / slash, lowercased. So the config's ``…/saisei_kano/`` and an
    index's ``…/saisei_kano/index.html`` collapse to the same committee."""
    if not u:
        return ""
    u = u.split("#")[0].split("?")[0].strip()
    u = re.sub(r"index\.html$", "", u)
    return u.rstrip("/").lower()


def upsert_discovered_committees(items: list[dict], db_path: str | None = None) -> int:
    """Insert catalog rows for discovered committees not already known.

    *items* are dicts ``{key, name_ja, source, url[, prefix, max_meeting,
    log_pages, min_meeting]}``. New rows are ``enabled=0`` (visible in the catalog
    but not tracked) and ``user_added=0`` (system-discovered). An item whose
    normalised URL already exists is skipped, so a committee we already track (or
    already discovered) is never duplicated or downgraded; a key that collides with
    a *different* URL is disambiguated with a numeric suffix. Returns rows inserted.
    """
    with session_scope(db_path) as session:
        existing = session.query(PolicyCommittee).all()
        keys = {r.committee_key for r in existing}
        urls = {_norm_url(r.url) for r in existing if r.url}
        inserted = 0
        for it in items:
            nu = _norm_url(it.get("url"))
            if nu and nu in urls:
                continue
            key = base = it["key"]
            n = 2
            while key in keys:
                key = f"{base}_{n}"
                n += 1
            row = PolicyCommittee(
                committee_key=key,
                name_ja=it.get("name_ja") or "",
                name_en=it.get("name_en") or "",
                url=it.get("url") or "",
                source=it.get("source") or "METI",
                priority=100,
                max_meeting=it.get("max_meeting"),
                prefix=it.get("prefix"),
                log_pages=_log_pages_to_db(it.get("log_pages")),
                min_meeting=it.get("min_meeting"),
            )
            row.enabled = False   # discovered → visible but not tracked
            row.user_added = False  # system-discovered (vs a manual add)
            session.add(row)
            keys.add(key)
            if nu:
                urls.add(nu)
            inserted += 1
        return inserted


def add_user_committee(item: dict, *, enabled: bool = True, db_path: str | None = None) -> dict:
    """Insert one manually-added committee (the add-by-URL path).

    *item* is a dict ``{key, name_ja, source, url[, prefix]}``. Unlike
    :func:`upsert_discovered_committees`, the row is inserted ``user_added=1``
    and (by default) already tracked. If the normalised URL is already in the
    catalog the existing row is returned untouched — the caller can offer
    "already in catalog — track it?" instead of silently duplicating.
    Returns ``{"key", "existing"}``.
    """
    with session_scope(db_path) as session:
        nu = _norm_url(item.get("url"))
        if nu:
            for r in session.query(PolicyCommittee).all():
                if _norm_url(r.url) == nu:
                    return {"key": r.committee_key, "existing": True}
        keys = {r.committee_key for r in session.query(PolicyCommittee.committee_key)}
        key = base = item["key"]
        n = 2
        while key in keys:
            key = f"{base}_{n}"
            n += 1
        row = PolicyCommittee(
            committee_key=key,
            name_ja=item.get("name_ja") or "",
            name_en=item.get("name_en") or "",
            url=item.get("url") or "",
            source=item.get("source") or "METI",
            priority=100,
            prefix=item.get("prefix"),
        )
        row.enabled = bool(enabled)
        row.user_added = True
        session.add(row)
        return {"key": key, "existing": False}


# ── Generation queue (dashboard "Generate summary" when auth is stale) ────────
def request_generation(key: str, meeting_num: int, db_path: str | None = None) -> bool:
    """Flag one meeting for summarisation. Returns True if the row exists/was flagged.

    On an already-``done`` meeting this means "write it again, at the front": the row
    also gets ``resummarise_requested``, since a done meeting is outside the pending
    worklist and a bare ``gen_requested`` on it would never be picked up.
    """
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is None:
            return False
        m.gen_requested = True
        if m.state == "done":
            m.resummarise_requested = True
        return True


def clear_generation_request(key: str, meeting_num: int, db_path: str | None = None, *,
                             withdraw_resummarise: bool = False) -> None:
    """Clear a meeting's generation-requested flag (once it's been summarised).

    ``resummarise_requested`` is left alone by default: the pipeline calls this after
    every attempt, including a failed one, and a failed re-run must stay queued for the
    next round. *withdraw_resummarise* is for a person taking the meeting off the queue.
    """
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is not None and m.gen_requested:
            m.gen_requested = False
        if m is not None and withdraw_resummarise and m.resummarise_requested:
            m.resummarise_requested = False


def get_committee(key: str, db_path: str | None = None) -> PolicyCommittee | None:
    # Read-only, and the detached row's attributes are read after close — a
    # commit would expire them (expire_on_commit) and break callers.
    with session_scope(db_path, commit=False) as session:
        return session.get(PolicyCommittee, key)


# ── Detection writes ─────────────────────────────────────────────────────────
def known_meeting_nums(key: str, db_path: str | None = None) -> set[int]:
    """Meeting numbers already recorded for a committee (any state)."""
    with session_scope(db_path, commit=False) as session:
        rows = session.query(PolicyMeeting.meeting_num).filter_by(committee_key=key).all()
        return {r[0] for r in rows}


def record_meeting(key: str, meeting_num: int, materials: list[Material] | None,
                   db_path: str | None = None) -> bool:
    """Upsert one meeting + its materials. Returns True if the meeting was new.

    Existing meetings keep their lifecycle ``state``; new materials (e.g. a
    late-arriving 議事録) are added without disturbing already-ingested ones.
    """
    with session_scope(db_path) as session:
        meeting = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        is_new = meeting is None
        if meeting is None:
            meeting = PolicyMeeting(committee_key=key, meeting_num=meeting_num, state="detected")
            session.add(meeting)

        mats = materials or []
        if mats:
            existing_ids = {
                r[0]
                for r in session.query(PolicyMaterial.pdf_id)
                .filter_by(committee_key=key)
                .filter(PolicyMaterial.meeting_num == meeting_num)
                .all()
            }
            for m in mats:
                if m.pdf_id in existing_ids:
                    continue
                session.add(
                    PolicyMaterial(
                        committee_key=key,
                        meeting_num=meeting_num,
                        pdf_id=m.pdf_id,
                        kind=m.kind,
                        url=m.url,
                        title=m.title,
                        status="detected",
                        first_seen_at=_now(),
                    )
                )
            kinds = {m.kind for m in mats}
            if "minutes" in kinds:
                meeting.has_minutes = True
            if "compilation" in kinds:
                meeting.has_torimatome = True
        meeting.updated_at = _now()
        return is_new


# A document of one of these kinds arriving after a meeting was summarised makes
# that briefing incomplete. Appendices are left out: they are only ingested when the
# source budget has room, so one arriving late is not worth a quota slot on its own.
LATE_REQUEUE_KINDS = ("minutes", "brief", "compilation", "handout", "agenda")

# States in which a meeting's document list is safe to refresh. The in-flight ones
# (downloading / ingesting / generating) have a notebook being built from the list as
# it stands, so it is left alone until that attempt resolves.
_REFRESHABLE_STATES = ("done", "detected", "error")


def recent_meeting_nums(key: str, since: date, db_path: str | None = None) -> list[int]:
    """Meetings of *key* held on/after *since* whose document list may still grow,
    newest first.

    An undated meeting falls back to the day it was detected, so a committee whose
    index carries no dates still gets its latest meetings refreshed.
    """
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyMeeting.meeting_num, PolicyMeeting.meeting_date,
                          PolicyMeeting.detected_at)
            .filter(PolicyMeeting.committee_key == key,
                    PolicyMeeting.state.in_(_REFRESHABLE_STATES))
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
    out = []
    for num, held, detected in rows:
        when = held or (detected.date() if detected else None)
        if when is not None and when >= since:
            out.append(num)
    return out


def watch_meeting_nums(
    key: str,
    today: date,
    *,
    horizon_days: int = 90,
    interval_days: int = 7,
    db_path: str | None = None,
) -> list[int]:
    """Summarised meetings of *key* still worth re-checking for late minutes, newest first.

    A meeting qualifies when it is ``done``, has **neither minutes nor a brief** on
    file, and either

    * has never had its document list re-read (``materials_checked_at`` NULL) — one
      look regardless of age, because lists were frozen when a meeting was first
      seen, so an old meeting may long since have its minutes; or
    * is within *horizon_days* of its date **and** was last read at least
      *interval_days* ago — a slow weekly poll that stops after the horizon, so a
      committee that never publishes minutes costs ~13 fetches per meeting, once.

    Tracked (enabled) committees only: nobody reads a briefing of an untracked one,
    and a re-run would never be scheduled for it anyway.
    """
    from sqlalchemy import exists

    with session_scope(db_path, commit=False) as session:
        committee = session.get(PolicyCommittee, key)
        if committee is not None and committee.enabled is False:
            return []

        def _has(kind: str):
            return exists().where(
                PolicyMaterial.committee_key == PolicyMeeting.committee_key,
                PolicyMaterial.meeting_num == PolicyMeeting.meeting_num,
                PolicyMaterial.kind == kind,
            )

        rows = (
            session.query(PolicyMeeting.meeting_num, PolicyMeeting.meeting_date,
                          PolicyMeeting.detected_at, PolicyMeeting.materials_checked_at)
            .filter(PolicyMeeting.committee_key == key, PolicyMeeting.state == "done",
                    ~_has("minutes"), ~_has("brief"))
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
    horizon = today - timedelta(days=horizon_days)
    due = datetime.combine(today, datetime.min.time(), tzinfo=UTC) - timedelta(days=interval_days)
    out = []
    for num, held, detected, checked in rows:
        if checked is None:
            out.append(num)
            continue
        when = held or (detected.date() if detected else None)
        if when is None or when < horizon:
            continue
        if checked.replace(tzinfo=checked.tzinfo or UTC) <= due:
            out.append(num)
    return out


def add_late_materials(key: str, meeting_num: int, materials: list[Material],
                       db_path: str | None = None) -> dict:
    """Merge a re-enumerated document list into an already-known meeting.

    Returns ``{"added": n, "requeued": bool}``. Only documents not yet on file are
    added, so a re-fetch that finds nothing new changes nothing — in particular
    ``updated_at``, which the UI reads as "when this was summarised".

    A ``done`` meeting that gains a minutes / brief / compilation / handout / agenda
    document gets ``resummarise_requested``: its briefing was written without that
    paper. It **stays ``done``** — the existing briefing remains visible, just thinner
    than it could be — and the next ``policy run`` writes a new one behind any
    never-summarised meeting, then clears the flag.

    Every successful listing stamps ``materials_checked_at``, whether or not it found
    anything, so the re-check schedule can tell "looked and found nothing" from
    "never looked".
    """
    with session_scope(db_path) as session:
        meeting = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if meeting is None:
            return {"added": 0, "requeued": False}
        known = {
            r[0]
            for r in session.query(PolicyMaterial.pdf_id)
            .filter_by(committee_key=key)
            .filter(PolicyMaterial.meeting_num == meeting_num)
            .all()
        }
        meeting.materials_checked_at = _now()
        added: list[Material] = []
        for m in materials:
            if m.pdf_id in known:
                continue
            known.add(m.pdf_id)
            added.append(m)
            session.add(PolicyMaterial(
                committee_key=key, meeting_num=meeting_num, pdf_id=m.pdf_id,
                kind=m.kind, url=m.url, title=m.title, status="detected",
                first_seen_at=_now(),
            ))
        if not added:
            return {"added": 0, "requeued": False}
        kinds = {m.kind for m in added}
        if "minutes" in kinds:
            meeting.has_minutes = True
        if "compilation" in kinds:
            meeting.has_torimatome = True
        requeue = meeting.state == "done" and any(k in LATE_REQUEUE_KINDS for k in kinds)
        if requeue:
            meeting.resummarise_requested = True
            meeting.retry_count = 0  # a fresh reason; earlier failures no longer count
        return {"added": len(added), "requeued": requeue}


def reclassify_materials(db_path: str | None = None, dry_run: bool = False) -> list[dict]:
    """Re-run :func:`classify_material` over every stored document.

    ``record_meeting`` never revisits a document once it is on file, so rows typed by
    an earlier classifier keep their old ``kind`` forever. Pure DB work — no fetch.
    Returns one ``{committee_key, meeting_num, pdf_id, old, new, state}`` dict per
    document whose kind changes; with *dry_run* nothing is written.
    """
    from repower.policy.scraper import classify_material

    changes: list[dict] = []
    with session_scope(db_path, commit=not dry_run) as session:
        states = {
            (c, n): s
            for c, n, s in session.query(
                PolicyMeeting.committee_key, PolicyMeeting.meeting_num, PolicyMeeting.state
            )
        }
        for m in session.query(PolicyMaterial).all():
            new = classify_material(m.title or "", m.url or "")
            if new == m.kind:
                continue
            changes.append({
                "committee_key": m.committee_key, "meeting_num": m.meeting_num,
                "pdf_id": m.pdf_id, "old": m.kind, "new": new,
                "state": states.get((m.committee_key, m.meeting_num)),
            })
            if not dry_run:
                m.kind = new
    return changes


def queue_resummarise(meetings: list[tuple[str, int]], db_path: str | None = None) -> dict:
    """Flag summarised meetings for a new briefing (``resummarise_requested``).

    Only ``done`` meetings of **tracked** committees: the flag is what the run reads, and a
    run on ``--committee all`` skips untracked ones, so flagging them would only light the
    "update queued" chip for work that never starts. Returns
    ``{"queued": [...], "untracked": [...]}`` of ``(committee_key, meeting_num)``; anything
    that is not ``done`` (it changed state since the caller looked) is silently left alone.
    The retry count is reset: a fresh reason, so earlier failures no longer count against it.
    """
    queued: list[tuple[str, int]] = []
    untracked: list[tuple[str, int]] = []
    with session_scope(db_path) as session:
        tracked = {c.committee_key: c.enabled is not False for c in session.query(PolicyCommittee)}
        for key, num in meetings:
            m = (session.query(PolicyMeeting)
                 .filter_by(committee_key=key, meeting_num=num).one_or_none())
            if m is None or m.state != "done":
                continue
            if not tracked.get(key, True):
                untracked.append((key, num))
                continue
            m.resummarise_requested = True
            m.retry_count = 0
            queued.append((key, num))
    return {"queued": queued, "untracked": untracked}


def set_committee_checked(key: str, db_path: str | None = None) -> None:
    """Record that a detection pass ran (used for the dashboard / freshness)."""
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is None:
            row = PolicyCommittee(committee_key=key)
            session.add(row)
        row.last_checked = _now()


# Keep the event log bounded: it rides the Hugging Face sync with the rest of the
# DB, and only the recent shape of a committee's failures is decision-relevant.
FETCH_EVENTS_PER_COMMITTEE = 20


def set_committee_fetch_result(
    key: str,
    status: str,
    *,
    kind: str | None = None,
    detail: str | None = None,
    url: str | None = None,
    db_path: str | None = None,
) -> None:
    """Record the outcome of one fetch attempt for *key* — success **or** failure.

    Called on every detection path. ``last_checked`` alone could not express this:
    it was written only when a committee succeeded or 304'd, so a blocked
    committee's timestamp simply went stale, which reads identically to one that
    was never scheduled. Here an error still stamps ``last_fetch_at``, so
    "attempted and failed at T" and "never attempted" are finally distinct.

    ``consecutive_failures`` separates a flaky host from a dead URL, and
    ``last_ok_at`` preserves the last time the committee genuinely worked (which
    an error must not overwrite). Also appends to ``policy_fetch_event``.
    """
    now = _now()
    ok = status != "error"
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is None:
            row = PolicyCommittee(committee_key=key)
            session.add(row)
        row.last_fetch_status = status
        row.last_fetch_kind = None if ok else kind
        row.last_fetch_detail = None if ok else (detail or "")[:500]
        row.last_fetch_url = None if ok else url
        row.last_fetch_at = now
        if ok:
            row.last_ok_at = now
            row.consecutive_failures = 0
        else:
            row.consecutive_failures = (row.consecutive_failures or 0) + 1

        session.add(PolicyFetchEvent(
            committee_key=key, at=now, status=status,
            kind=None if ok else kind,
            detail=None if ok else (detail or "")[:500],
            url=url,
        ))
        _trim_fetch_events(session, key)


def _trim_fetch_events(session, key: str) -> None:
    """Keep only the newest :data:`FETCH_EVENTS_PER_COMMITTEE` events for *key*."""
    ids = [
        r.id for r in session.query(PolicyFetchEvent.id)
        .filter(PolicyFetchEvent.committee_key == key)
        .order_by(PolicyFetchEvent.at.desc(), PolicyFetchEvent.id.desc())
        .offset(FETCH_EVENTS_PER_COMMITTEE)
        .all()
    ]
    if ids:
        (session.query(PolicyFetchEvent)
         .filter(PolicyFetchEvent.id.in_(ids))
         .delete(synchronize_session=False))


def fetch_events(key: str | None = None, limit: int = 50,
                 db_path: str | None = None) -> list[dict]:
    """Recent fetch attempts, newest first — the history behind a committee's
    current status (is this host flaky, or has this URL been dead for weeks?)."""
    with session_scope(db_path, commit=False) as session:
        q = session.query(PolicyFetchEvent)
        if key:
            q = q.filter(PolicyFetchEvent.committee_key == key)
        rows = q.order_by(PolicyFetchEvent.at.desc(), PolicyFetchEvent.id.desc()).limit(limit).all()
        return [
            {
                "committee_key": r.committee_key,
                "at": r.at,
                "status": r.status,
                "kind": r.kind,
                "detail": r.detail,
                "url": r.url,
            }
            for r in rows
        ]


def prune_fetch_events(older_than_days: float = 90, db_path: str | None = None) -> int:
    """Drop fetch events older than *older_than_days*. Returns rows deleted.

    Mirrors ``http_cache.prune_cache``'s retention so the two observability
    stores age out together and neither grows without bound in the synced DB.
    """
    from datetime import timedelta

    cutoff = _now() - timedelta(days=older_than_days)
    with session_scope(db_path) as session:
        n = (session.query(PolicyFetchEvent)
             .filter(PolicyFetchEvent.at < cutoff)
             .delete(synchronize_session=False))
        if n:
            logger.info("policy: pruned %d fetch event(s) older than %s days", n, older_than_days)
        return n


# ── Worklist / lifecycle ─────────────────────────────────────────────────────
def pending_meetings(key: str | None = None, db_path: str | None = None,
                     only_enabled: bool = False, breadth_first: bool = False,
                     include_resummarise: bool = False,
                     today: date | None = None,
                     ready_only: bool = True) -> list[dict]:
    """Meetings still needing work, in summarisation order, as plain dicts.

    Ordered by: **user-requested first** (a dashboard "Generate summary" that was
    queued), then committee **priority** (so a quota-bounded ``policy run`` drains
    high-priority committees first), then committee key to keep a committee's
    meetings grouped, then newest meeting first within a committee.

    With ``breadth_first`` the order instead interleaves committees by how deep into
    each one's backlog a meeting sits: every committee's **newest** pending meeting
    (in priority order) comes before any committee's second-newest, and so on. This
    spreads a small daily NotebookLM quota across committees — getting the latest
    meeting of each tracked committee current first — instead of draining a single
    committee's history. ``gen_requested`` still wins over everything.

    Includes everything not yet ``done``, plus ``error`` rows that have failed
    fewer than ``MAX_RETRIES`` times (so transient failures are retried). With
    ``include_resummarise`` it also returns ``done`` meetings flagged
    ``resummarise_requested`` (``"resummarise": True``), held to the same retry cap.
    Off by default because "pending" is also a *count* (status tables, the backlog
    badge) that should keep meaning "no briefing yet".

    **Readiness.** With ``ready_only`` (the default) a never-summarised meeting that is not
    yet worth a briefing — ``upcoming`` or ``awaiting``, see :func:`meeting_readiness` — is
    left out, so it neither takes a quota slot nor counts as backlog. A meeting someone
    asked for (``gen_requested``) and a ``done`` meeting flagged for a new briefing are
    exempt. Every row carries its ``"readiness"``; ``ready_only=False`` returns them all
    for callers that report on the unready ones.

    **Recency tier.** Breadth-first only: meetings dated within the trailing
    ``RECENT_WINDOW_MONTHS`` of *today* (default today in JST; undated counts as old) all come
    before any older one, and backlog depth is measured *within* a tier. So a committee whose
    recent meetings are already summarised stops taking the first slot every day with its oldest
    leftovers — current meetings of every committee go first, in priority order, and the old
    backlog then drains the same way. It is a tier, not a cut-off: nothing is ever excluded.
    ``gen_requested`` still wins over it.

    **Where an update sits.** Breadth-first (the daily run): after every committee's
    *newest* pending meeting, but **ahead of any committee's deeper backlog** — a
    meeting that just got its minutes is worth more than the fifth-newest never-summarised
    one, which at a few a day it would otherwise wait ~weeks behind (it ranked last of
    ~290 when this was measured). Depth-first (a single committee): after every pending
    meeting, unchanged — a backfill drains history, and an update is not part of it. With
    ``only_enabled`` the result is restricted to tracked (``enabled=1``) committees
    — used by ``policy run --committee all`` so disabling a committee removes it
    from the daily worklist.
    """
    with session_scope(db_path, commit=False) as session:
        q = session.query(PolicyMeeting).filter(
            PolicyMeeting.state != "done",
            or_(
                PolicyMeeting.state != "error",
                func.coalesce(PolicyMeeting.retry_count, 0) < MAX_RETRIES,
            ),
        )
        if key:
            q = q.filter_by(committee_key=key)
        rows = q.all()
        if include_resummarise:
            uq = session.query(PolicyMeeting).filter(
                PolicyMeeting.state == "done",
                PolicyMeeting.resummarise_requested == True,  # noqa: E712
                func.coalesce(PolicyMeeting.retry_count, 0) < MAX_RETRIES,
            )
            if key:
                uq = uq.filter_by(committee_key=key)
            rows = rows + uq.all()
        # Priority + enabled live on the committee row; read them once and order in Python.
        coms = {c.committee_key: c for c in session.query(PolicyCommittee).all()}
        if only_enabled:
            rows = [m for m in rows if getattr(coms.get(m.committee_key), "enabled", True)]

        # Readiness is judged on the document kinds on file, read in one query for the
        # committees involved. A summarised meeting is never re-judged: it already passed.
        kinds_by: dict[tuple[str, int], set[str]] = {}
        unsettled = {m.committee_key for m in rows if m.state != "done"}
        if unsettled:
            for ck, num, kind in (
                session.query(PolicyMaterial.committee_key, PolicyMaterial.meeting_num,
                               PolicyMaterial.kind)
                .filter(PolicyMaterial.committee_key.in_(unsettled))
            ):
                kinds_by.setdefault((ck, num), set()).add(kind)
        day = today or today_jst()
        readiness: dict[int, str] = {
            m.id: READY if m.state == "done"
            else meeting_readiness(m.meeting_date, kinds_by.get((m.committee_key, m.meeting_num), ()),
                                   today=day, checked_at=m.materials_checked_at)
            for m in rows
        }
        if ready_only:
            rows = [m for m in rows if readiness[m.id] == READY or m.gen_requested]

        def _prio(ck: str) -> int:
            c = coms.get(ck)
            if c is not None and c.priority is not None:
                return c.priority
            return committee_priority(ck)

        # Depth of each meeting within its committee's backlog (0 = that committee's
        # newest pending meeting). Only computed for the breadth-first interleave;
        # when off it stays empty so the sort key below is a constant 0 and the
        # ordering collapses to the original priority-then-key behaviour.
        depth: dict[int, int] = {}
        recent_from = _months_before(day, RECENT_WINDOW_MONTHS)

        def _age_tier(m: PolicyMeeting) -> int:
            """0 for a meeting inside the recency window, 1 for an older (or undated) one."""
            if not breadth_first:
                return 0
            d = m.meeting_date
            return 0 if d is not None and d >= recent_from else 1

        if breadth_first:
            by_com: dict[tuple[str, int], list[PolicyMeeting]] = {}
            for m in rows:
                if m.state == "done":
                    continue  # an upgrade is not backlog depth: it must not push a new meeting back
                by_com.setdefault((m.committee_key, _age_tier(m)), []).append(m)
            for ms in by_com.values():
                for r, m in enumerate(sorted(ms, key=lambda x: -x.meeting_num)):
                    depth[m.id] = r

        def _tier(m: PolicyMeeting) -> float:
            """Backlog depth for a pending meeting; a fixed slot for an update (see docstring)."""
            if m.state == "done":
                return UPDATE_DEPTH if breadth_first else 1
            return depth.get(m.id, 0)

        rows.sort(key=lambda m: (
            0 if m.gen_requested else 1,  # user-requested ("Generate summary") first
            _age_tier(m),                 # breadth-first: the recency window before older backlog
            _tier(m),                     # breadth-first: newest-of-each committee, updates, deeper…
            _prio(m.committee_key),
            m.committee_key,
            -m.meeting_num,
        ))
        return [
            {
                "id": m.id,
                "committee_key": m.committee_key,
                "meeting_num": m.meeting_num,
                "state": m.state,
                "has_minutes": m.has_minutes,
                "has_torimatome": m.has_torimatome,
                "gen_requested": bool(m.gen_requested),
                "resummarise": m.state == "done",
                "readiness": readiness[m.id],
            }
            for m in rows
        ]


def queue_snapshot(
    db_path: str | None = None,
    *,
    cap: int = DAILY_RUN_CAP,
    now: datetime | None = None,
    recent_days: int = 7,
    max_items: int = 100,
    max_recent: int = 40,
) -> dict:
    """What the daily run will work through next, and what it has just worked through.

    ``items`` is :func:`pending_meetings` exactly as ``policy run --committee all`` calls
    it (tracked committees, breadth-first, upgrades included) — the same function, so the
    view cannot drift from the run — numbered from 1. The first *cap* are what one daily
    run takes. Each carries a ``kind``: ``update`` (summarised; a late paper means it is
    being written again), ``retry`` (errored, under the retry cap) or ``new`` (no briefing
    yet), plus ``requested`` when someone moved it to the front.

    It is the *expected* order: a run also skips a committee whose host is cooling down and
    stops early on a rate limit. ``totals`` count the whole worklist. ``items`` holds the
    first *max_items* by rank **plus every update, retry and moved-to-front meeting whatever
    its rank** — a long backlog of ordinary new meetings is a count, not a list, but the rare
    ones an operator filters for must not be cut off behind it (an update can rank well past
    a plain cap, and the "Update" filter would then find nothing). Ranks are kept, so they
    can be non-contiguous; ``truncated`` is how many new meetings are left out.

    ``recent`` is what left the queue in the last *recent_days*, newest first, with
    ``kind`` ``update`` or ``new``. Rows summarised before ``summarised_at`` existed fall
    back to a done meeting touched recently with a recorded generation time, and carry
    ``kind: None`` — "summarised", but not known to be first or repeat.
    """
    explicit_now = now is not None
    now = now or _now()
    work = pending_meetings(db_path=db_path, only_enabled=True, breadth_first=True,
                            include_resummarise=True, today=now.date() if explicit_now else None)
    with session_scope(db_path, commit=False) as session:
        def _kind(w: dict) -> str:
            return "update" if w["state"] == "done" else "retry" if w["state"] == "error" else "new"

        ranked = list(enumerate(work, start=1))
        listed = [(r, w) for r, w in ranked if r <= max_items or _kind(w) != "new" or w["gen_requested"]]
        ids = [w["id"] for _, w in listed]
        extra = {
            m.id: m for m in session.query(PolicyMeeting).filter(PolicyMeeting.id.in_(ids)).all()
        } if ids else {}
        items = []
        for rank, w in listed:
            m = extra[w["id"]]
            kind = _kind(w)
            items.append({
                "rank": rank, "com": w["committee_key"], "num": w["meeting_num"],
                "date": str(m.meeting_date)[:10] if m.meeting_date else None,
                "kind": kind, "requested": bool(w["gen_requested"]),
                "state": w["state"], "retries": m.retry_count or 0,
            })

        cutoff = now - timedelta(days=recent_days)
        rows = (
            session.query(PolicyMeeting)
            .filter(PolicyMeeting.state == "done")
            .filter(or_(
                PolicyMeeting.summarised_at >= cutoff,
                (PolicyMeeting.summarised_at.is_(None))
                & (PolicyMeeting.updated_at >= cutoff)
                & (PolicyMeeting.gen_seconds.isnot(None)),
            ))
            .all()
        )

        def _when(m: PolicyMeeting) -> datetime:
            return m.summarised_at or m.updated_at or datetime.min  # both set for any row selected above

        rows.sort(key=_when, reverse=True)
        recent = [{
            "com": m.committee_key, "num": m.meeting_num, "at": str(_when(m)),
            "kind": ("update" if m.resummarised_at else "new") if m.summarised_at else None,
        } for m in rows[:max_recent]]

    totals = {"new": 0, "update": 0, "retry": 0, "requested": 0}
    by_com: dict[str, dict[str, int]] = {}
    for w in work:
        kind = "update" if w["state"] == "done" else "retry" if w["state"] == "error" else "new"
        totals[kind] += 1
        totals["requested"] += int(bool(w["gen_requested"]))
        c = by_com.setdefault(w["committee_key"], {"new": 0, "update": 0, "retry": 0, "requested": 0})
        c[kind] += 1
        c["requested"] += int(bool(w["gen_requested"]))
    return {
        "cap": cap,
        "total": len(work),
        "totals": totals,
        # Over the whole worklist, not the capped `items`: "which committees are queued"
        # must not depend on how far down the list happens to be cut. Biggest first.
        "byCom": dict(sorted(
            by_com.items(), key=lambda kv: (-sum(kv[1][k] for k in ("new", "update", "retry")), kv[0]))),
        "items": items,
        "truncated": max(0, len(work) - len(items)),
        "recent": recent,
        "recentDays": recent_days,
    }


def reset_unready_summaries(db_path: str | None = None, *, today: date | None = None) -> dict:
    """Put back to ``detected`` the meetings that were summarised or failed *before* they
    were ready, so the readiness gate can hold them until they are.

    Two cases, both left by runs from before the gate (or by a date that arrived only after
    the summary):

    * ``done`` and dated **today or later** — a briefing of the papers posted ahead of a
      meeting that has not happened. Its briefing and digest are cleared (they describe the
      wrong thing and must not be shown or folded into the committee synthesis), its flags
      and retry count reset; the per-meeting notebook id is kept so the next run deletes it.
    * ``error`` with ``no_sources`` that is still not ready — an upcoming meeting with no
      papers is "not yet", not a failure; the red row and the spent retry go away.

    Idempotent and cheap, so ``detect`` runs it every pass — which is also what carries the
    fix through the Hugging Face round trip. Returns ``{"unsummarised": n, "cleared": n}``.
    """
    day = today or today_jst()
    out = {"unsummarised": 0, "cleared": 0}
    with session_scope(db_path) as session:
        kinds_by: dict[tuple[str, int], set[str]] = {}
        for ck, num, kind in session.query(PolicyMaterial.committee_key,
                                           PolicyMaterial.meeting_num, PolicyMaterial.kind):
            kinds_by.setdefault((ck, num), set()).add(kind)
        rows = (session.query(PolicyMeeting)
                .filter(or_(
                    (PolicyMeeting.state == "done") & (PolicyMeeting.meeting_date >= day),
                    (PolicyMeeting.state == "error") & (PolicyMeeting.quality_flag == "no_sources"),
                )).all())
        for m in rows:
            if meeting_readiness(m.meeting_date, kinds_by.get((m.committee_key, m.meeting_num), ()),
                                 today=day, checked_at=m.materials_checked_at) == READY:
                continue
            was_done = m.state == "done"
            m.state = "detected"
            m.retry_count = 0
            m.quality_flag = None
            m.last_error = None
            m.last_error_at = None
            if was_done:
                m.briefing_md = None
                m.digest_en_json = None
                m.citations_json = None
                m.report_task_id = None
                m.summarised_at = None
                m.resummarised_at = None
                m.resummarise_requested = False
                m.synth_done = False
                out["unsummarised"] += 1
            else:
                out["cleared"] += 1
            m.updated_at = _now()
    return out


def mark_materials_checked(key: str, meeting_num: int, db_path: str | None = None) -> None:
    """Record that the meeting's document list was just read from its page (see
    :func:`meeting_readiness`: it is what turns "no documents on file" from *unknown* into
    *looked, nothing yet*)."""
    with session_scope(db_path) as session:
        m = (session.query(PolicyMeeting)
             .filter_by(committee_key=key, meeting_num=meeting_num).one_or_none())
        if m is not None:
            m.materials_checked_at = _now()


def meeting_gate(key: str, meeting_num: int, kinds, *, today: date | None = None,
                 db_path: str | None = None) -> tuple[str, bool]:
    """``(readiness, requested)`` for one meeting, judged on *kinds* (its documents now).

    The check ``summarize_meeting`` repeats at the point of spending quota, in case the
    worklist it came from is stale. A ``done`` meeting is always ``ready`` (it already
    passed, and a re-write is a deliberate upgrade); *requested* is ``gen_requested`` — a
    person asked for this one, which overrides the gate.
    """
    with session_scope(db_path, commit=False) as session:
        m = (session.query(PolicyMeeting)
             .filter_by(committee_key=key, meeting_num=meeting_num).one_or_none())
        if m is None:
            return AWAITING, False
        if m.state == "done":
            return READY, bool(m.gen_requested)
        return (meeting_readiness(m.meeting_date, kinds, today=today or today_jst(),
                                  checked_at=m.materials_checked_at),
                bool(m.gen_requested))


def meeting_materials(key: str, meeting_num: int, db_path: str | None = None) -> list[dict]:
    """All materials for a meeting, as plain dicts (id, pdf_id, kind, url, title)."""
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyMaterial)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .all()
        )
        return [
            {"id": r.id, "pdf_id": r.pdf_id, "kind": r.kind, "url": r.url, "title": r.title,
             "status": r.status, "nblm_source_id": r.nblm_source_id}
            for r in rows
        ]


def set_material_state(key: str, pdf_id: str, db_path: str | None = None, **fields) -> None:
    """Patch one material row (``status``, ``nblm_source_id``, ...).

    ``policy_material.status`` and ``nblm_source_id`` were declared from the start
    and never written, so every document read ``detected`` forever — which meant
    nothing recorded whether a meeting's briefing had actually seen its papers.
    Written per document by the pipeline, and read back as the "N of M ingested"
    count in the Manage status table.
    """
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMaterial)
            .filter_by(committee_key=key, pdf_id=pdf_id)
            .one_or_none()
        )
        if m is None:
            return
        for k, v in fields.items():
            setattr(m, k, v)


def forget_staged_materials(key: str, meeting_num: int, db_path: str | None = None) -> None:
    """Reset ``downloaded`` materials of one meeting back to ``detected``.

    Called when the staged files are discarded. ``downloaded`` is a claim about what
    is on disk, and the next attempt's resume check reads the disk — so leaving the
    column saying ``downloaded`` after a wipe makes the status table report progress
    that no longer exists. ``ingested`` rows are left alone: that did happen.
    """
    with session_scope(db_path) as session:
        for m in (
            session.query(PolicyMaterial)
            .filter_by(committee_key=key, meeting_num=meeting_num, status="downloaded")
            .all()
        ):
            m.status = "detected"


def meetings_for_synthesis(key: str, db_path: str | None = None) -> list[dict]:
    """Done meetings with a briefing not yet folded into the committee synthesis
    (oldest first).

    Selection is by the per-meeting ``synth_done`` flag rather than a single
    high-water mark, so backfilled / out-of-order meetings (summarised after a
    newer one) are still added to the synthesis instead of being skipped.
    """
    with session_scope(db_path, commit=False) as session:
        q = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, state="done")
            .filter(PolicyMeeting.briefing_md.isnot(None))
            .filter(or_(PolicyMeeting.synth_done.is_(None), PolicyMeeting.synth_done == False))  # noqa: E712
            .order_by(PolicyMeeting.meeting_num.asc())
        )
        return [{"meeting_num": m.meeting_num, "briefing_md": m.briefing_md} for m in q.all()]


def mark_synthesized(key: str, meeting_num: int, db_path: str | None = None) -> None:
    """Flag a meeting's briefing as folded into the committee synthesis notebook."""
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is not None:
            m.synth_done = True


def reset_synthesized(key: str, meeting_num: int, db_path: str | None = None) -> None:
    """Un-flag a meeting so its briefing is folded into the synthesis again.

    Used when a meeting is deliberately re-summarised: the copy already in the
    synthesis notebook was written from the old briefing, so leaving the flag set
    would keep the committee overview quoting a summary its meeting no longer has.
    """
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is not None and m.synth_done:
            m.synth_done = False


def synthesized_meeting_nums(key: str, db_path: str | None = None) -> list[int]:
    """Meeting numbers whose briefings are already folded into the committee
    synthesis notebook (``synth_done``), ascending."""
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyMeeting.meeting_num)
            .filter_by(committee_key=key)
            .filter(PolicyMeeting.synth_done == True)  # noqa: E712
            .order_by(PolicyMeeting.meeting_num.asc())
            .all()
        )
        return [r[0] for r in rows]


def stalled_synthesis_committees(db_path: str | None = None,
                                 only_enabled: bool = False) -> list[str]:
    """Committee keys whose synthesis notebook has briefings folded in
    (``synth_done`` meetings) but no stored synthesis (``running_summary_md``
    is NULL) — an earlier run was interrupted (rate limit / crash) between
    adding sources and generating the report. Nothing is "new" for these
    committees, so without an explicit sweep they would never be retried."""
    with session_scope(db_path, commit=False) as session:
        q = (
            session.query(PolicyCommittee.committee_key)
            .filter(PolicyCommittee.synthesis_notebook_id.isnot(None))
            .filter(PolicyCommittee.running_summary_md.is_(None))
            .join(PolicyMeeting, PolicyMeeting.committee_key == PolicyCommittee.committee_key)
            .filter(PolicyMeeting.synth_done == True)  # noqa: E712
        )
        if only_enabled:
            q = q.filter(PolicyCommittee.enabled == True)  # noqa: E712
        return sorted({r[0] for r in q.all()})


def recent_done_meetings(since_days: int, db_path: str | None = None) -> list[dict]:
    """Meetings that reached ``done`` within the last ``since_days`` (newest first)."""
    from datetime import timedelta

    with session_scope(db_path, commit=False) as session:
        cutoff = _now() - timedelta(days=since_days)
        rows = (
            session.query(PolicyMeeting)
            .filter_by(state="done")
            .filter(PolicyMeeting.updated_at >= cutoff)
            .order_by(PolicyMeeting.updated_at.desc())
            .all()
        )
        return [
            {
                "committee_key": m.committee_key,
                "meeting_num": m.meeting_num,
                "has_torimatome": m.has_torimatome,
                "digest_en_json": m.digest_en_json,
            }
            for m in rows
        ]


def meetings_for_week(
    held_from: date, held_to: date, db_path: str | None = None,
    *, summarised_since: datetime | None = None,
) -> list[dict]:
    """Meetings *held* ``held_from..held_to`` (inclusive, by ``meeting_date``).

    With ``summarised_since``, only those whose summary landed at or after it — the
    weekly email's "summaries now available" catch-up for meetings held before the
    week. Undated meetings never match: when a meeting was held is the whole point.
    """
    with session_scope(db_path, commit=False) as session:
        q = session.query(PolicyMeeting).filter(
            PolicyMeeting.meeting_date >= held_from, PolicyMeeting.meeting_date <= held_to,
        )
        if summarised_since is not None:
            q = q.filter(PolicyMeeting.state == "done", PolicyMeeting.summarised_at >= summarised_since)
        rows = q.order_by(PolicyMeeting.meeting_date.desc(), PolicyMeeting.committee_key).all()
        return [
            {
                "committee_key": m.committee_key,
                "meeting_num": m.meeting_num,
                "meeting_date": m.meeting_date,
                "state": m.state,
                "has_torimatome": bool(m.has_torimatome),
                "digest_en_json": m.digest_en_json,
                "summarised_at": m.summarised_at,
            }
            for m in rows
        ]


def undated_meetings_detected_since(since: datetime, db_path: str | None = None) -> int:
    """How many meetings detected at or after *since* still have no ``meeting_date``."""
    with session_scope(db_path, commit=False) as session:
        return (
            session.query(func.count(PolicyMeeting.id))
            .filter(PolicyMeeting.detected_at >= since, PolicyMeeting.meeting_date.is_(None))
            .scalar()
        ) or 0


def update_committee(key: str, db_path: str | None = None, **fields) -> None:
    """Patch a ``policy_committee`` row (synthesis_notebook_id, last_synth_meeting, ...)."""
    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is None:
            row = PolicyCommittee(committee_key=key)
            session.add(row)
        for k, v in fields.items():
            setattr(row, k, v)


def update_meeting(meeting_id: int, db_path: str | None = None, **fields) -> None:
    """Patch a ``policy_meeting`` row (state, notebook_id, briefing_md, ...)."""
    with session_scope(db_path) as session:
        m = session.get(PolicyMeeting, meeting_id)
        if m is None:
            return
        for k, v in fields.items():
            setattr(m, k, v)
        m.updated_at = _now()


def meeting_digest(key: str, meeting_num: int, db_path: str | None = None) -> dict | None:
    """The stored English digest of one meeting as a dict (``answer``, ``references``…), or
    None if the meeting is unknown, has no digest, or the digest is unreadable."""
    with session_scope(db_path, commit=False) as session:
        raw = (
            session.query(PolicyMeeting.digest_en_json)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .scalar()
        )
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def set_meeting_citations(key: str, meeting_num: int, citations_json: str, db_path: str | None = None) -> bool:
    """Store a meeting's resolved citations. Deliberately leaves ``updated_at`` alone:
    the UI reads that as "when it was summarised", and resolving the citations of an old
    meeting must not make it look newly summarised."""
    with session_scope(db_path) as session:
        m = session.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=meeting_num).one_or_none()
        if m is None:
            return False
        m.citations_json = citations_json
        return True


def meetings_missing_citations(db_path: str | None = None, committee_key: str | None = None) -> list[tuple[str, int]]:
    """``(committee_key, meeting_num)`` of summarised meetings whose citations have never
    been resolved, newest first (highest id) — the recent ones are the ones being read."""
    with session_scope(db_path, commit=False) as session:
        q = (
            session.query(PolicyMeeting.committee_key, PolicyMeeting.meeting_num)
            .filter(PolicyMeeting.digest_en_json.isnot(None), PolicyMeeting.citations_json.is_(None))
        )
        if committee_key:
            q = q.filter(PolicyMeeting.committee_key == committee_key)
        return [(r[0], r[1]) for r in q.order_by(PolicyMeeting.id.desc()).all()]


def meetings_missing_date(key: str, db_path: str | None = None) -> list[int]:
    """Meeting numbers for *key* that have no ``meeting_date`` yet (newest first)."""
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyMeeting.meeting_num)
            .filter_by(committee_key=key)
            .filter(PolicyMeeting.meeting_date.is_(None))
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
        return [r[0] for r in rows]


def meetings_missing_materials(key: str, db_path: str | None = None) -> list[int]:
    """Meeting numbers for *key* that have no source materials yet and aren't done
    (newest first).

    ``detect`` only enumerates materials for genuinely *new* meetings, so a meeting
    first seen while its committee page was unavailable (e.g. a transient METI
    outage) keeps zero materials — and the Policy Deep Dive hides material-less,
    non-error meetings, so such a meeting never appears even though its committee is
    tracked. This lists them so a catch-up can re-fetch their materials.
    """
    with session_scope(db_path, commit=False) as session:
        with_mats = {
            r[0]
            for r in session.query(PolicyMaterial.meeting_num)
            .filter(PolicyMaterial.committee_key == key)
            .distinct()
            .all()
        }
        rows = (
            session.query(PolicyMeeting.meeting_num, PolicyMeeting.state)
            .filter_by(committee_key=key)
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
        return [num for (num, state) in rows if state != "done" and num not in with_mats]


def set_meeting_dates(key: str, dates: dict[int, date], db_path: str | None = None) -> int:
    """Set ``meeting_date`` for the given ``{meeting_num: date}`` of committee *key*.

    Only rows that exist and whose date actually changes are touched; ``updated_at``
    is deliberately left alone so a pure date backfill doesn't reshuffle
    recency-ordered views. Returns the number of rows updated.
    """
    if not dates:
        return 0
    with session_scope(db_path) as session:
        n = 0
        for num, d in dates.items():
            m = (
                session.query(PolicyMeeting)
                .filter_by(committee_key=key, meeting_num=num)
                .one_or_none()
            )
            if m is not None and d is not None and m.meeting_date != d:
                m.meeting_date = d
                n += 1
        return n


# ── Upcoming (scheduled) meetings ────────────────────────────────────────────
# Past calendar rows are kept this long: the weekly summary reads them to list
# meetings that were held — including ones on committees nothing else tracks.
UPCOMING_HISTORY_DAYS = 90


def replace_upcoming(rows, db_path: str | None = None, *, today: date | None = None) -> int:
    """Refresh ``policy_upcoming`` from *rows* (``schedule.Upcoming``).

    The table has two parts. **Future** rows (``meeting_date >= today``) are a rolling
    snapshot of the calendar: truncated and rewritten atomically, so a cancelled or
    moved meeting disappears. **Past** rows are a short history of what the calendar
    announced, kept for ``UPCOMING_HISTORY_DAYS`` — once its date passes, a meeting
    drops off the calendar but did happen. Past rows in *rows* are inserted only when
    absent. Rows are deduped on ``(meeting_date, source_key)``. Returns the number of
    future rows written.
    """
    from datetime import timedelta

    today = today or today_jst()
    cutoff = today - timedelta(days=UPCOMING_HISTORY_DAYS)
    with session_scope(db_path) as session:
        session.query(PolicyUpcoming).filter(
            or_(PolicyUpcoming.meeting_date >= today, PolicyUpcoming.meeting_date < cutoff)
        ).delete(synchronize_session=False)
        seen: set[tuple] = {
            (d, k)
            for d, k in session.query(PolicyUpcoming.meeting_date, PolicyUpcoming.source_key).all()
        }
        written = 0
        for r in rows:
            k = (r.date, r.source_key)
            if k in seen or r.date < cutoff:
                continue
            seen.add(k)
            session.add(
                PolicyUpcoming(
                    meeting_date=r.date,
                    name_ja=r.name_ja,
                    source_key=r.source_key,
                    org=r.org,
                    committee_key=r.committee_key,
                    meeting_num=r.meeting_num,
                    source=r.source,
                    source_url=r.source_url,
                )
            )
            if r.date >= today:
                written += 1
        return written


def _upcoming_dict(r: PolicyUpcoming) -> dict:
    return {
        "date": r.meeting_date.isoformat() if r.meeting_date else None,
        "name_ja": r.name_ja,
        "org": r.org,
        "committee_key": r.committee_key,
        "meeting_num": r.meeting_num,
        "source": r.source,
        "source_url": r.source_url,
    }


def list_upcoming(db_path: str | None = None, *, today: date | None = None) -> list[dict]:
    """Scheduled meetings on or after *today* (JST), soonest first, as plain dicts.

    Past rows (the calendar history) are excluded — see :func:`calendar_entries`.
    """
    today = today or today_jst()
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyUpcoming)
            .filter(PolicyUpcoming.meeting_date >= today)
            .order_by(PolicyUpcoming.meeting_date.asc(), PolicyUpcoming.org.asc())
            .all()
        )
        return [_upcoming_dict(r) for r in rows]


def calendar_entries(start: date, end: date, db_path: str | None = None) -> list[dict]:
    """Calendar rows dated ``start..end`` inclusive (past or future), soonest first."""
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyUpcoming)
            .filter(PolicyUpcoming.meeting_date >= start, PolicyUpcoming.meeting_date <= end)
            .order_by(PolicyUpcoming.meeting_date.asc(), PolicyUpcoming.org.asc())
            .all()
        )
        return [_upcoming_dict(r) for r in rows]


# ── Running document ─────────────────────────────────────────────────────────
def _digest_en_answer(digest_en_json: str | None) -> str | None:
    if not digest_en_json:
        return None
    try:
        return (json.loads(digest_en_json) or {}).get("answer")
    except (json.JSONDecodeError, TypeError):
        return None


def build_running_doc(key: str, db_path: str | None = None) -> str:
    """Render the committee's running document (Markdown) from the DB, newest first."""
    with session_scope(db_path, commit=False) as session:
        # Resolve via the DB first so discovered / runtime-added committees (not in
        # the static config, e.g. those the cross-check accumulates) also render —
        # committee_by_key alone would KeyError on them.
        c = committee_or_config(key, db_path=db_path)
        if c is None:
            raise KeyError(f"unknown committee {key!r}")
        committee = session.get(PolicyCommittee, key)
        meetings = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key)
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
        lines: list[str] = [
            f"# {c.name_en or c.name_ja or key}",
            f"## {c.name_ja or key}",
            f"_{c.source} · {c.url}_",
            f"_Generated: {_now():%Y-%m-%d %H:%M UTC}_",
            "",
        ]
        if committee and committee.running_summary_md:
            lines += ["## 議論の総括（会合横断シンセシス）", "", committee.running_summary_md, ""]
        if committee and committee.running_digest_en_md:
            lines += ["## Synthesis overview (English)", "", committee.running_digest_en_md, ""]
        lines += ["## Meetings", ""]
        for m in meetings:
            date = f" — {m.meeting_date}" if m.meeting_date else ""
            flag = " 🏁" if m.has_torimatome else ""
            lines.append(f"### 第{m.meeting_num}回{date}{flag}")
            en = _digest_en_answer(m.digest_en_json)
            if en:
                lines += ["", "**English digest:**", "", en]
            if m.briefing_md:
                lines += ["", m.briefing_md, ""]
            elif not en:
                lines += ["", f"_({m.state}; not yet summarised)_", ""]
            lines.append("")
        return "\n".join(lines).strip() + "\n"


def regenerate_running_doc(key: str, db_path: str | None = None):
    """Regenerate ``data/policy/<key>.md`` and cache it on the committee row.

    Returns the written :class:`pathlib.Path`.
    """
    doc = build_running_doc(key, db_path=db_path)
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    path = POLICY_DIR / f"{key}.md"
    path.write_text(doc, encoding="utf-8")

    with session_scope(db_path) as session:
        row = session.get(PolicyCommittee, key)
        if row is not None:
            # latest_meeting = highest meeting that reached 'done'
            done_max = (
                session.query(PolicyMeeting.meeting_num)
                .filter_by(committee_key=key, state="done")
                .order_by(PolicyMeeting.meeting_num.desc())
                .first()
            )
            row.latest_meeting = done_max[0] if done_max else row.latest_meeting
    return path
