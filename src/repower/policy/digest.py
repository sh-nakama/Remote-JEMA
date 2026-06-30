"""Weekly digest of recently-summarised committee meetings.

Assembled deterministically from the per-meeting English digests already stored in
the DB (no NotebookLM call), and optionally posted to ``WEBHOOK_URL``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from repower.config import WEBHOOK_URL
from repower.policy.committees import committee_by_key
from repower.policy.store import recent_done_meetings

logger = logging.getLogger(__name__)


def _digest_answer(digest_en_json: str | None) -> str:
    if not digest_en_json:
        return "_(no English digest)_"
    try:
        return (json.loads(digest_en_json) or {}).get("answer") or "_(empty)_"
    except (json.JSONDecodeError, TypeError):
        return "_(unparseable digest)_"


def build_digest(since_days: int = 7, db_path: str | None = None) -> str:
    """Markdown digest of meetings summarised in the last ``since_days``."""
    meetings = recent_done_meetings(since_days, db_path=db_path)
    header = f"# Policy digest — {datetime.now(timezone.utc):%Y-%m-%d} (last {since_days}d)"
    if not meetings:
        return f"{header}\n\nNo new committee meetings summarised this period."

    lines = [header, "", f"{len(meetings)} meeting(s) summarised:", ""]
    for m in meetings:
        try:
            name = committee_by_key(m["committee_key"]).name_en
        except KeyError:
            name = m["committee_key"]
        flag = " 🏁 (とりまとめ)" if m["has_torimatome"] else ""
        lines.append(f"## {name} — 第{m['meeting_num']}回{flag}")
        lines.append("")
        lines.append(_digest_answer(m["digest_en_json"]))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def post_digest(markdown: str) -> bool:
    """POST the digest to ``WEBHOOK_URL`` (Discord/Slack-style ``{"content": ...}``).

    Returns False (no-op) when no webhook is configured.
    """
    if not WEBHOOK_URL:
        return False
    # Discord caps message content at 2000 chars.
    content = markdown if len(markdown) <= 1900 else markdown[:1900] + "\n…(truncated)"
    try:
        r = httpx.post(WEBHOOK_URL, json={"content": content}, timeout=30.0)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("digest webhook post failed: %s", e)
        return False
