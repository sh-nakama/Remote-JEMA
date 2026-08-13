"""DB read/write for the policy observer + deterministic running-document regen.

State of record lives in the three SQLite tables (``policy_committee``,
``policy_meeting``, ``policy_material``). The per-committee running document at
``data/policy/<key>.md`` is always *regenerated* from the DB (never appended), so
it can't drift from the source of truth and is safe to re-run after a crash.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from datetime import UTC, date, datetime

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

logger = logging.getLogger(__name__)

# Errored meetings stay in the worklist until they've failed this many times, so
# transient failures (network/rate-limit) are retried by the next `policy run`.
MAX_RETRIES = 3

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
    include_archived: bool = False,
) -> list[Committee]:
    """The committees to detect/summarise, as :class:`Committee` objects.

    Reads the DB registry (so it includes user-added committees and honours the
    ``enabled`` flag). ``sync=True`` seeds the code committees first. Before the
    first sync (empty registry) it falls back to the code config so a fresh dry-run
    still sees every committee.

    ``archived`` committees (concluded, no longer meeting) are excluded unless
    ``include_archived=True`` — they are a *fetch* exclusion, orthogonal to the
    ``enabled`` tracking flag. Their stored meetings are untouched and still render.
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
        rows.sort(key=lambda r: (code_order.get(r.committee_key, len(code_order)), r.committee_key))
        return [_row_to_committee(r) for r in rows]


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
    """Flag one meeting for summarisation. Returns True if the row exists/was flagged."""
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is None:
            return False
        m.gen_requested = True
        return True


def clear_generation_request(key: str, meeting_num: int, db_path: str | None = None) -> None:
    """Clear a meeting's generation-requested flag (once it's been summarised)."""
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is not None and m.gen_requested:
            m.gen_requested = False


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
                    )
                )
            kinds = {m.kind for m in mats}
            if "minutes" in kinds:
                meeting.has_minutes = True
            if "compilation" in kinds:
                meeting.has_torimatome = True
        meeting.updated_at = _now()
        return is_new


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
                     only_enabled: bool = False, breadth_first: bool = False) -> list[dict]:
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
        # Priority + enabled live on the committee row; read them once and order in Python.
        coms = {c.committee_key: c for c in session.query(PolicyCommittee).all()}
        if only_enabled:
            rows = [m for m in rows if getattr(coms.get(m.committee_key), "enabled", True)]

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
        if breadth_first:
            by_com: dict[str, list[PolicyMeeting]] = {}
            for m in rows:
                by_com.setdefault(m.committee_key, []).append(m)
            for ms in by_com.values():
                for r, m in enumerate(sorted(ms, key=lambda x: -x.meeting_num)):
                    depth[m.id] = r

        rows.sort(key=lambda m: (
            0 if m.gen_requested else 1,  # user-requested ("Generate summary") first
            depth.get(m.id, 0),           # breadth-first: newest-of-each committee first
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
            }
            for m in rows
        ]


def meeting_materials(key: str, meeting_num: int, db_path: str | None = None) -> list[dict]:
    """All materials for a meeting, as plain dicts (id, pdf_id, kind, url, title)."""
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyMaterial)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .all()
        )
        return [
            {"id": r.id, "pdf_id": r.pdf_id, "kind": r.kind, "url": r.url, "title": r.title}
            for r in rows
        ]


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
def replace_upcoming(rows, db_path: str | None = None) -> int:
    """Replace the ``policy_upcoming`` snapshot with *rows* (``schedule.Upcoming``).

    The table is a rolling snapshot, so it is truncated and rewritten atomically.
    Rows are deduped on ``(meeting_date, source_key)`` in case a source repeats an
    entry. Returns the number of rows written.
    """
    with session_scope(db_path) as session:
        session.query(PolicyUpcoming).delete()
        seen: set[tuple] = set()
        written = 0
        for r in rows:
            k = (r.date, r.source_key)
            if k in seen:
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
            written += 1
        return written


def list_upcoming(db_path: str | None = None) -> list[dict]:
    """All rows from the ``policy_upcoming`` snapshot, soonest first, as plain dicts."""
    with session_scope(db_path, commit=False) as session:
        rows = (
            session.query(PolicyUpcoming)
            .order_by(PolicyUpcoming.meeting_date.asc(), PolicyUpcoming.org.asc())
            .all()
        )
        return [
            {
                "date": r.meeting_date.isoformat() if r.meeting_date else None,
                "name_ja": r.name_ja,
                "org": r.org,
                "committee_key": r.committee_key,
                "meeting_num": r.meeting_num,
                "source": r.source,
                "source_url": r.source_url,
            }
            for r in rows
        ]


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
