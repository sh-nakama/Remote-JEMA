"""DB read/write for the policy observer + deterministic running-document regen.

State of record lives in the three SQLite tables (``policy_committee``,
``policy_meeting``, ``policy_material``). The per-committee running document at
``data/policy/<key>.md`` is always *regenerated* from the DB (never appended), so
it can't drift from the source of truth and is safe to re-run after a crash.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_

from repower.config import POLICY_DIR
from repower.db import PolicyCommittee, PolicyMaterial, PolicyMeeting, get_session, init_db
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
    return datetime.now(timezone.utc)


# ── Committee bootstrap / registry ───────────────────────────────────────────
def sync_committees(db_path: str | None = None) -> int:
    """Ensure a ``policy_committee`` row exists for each code-configured committee.

    Idempotent. Always refreshes the authoritative static fields (name/url/source
    and the structural scrape params) from the code config. **User state**
    (``enabled``, ``priority``) is seeded on first insert (and back-filled when a
    just-migrated row still has ``priority IS NULL``) but never clobbered
    afterwards — so a committee disabled or re-prioritised in the dashboard stays
    that way across detection runs. User-added committees (not in ``COMMITTEES``)
    are left entirely untouched.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        n = 0
        for c in COMMITTEES:
            row = session.get(PolicyCommittee, c.key)
            if row is None:
                row = PolicyCommittee(committee_key=c.key, enabled=True, user_added=False)
                session.add(row)
                n += 1
            row.name_ja, row.name_en = c.name_ja, c.name_en
            row.url, row.source = c.url, c.source
            # Structural scrape params are code-authoritative for code committees.
            row.max_meeting, row.prefix = c.max_meeting, c.prefix
            row.log_pages = json.dumps(list(c.log_pages)) if c.log_pages else None
            row.min_meeting = c.min_meeting
            # Seed priority from code only when it hasn't been set yet (fresh insert
            # or a row from before the priority column existed); preserve UI edits.
            if row.priority is None:
                row.priority = c.priority
        session.commit()
        return n
    finally:
        session.close()


def _committee_from_row(row: PolicyCommittee) -> Committee:
    """Build a :class:`Committee` from a ``policy_committee`` DB row."""
    log_pages: tuple[str, ...] = ()
    if row.log_pages:
        try:
            log_pages = tuple(json.loads(row.log_pages) or ())
        except (json.JSONDecodeError, TypeError):
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


def resolve_committee(key: str, db_path: str | None = None) -> Committee:
    """Resolve a committee by key, DB-first (so UI edits + user-added committees win).

    Falls back to the code config for keys with no DB row yet (e.g. a dry-run before
    the first ``sync_committees``). Raises ``KeyError`` if the key is unknown to both.
    """
    row = get_committee(key, db_path=db_path)
    if row is not None and row.source:
        return _committee_from_row(row)
    return committee_by_key(key)  # raises KeyError if genuinely unknown


def tracked_committees(
    db_path: str | None = None, *, include_disabled: bool = False, sync: bool = True,
) -> list[Committee]:
    """The committees to detect/summarise, as :class:`Committee` objects.

    Reads the DB registry (so it includes user-added committees and honours the
    ``enabled`` flag). ``sync=True`` seeds the code committees first. Before the
    first sync (empty registry) it falls back to the code config so a fresh dry-run
    still sees every committee.
    """
    if sync:
        sync_committees(db_path)
    init_db(db_path)
    session = get_session(db_path)
    try:
        q = session.query(PolicyCommittee)
        if not include_disabled:
            q = q.filter(PolicyCommittee.enabled.is_(True))
        rows = q.all()
        if not rows and not sync:
            return list(COMMITTEES)
        # Preserve the code ordering for code committees; append user-added ones.
        code_order = {c.key: i for i, c in enumerate(COMMITTEES)}
        rows.sort(key=lambda r: (code_order.get(r.committee_key, len(code_order)), r.committee_key))
        return [_committee_from_row(r) for r in rows]
    finally:
        session.close()


def add_committee(
    *, key: str, name_ja: str, name_en: str, url: str, source: str,
    priority: int = 100, max_meeting: int | None = None, prefix: str | None = None,
    log_pages: tuple[str, ...] | list[str] | None = None, min_meeting: int | None = None,
    enabled: bool = True, db_path: str | None = None,
) -> bool:
    """Insert (or update) a user-added committee row. Returns True if newly created.

    ``key`` must be unique; re-adding an existing key updates its config fields.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyCommittee, key)
        is_new = row is None
        if row is None:
            row = PolicyCommittee(committee_key=key, user_added=True)
            session.add(row)
        row.name_ja, row.name_en = name_ja, name_en
        row.url, row.source = url, source
        row.priority = priority
        row.max_meeting, row.prefix = max_meeting, prefix
        row.log_pages = json.dumps(list(log_pages)) if log_pages else None
        row.min_meeting = min_meeting
        row.enabled = enabled
        session.commit()
        return is_new
    finally:
        session.close()


def set_committee_enabled(key: str, enabled: bool, db_path: str | None = None) -> None:
    """Enable/disable tracking of a committee (gates detection + summarisation)."""
    update_committee(key, db_path=db_path, enabled=enabled)


def set_committee_priority(key: str, priority: int, db_path: str | None = None) -> None:
    """Set a committee's summarisation priority (lower = summarised first)."""
    update_committee(key, db_path=db_path, priority=priority)


def delete_committee(key: str, db_path: str | None = None) -> bool:
    """Delete a **user-added** committee and all its meetings/materials.

    Refuses to delete code-config committees (returns False) — disable those
    instead so the registry can't drift from the code config.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyCommittee, key)
        if row is None or not row.user_added:
            return False
        session.query(PolicyMaterial).filter_by(committee_key=key).delete()
        session.query(PolicyMeeting).filter_by(committee_key=key).delete()
        session.delete(row)
        session.commit()
        return True
    finally:
        session.close()


def list_committees(db_path: str | None = None) -> list[dict]:
    """All registry rows (enabled + disabled) as plain dicts, for the management UI."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        rows = session.query(PolicyCommittee).all()
        code_order = {c.key: i for i, c in enumerate(COMMITTEES)}
        rows.sort(key=lambda r: (r.priority if r.priority is not None else 100,
                                 code_order.get(r.committee_key, len(code_order)),
                                 r.committee_key))
        return [
            {
                "committee_key": r.committee_key,
                "name_ja": r.name_ja or r.committee_key,
                "name_en": r.name_en or r.committee_key,
                "url": r.url,
                "source": r.source,
                "enabled": bool(r.enabled),
                "user_added": bool(r.user_added),
                "priority": r.priority if r.priority is not None else 100,
                "latest_meeting": r.latest_meeting,
            }
            for r in rows
        ]
    finally:
        session.close()


# ── Generation queue (dashboard "Generate summary" when auth is stale) ────────
def request_generation(key: str, meeting_num: int, db_path: str | None = None) -> bool:
    """Flag one meeting for summarisation. Returns True if the row exists/was flagged."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is None:
            return False
        m.gen_requested = True
        session.commit()
        return True
    finally:
        session.close()


def clear_generation_request(key: str, meeting_num: int, db_path: str | None = None) -> None:
    """Clear a meeting's generation-requested flag (once it's been summarised)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is not None and m.gen_requested:
            m.gen_requested = False
            session.commit()
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
def _priority_map(session) -> dict[str, int]:
    """committee_key → priority, from the DB registry (fallback to code config)."""
    out: dict[str, int] = {}
    for r in session.query(PolicyCommittee.committee_key, PolicyCommittee.priority).all():
        out[r[0]] = r[1] if r[1] is not None else committee_priority(r[0])
    return out


def pending_meetings(key: str | None = None, db_path: str | None = None) -> list[dict]:
    """Meetings still needing work, in summarisation order, as plain dicts.

    Ordered by: **user-requested first** (a dashboard "Generate summary" that was
    queued), then committee **priority** (so a quota-bounded ``policy run`` drains
    high-priority committees first), then committee key to keep a committee's
    meetings grouped, then newest meeting first within a committee.

    Includes everything not yet ``done``, plus ``error`` rows that have failed
    fewer than ``MAX_RETRIES`` times (so transient failures are retried).
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
        # Priority lives in the DB registry (editable from the UI), so order in Python.
        prio = _priority_map(session)
        rows.sort(key=lambda m: (
            0 if m.gen_requested else 1,
            prio.get(m.committee_key, 100),
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
        c = committee_by_key(key)
        committee = session.get(PolicyCommittee, key)
        meetings = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key)
            .order_by(PolicyMeeting.meeting_num.desc())
            .all()
        )
        lines: list[str] = [
            f"# {c.name_en}",
            f"## {c.name_ja}",
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
