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
from datetime import date, datetime, timezone

from sqlalchemy import func, or_

from repower.config import POLICY_DIR
from repower.db import (
    PolicyCommittee,
    PolicyMaterial,
    PolicyMeeting,
    PolicyUpcoming,
    get_session,
    init_db,
)
from repower.policy.committees import COMMITTEES, Committee, committee_by_key
from repower.policy.scraper import Material

logger = logging.getLogger(__name__)

# Errored meetings stay in the worklist until they've failed this many times, so
# transient failures (network/rate-limit) are retried by the next `policy run`.
MAX_RETRIES = 3

# Documents to ingest per meeting, in priority order (code-enforced, not agent
# judgment), keeping a meeting to a handful of sources well under any tier cap.
INGEST_KINDS = ("minutes", "brief", "compilation", "handout", "agenda", "appendix")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Committee bootstrap ──────────────────────────────────────────────────────
def _log_pages_to_db(log_pages) -> str | None:
    """Serialize a committee's EGC ``log_pages`` tuple to the DB's JSON-array form."""
    return json.dumps(list(log_pages)) if log_pages else None


def sync_committees(db_path: str | None = None) -> int:
    """Ensure a ``policy_committee`` row exists for each configured committee.

    Idempotent: inserts missing rows and refreshes the static config fields
    (name/url/source + per-source scraper config) without touching dynamic state
    (latest_meeting, synthesis, etc.). ``enabled`` (tracked) and ``priority`` (the
    catch-up queue position) are **user-editable**, so they are seeded only on
    insert — an existing row keeps whatever the user set via the UI/CLI, which is
    what lets a committee "jump the queue permanently". Committees not in the
    config (discovered / user-added) are left untouched.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        n = 0
        for c in COMMITTEES:
            row = session.get(PolicyCommittee, c.key)
            if row is None:
                row = PolicyCommittee(committee_key=c.key)
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
        session.commit()
        return n
    finally:
        session.close()


def _row_to_committee(row: PolicyCommittee) -> Committee:
    """Build a :class:`~repower.policy.committees.Committee` config object from a
    ``policy_committee`` row, so the scraper can process it whether it was seeded
    from config or added at runtime."""
    try:
        log_pages = tuple(json.loads(row.log_pages)) if row.log_pages else ()
    except (ValueError, TypeError):
        log_pages = ()
    return Committee(
        key=row.committee_key,
        name_ja=row.name_ja or "",
        name_en=row.name_en or "",
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
    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyCommittee, key)
        if row is not None:
            return _row_to_committee(row)
    finally:
        session.close()
    try:
        return committee_by_key(key)
    except KeyError:
        return None


def enabled_committees(db_path: str | None = None) -> list[Committee]:
    """Tracked committees (``enabled=1``) as ``Committee`` config objects, in
    summarisation order (priority, then key)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        rows = session.query(PolicyCommittee).filter(PolicyCommittee.enabled == True).all()  # noqa: E712
        coms = [_row_to_committee(r) for r in rows]
        coms.sort(key=lambda c: (c.priority, c.key))
        return coms
    finally:
        session.close()


def enabled_committee_keys(db_path: str | None = None) -> list[str]:
    """Keys of the tracked committees (``enabled=1``)."""
    return [c.key for c in enabled_committees(db_path)]


def set_committee_enabled(key: str, enabled: bool, db_path: str | None = None) -> bool:
    """Set a committee's tracked flag. Returns True if the row existed."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyCommittee, key)
        if row is None:
            return False
        row.enabled = bool(enabled)
        session.commit()
        return True
    finally:
        session.close()


def set_committee_priority(key: str, priority: int, db_path: str | None = None) -> bool:
    """Set a committee's summarisation priority (the catch-up queue position; lower
    is summarised first). Persisted across ``sync_committees`` so a committee can
    "jump the queue permanently". Returns True if the row existed."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyCommittee, key)
        if row is None:
            return False
        row.priority = int(priority)
        session.commit()
        return True
    finally:
        session.close()


def list_committees(db_path: str | None = None) -> list[dict]:
    """All catalog committees as plain dicts (key/source/names/tracked/priority/…),
    sorted by source, priority, key. Includes discovered/untracked rows."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        rows = session.query(PolicyCommittee).all()
        out = [
            {
                "key": r.committee_key,
                "source": r.source or "METI",
                "name_en": r.name_en or r.committee_key,
                "name_ja": r.name_ja or "",
                "enabled": bool(r.enabled) if r.enabled is not None else True,
                "user_added": bool(r.user_added),
                "priority": r.priority if r.priority is not None else 100,
                "latest_meeting": r.latest_meeting,
                "url": r.url or "",
            }
            for r in rows
        ]
        out.sort(key=lambda x: (x["source"], x["priority"], x["key"]))
        return out
    finally:
        session.close()


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
    init_db(db_path)
    session = get_session(db_path)
    try:
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
        session.commit()
        return inserted
    finally:
        session.close()


def get_committee(key: str, db_path: str | None = None) -> PolicyCommittee | None:
    init_db(db_path)
    session = get_session(db_path)
    try:
        return session.get(PolicyCommittee, key)
    finally:
        session.close()


# ── Detection writes ─────────────────────────────────────────────────────────
def known_meeting_nums(key: str, db_path: str | None = None) -> set[int]:
    """Meeting numbers already recorded for a committee (any state)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        rows = session.query(PolicyMeeting.meeting_num).filter_by(committee_key=key).all()
        return {r[0] for r in rows}
    finally:
        session.close()


def record_meeting(key: str, meeting_num: int, materials: list[Material] | None,
                   db_path: str | None = None) -> bool:
    """Upsert one meeting + its materials. Returns True if the meeting was new.

    Existing meetings keep their lifecycle ``state``; new materials (e.g. a
    late-arriving 議事録) are added without disturbing already-ingested ones.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
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
        session.commit()
        return is_new
    finally:
        session.close()


def set_committee_checked(key: str, latest_online: int | None, db_path: str | None = None) -> None:
    """Record that a detection pass ran (used for the dashboard / freshness)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyCommittee, key)
        if row is None:
            row = PolicyCommittee(committee_key=key)
            session.add(row)
        row.last_checked = _now()
        session.commit()
    finally:
        session.close()


# ── Worklist / lifecycle ─────────────────────────────────────────────────────
def pending_meetings(key: str | None = None, db_path: str | None = None,
                     only_enabled: bool = False) -> list[dict]:
    """Meetings still needing work, in summarisation order, as plain dicts.

    Ordered by committee **priority** first (so a quota-bounded ``policy run`` drains
    the high-priority committees first), then committee key to keep each committee's
    meetings grouped, then newest meeting first within a committee.

    Includes everything not yet ``done``, plus ``error`` rows that have failed
    fewer than ``MAX_RETRIES`` times (so transient failures are retried). With
    ``only_enabled`` the result is restricted to tracked (``enabled=1``) committees
    — used by ``policy run --committee all`` so disabling a committee removes it
    from the daily worklist.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
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
            return c.priority if c is not None and c.priority is not None else 100

        rows.sort(key=lambda m: (_prio(m.committee_key), m.committee_key, -m.meeting_num))
        return [
            {
                "id": m.id,
                "committee_key": m.committee_key,
                "meeting_num": m.meeting_num,
                "state": m.state,
                "has_minutes": m.has_minutes,
                "has_torimatome": m.has_torimatome,
            }
            for m in rows
        ]
    finally:
        session.close()


def meeting_materials(key: str, meeting_num: int, db_path: str | None = None) -> list[dict]:
    """All materials for a meeting, as plain dicts (id, pdf_id, kind, url, title)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        rows = (
            session.query(PolicyMaterial)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .all()
        )
        return [
            {"id": r.id, "pdf_id": r.pdf_id, "kind": r.kind, "url": r.url, "title": r.title}
            for r in rows
        ]
    finally:
        session.close()


def meetings_for_synthesis(key: str, db_path: str | None = None) -> list[dict]:
    """Done meetings with a briefing not yet folded into the committee synthesis
    (oldest first).

    Selection is by the per-meeting ``synth_done`` flag rather than a single
    high-water mark, so backfilled / out-of-order meetings (summarised after a
    newer one) are still added to the synthesis instead of being skipped.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        q = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, state="done")
            .filter(PolicyMeeting.briefing_md.isnot(None))
            .filter(or_(PolicyMeeting.synth_done.is_(None), PolicyMeeting.synth_done == False))  # noqa: E712
            .order_by(PolicyMeeting.meeting_num.asc())
        )
        return [{"meeting_num": m.meeting_num, "briefing_md": m.briefing_md} for m in q.all()]
    finally:
        session.close()


def mark_synthesized(key: str, meeting_num: int, db_path: str | None = None) -> None:
    """Flag a meeting's briefing as folded into the committee synthesis notebook."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is not None:
            m.synth_done = True
            session.commit()
    finally:
        session.close()


def recent_done_meetings(since_days: int, db_path: str | None = None) -> list[dict]:
    """Meetings that reached ``done`` within the last ``since_days`` (newest first)."""
    from datetime import timedelta

    init_db(db_path)
    session = get_session(db_path)
    try:
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
    finally:
        session.close()


def update_committee(key: str, db_path: str | None = None, **fields) -> None:
    """Patch a ``policy_committee`` row (synthesis_notebook_id, last_synth_meeting, ...)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyCommittee, key)
        if row is None:
            row = PolicyCommittee(committee_key=key)
            session.add(row)
        for k, v in fields.items():
            setattr(row, k, v)
        session.commit()
    finally:
        session.close()


def update_meeting(meeting_id: int, db_path: str | None = None, **fields) -> None:
    """Patch a ``policy_meeting`` row (state, notebook_id, briefing_md, ...)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        m = session.get(PolicyMeeting, meeting_id)
        if m is None:
            return
        for k, v in fields.items():
            setattr(m, k, v)
        m.updated_at = _now()
        session.commit()
    finally:
        session.close()


def meetings_missing_date(key: str, db_path: str | None = None) -> list[int]:
    """Meeting numbers for *key* that have no ``meeting_date`` yet (newest first)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        rows = (
            session.query(PolicyMeeting.meeting_num)
            .filter_by(committee_key=key)
            .filter(PolicyMeeting.meeting_date.is_(None))
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
        return [r[0] for r in rows]
    finally:
        session.close()


def set_meeting_dates(key: str, dates: dict[int, date], db_path: str | None = None) -> int:
    """Set ``meeting_date`` for the given ``{meeting_num: date}`` of committee *key*.

    Only rows that exist and whose date actually changes are touched; ``updated_at``
    is deliberately left alone so a pure date backfill doesn't reshuffle
    recency-ordered views. Returns the number of rows updated.
    """
    if not dates:
        return 0
    init_db(db_path)
    session = get_session(db_path)
    try:
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
        if n:
            session.commit()
        return n
    finally:
        session.close()


# ── Upcoming (scheduled) meetings ────────────────────────────────────────────
def replace_upcoming(rows, db_path: str | None = None) -> int:
    """Replace the ``policy_upcoming`` snapshot with *rows* (``schedule.Upcoming``).

    The table is a rolling snapshot, so it is truncated and rewritten atomically.
    Rows are deduped on ``(meeting_date, source_key)`` in case a source repeats an
    entry. Returns the number of rows written.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
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
        session.commit()
        return written
    finally:
        session.close()


def list_upcoming(db_path: str | None = None) -> list[dict]:
    """All rows from the ``policy_upcoming`` snapshot, soonest first, as plain dicts."""
    init_db(db_path)
    session = get_session(db_path)
    try:
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
    finally:
        session.close()


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
    init_db(db_path)
    session = get_session(db_path)
    try:
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
    finally:
        session.close()


def regenerate_running_doc(key: str, db_path: str | None = None):
    """Regenerate ``data/policy/<key>.md`` and cache it on the committee row.

    Returns the written :class:`pathlib.Path`.
    """
    doc = build_running_doc(key, db_path=db_path)
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    path = POLICY_DIR / f"{key}.md"
    path.write_text(doc, encoding="utf-8")

    init_db(db_path)
    session = get_session(db_path)
    try:
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
            session.commit()
    finally:
        session.close()
    return path
