"""Apply topic tags to committees and meetings, and persist them.

The vocabulary and the matching rules are pure and live in :mod:`repower.policy.tags`;
this module reads the policy tables, runs the rules and writes the result back.

**Who may overwrite whom.** Every tag set records its ``tags_source``, and a write only
lands when its source ranks at least as high as the one already stored::

    manual (a person, via `repower policy tag-set`)   3
    config (curated in committees.py) / llm            2
    rule   (keywords)                                  1

So the daily rule pass re-evaluates freely — a meeting's material titles grow as
documents land, and its briefing arrives later — but it can never undo an LLM
classification or a person's correction. A manual pin of ``[]`` is meaningful ("this has
no topic"), which is why "never tagged" is ``NULL`` and "tagged, nothing" is ``"[]"``.

Everything here is DB-only: no network, no NotebookLM, safe to run in any cron.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from repower.db import PolicyCommittee, PolicyMaterial, PolicyMeeting
from repower.policy import tags as tg
from repower.policy.committees import COMMITTEES
from repower.policy.store import session_scope

logger = logging.getLogger(__name__)

_RANK: dict[str | None, int] = {None: 0, "rule": 1, "config": 2, "llm": 2, "manual": 3}

_CURATED: dict[str, tuple[str, ...]] = {c.key: c.tags for c in COMMITTEES if c.tags is not None}


def _rank(source: str | None) -> int:
    return _RANK.get(source, 0)


def _encode(keys: list[str]) -> str:
    return json.dumps(keys)


def _write(row: Any, new: list[str], source: str) -> bool:
    """Store *new* on *row* if *source* may overwrite what is there. True when written."""
    if _rank(source) < _rank(row.tags_source):
        return False
    row.tags = _encode(new)
    row.tags_source = source
    return True


def _meeting_day(m: Any) -> date | None:
    """The day a meeting counts as having happened: its real date, else when we detected it."""
    if m.meeting_date:
        return m.meeting_date
    return m.detected_at.date() if m.detected_at else None


def committee_coverage(db_path: str | None = None, committee: str | None = None) -> dict[str, dict[str, tg.Coverage]]:
    """Topic coverage per committee, from the tags currently stored (read-only).

    The same numbers the web shows: ``{committee_key: {tag: Coverage}}``.
    """
    rows: dict[str, list[tuple[date | None, list[str], bool]]] = {}
    with session_scope(db_path, commit=False) as session:
        with_materials = {
            (ck, num) for ck, num in session.query(PolicyMaterial.committee_key, PolicyMaterial.meeting_num).distinct()
        }
        mq = session.query(PolicyMeeting)
        if committee:
            mq = mq.filter(PolicyMeeting.committee_key == committee)
        for m in mq.all():
            ok = tg.has_evidence(m.state, (m.committee_key, m.meeting_num) in with_materials)
            rows.setdefault(m.committee_key, []).append((_meeting_day(m), tg.decode(m.tags) or [], ok))
    return {ck: tg.coverage(r) for ck, r in rows.items()}


def meeting_tag_rows(committee: str, db_path: str | None = None) -> list[dict]:
    """One row per meeting of *committee*, newest first — the evidence behind its coverage.

    Each row is ``{num, date, state, has_evidence, tags, tags_source, titles}``: ``date``
    is the day coverage ages it by (real meeting date, else detection day), ``titles`` its
    document titles joined with ' / ' (what the keyword rules actually saw), and
    ``has_evidence`` whether this meeting counts towards coverage at all (see
    :func:`repower.policy.tags.has_evidence`) — a row with no documents and no summary is
    shown but does not move any score, which is what makes a thin score legible rather than
    a mystery.
    """
    with session_scope(db_path, commit=False) as session:
        titles: dict[int, list[str]] = {}
        for num, title in session.query(
            PolicyMaterial.meeting_num, PolicyMaterial.title
        ).filter(PolicyMaterial.committee_key == committee):
            if title:
                titles.setdefault(num, []).append(title)
        rows = []
        mq = session.query(PolicyMeeting).filter(PolicyMeeting.committee_key == committee)
        for m in mq.all():
            rows.append({
                "num": m.meeting_num,
                "date": _meeting_day(m),
                "state": m.state,
                "has_evidence": tg.has_evidence(m.state, m.meeting_num in titles),
                "tags": tg.decode(m.tags) or [],
                "tags_source": m.tags_source,
                "titles": " / ".join(titles.get(m.meeting_num, [])),
            })
    rows.sort(key=lambda r: r["num"], reverse=True)
    return rows


# ── Bulk rule pass ───────────────────────────────────────────────────────────
def retag(
    db_path: str | None = None,
    *,
    apply: bool = True,
    committee: str | None = None,
    meetings: bool = True,
    committees: bool = True,
) -> dict:
    """Re-evaluate rule-based tags for meetings, then committees.

    Idempotent and cheap (a few DB reads, no I/O), so the daily run calls it every
    time: it picks up new meetings, new material titles and fresh briefings.
    ``apply=False`` computes the same result and writes nothing — the dry run behind
    ``repower policy tag``.

    Returns ``{"meetings": [...], "committees": [...], "checked": {...}}``; each change
    is ``{"key", "num"?, "old", "new", "source"}`` where ``old`` is ``None`` for a row
    that was never tagged.
    """
    meeting_changes: list[dict] = []
    committee_changes: list[dict] = []
    n_meetings = n_committees = 0

    with session_scope(db_path, commit=apply) as session:
        titles: dict[tuple[str, int], list[str]] = {}
        with_materials: set[tuple[str, int]] = set()
        for ck, num, title in session.query(
            PolicyMaterial.committee_key, PolicyMaterial.meeting_num, PolicyMaterial.title
        ):
            with_materials.add((ck, num))
            if title:
                titles.setdefault((ck, num), []).append(title)

        mq = session.query(PolicyMeeting)
        if committee:
            mq = mq.filter(PolicyMeeting.committee_key == committee)
        # (day, tags, has_evidence) per meeting, feeding each committee's coverage.
        evidence: dict[str, list[tuple[date | None, list[str], bool]]] = {}
        for m in mq.all():
            t = titles.get((m.committee_key, m.meeting_num), [])
            body = m.briefing_md if m.state == "done" else None
            current = tg.decode(m.tags)
            if _rank(m.tags_source) > _rank("rule"):
                final = current or []  # llm / manual: not ours to recompute
            else:
                new = tg.tags_for_meeting(titles=t, body=body, extra_title=m.title)
                final = new
                if meetings and (current != new or m.tags_source != "rule"):
                    meeting_changes.append(
                        {"key": m.committee_key, "num": m.meeting_num, "old": current, "new": new, "source": "rule"}
                    )
                    if apply:
                        _write(m, new, "rule")
            n_meetings += 1
            ok = tg.has_evidence(m.state, (m.committee_key, m.meeting_num) in with_materials)
            evidence.setdefault(m.committee_key, []).append((_meeting_day(m), final, ok))

        if committees:
            cq = session.query(PolicyCommittee)
            if committee:
                cq = cq.filter(PolicyCommittee.committee_key == committee)
            for c in cq.all():
                n_committees += 1
                curated = _CURATED.get(c.committee_key)
                if curated is not None:
                    new, source = tg.normalize(curated), "config"
                else:
                    # Name rules say what the committee is for; its coverage adds what
                    # its meetings actually keep coming back to.
                    new = tg.normalize(
                        tg.tags_from_name(c.name_ja)
                        + tg.tags_from_coverage(tg.coverage(evidence.get(c.committee_key, [])))
                    )
                    source = "rule"
                if _rank(source) < _rank(c.tags_source):
                    continue
                current = tg.decode(c.tags)
                if current == new and c.tags_source == source:
                    continue
                committee_changes.append(
                    {"key": c.committee_key, "old": current, "new": new, "source": source}
                )
                if apply:
                    _write(c, new, source)

    return {
        "meetings": meeting_changes,
        "committees": committee_changes,
        "checked": {"meetings": n_meetings, "committees": n_committees},
    }


# ── Single writes ────────────────────────────────────────────────────────────
def set_meeting_llm_tags(key: str, meeting_num: int, keys: list[str], db_path: str | None = None) -> bool:
    """Record an LLM classification for one meeting. False when a person's pin outranks it."""
    with session_scope(db_path) as session:
        m = (
            session.query(PolicyMeeting)
            .filter_by(committee_key=key, meeting_num=meeting_num)
            .one_or_none()
        )
        if m is None:
            return False
        return _write(m, tg.normalize(keys), "llm")


def _target(session, key: str, meeting_num: int | None):
    if meeting_num is None:
        return session.get(PolicyCommittee, key)
    return (
        session.query(PolicyMeeting)
        .filter_by(committee_key=key, meeting_num=meeting_num)
        .one_or_none()
    )


def set_manual_tags(
    key: str, keys: list[str], *, meeting_num: int | None = None, db_path: str | None = None
) -> bool:
    """Pin a tag set by hand (``[]`` = deliberately no topic). False if the row is unknown.

    Raises ``ValueError`` on a key outside the vocabulary rather than silently dropping it.
    """
    bad = [k for k in keys if not tg.valid(k)]
    if bad:
        raise ValueError(f"unknown tag(s): {', '.join(bad)} (see `repower policy tags`)")
    with session_scope(db_path) as session:
        row = _target(session, key, meeting_num)
        if row is None:
            return False
        _write(row, tg.normalize(keys), "manual")
        return True


def clear_manual_tags(key: str, *, meeting_num: int | None = None, db_path: str | None = None) -> bool:
    """Drop a pin so the automatic rules own the row again (next :func:`retag` fills it)."""
    with session_scope(db_path) as session:
        row = _target(session, key, meeting_num)
        if row is None:
            return False
        row.tags = None
        row.tags_source = None
        return True
