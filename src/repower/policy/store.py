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
from repower.policy.committees import COMMITTEES, committee_by_key
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
def sync_committees(db_path: str | None = None) -> int:
    """Ensure a ``policy_committee`` row exists for each configured committee.

    Idempotent: inserts missing rows and refreshes the static config fields
    (name/url/source) without touching dynamic state (latest_meeting, etc.).
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
                n += 1
            row.name_ja, row.name_en = c.name_ja, c.name_en
            row.url, row.source = c.url, c.source
        session.commit()
        return n
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
def pending_meetings(key: str | None = None, db_path: str | None = None) -> list[dict]:
    """Meetings still needing work, newest first, as plain dicts.

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
        q = q.order_by(PolicyMeeting.committee_key, PolicyMeeting.meeting_num.desc())
        return [
            {
                "id": m.id,
                "committee_key": m.committee_key,
                "meeting_num": m.meeting_num,
                "state": m.state,
                "has_minutes": m.has_minutes,
                "has_torimatome": m.has_torimatome,
            }
            for m in q.all()
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


def meetings_for_synthesis(key: str, since_meeting: int | None, db_path: str | None = None) -> list[dict]:
    """Done meetings with a briefing, numbered above ``since_meeting`` (oldest first)."""
    init_db(db_path)
    session = get_session(db_path)
    try:
        q = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, state="done")
            .filter(PolicyMeeting.briefing_md.isnot(None))
        )
        if since_meeting is not None:
            q = q.filter(PolicyMeeting.meeting_num > since_meeting)
        q = q.order_by(PolicyMeeting.meeting_num.asc())
        return [{"meeting_num": m.meeting_num, "briefing_md": m.briefing_md} for m in q.all()]
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
        if committee and committee.running_digest_en_md:
            lines += ["## Overview (English)", "", committee.running_digest_en_md, ""]
        if committee and committee.running_summary_md and committee.running_summary_md != "__doc__":
            # running_summary_md holds the synthesis body; avoid recursion if it
            # was previously set to the full doc.
            pass
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
