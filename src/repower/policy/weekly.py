"""Weekly summary email: committee meetings *held* in the past week.

Every section is keyed on when a meeting was **held** (``meeting_date``), never on
when it was summarised, so the backlog catch-up cannot flood the email:

1. **Tracked & summarised** — meetings of tracked committees held in the window
   that already have a summary, each with a short brief.
2. **Summaries now available** — tracked meetings held in the ``LATE_DAYS`` before
   the window whose summary landed during the last week. Materials publish days to
   weeks after a meeting, so these were "pending" in an earlier email; without this
   section their brief would never be sent.
3. **Also held last week** — every other meeting held in the window, tracked or not:
   from detection (all catalog committees), the METI calendar history and the
   energy-board feed, deduplicated.

Each summarised meeting carries two briefs, always whole bullets, both deterministic
extracts with citation markers removed — no model call. The English one is the first
"Key decisions" bullets of the digest; the Japanese one is the same bullets of the
Japanese digest, which NotebookLM translates from the English when the meeting is
summarised. Meetings summarised before that existed, or whose translation did not line
up, use the first bullets of the briefing's 決定事項 section instead: a separate document,
so those points can differ, and the email says so. Building the report reads only the
DB; the energy-board feed is fetched by the caller and passed in.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from repower.policy import store
from repower.policy.energy_board import committee_meti_dir
from repower.timeutil import yesterday_jst

WINDOW_DAYS = 7  # the last 7 complete days (JST): sent Monday morning, Monday–Sunday
LATE_DAYS = 21  # how long before the window a meeting may be held and still be caught up
BRIEF_BULLETS = 3

SUMMARISED = "Summarised"
PENDING = "Summary pending"
FAILED = "Summary failed"
NOT_PUBLISHED = "Materials not yet published"
UNTRACKED = "Not tracked"


@dataclass
class WeeklyItem:
    """One meeting in the email."""

    date: date
    name: str  # English name when known, else the Japanese one
    name_ja: str | None
    org: str
    status: str
    tracked: bool
    committee_key: str | None = None
    meeting_num: int | None = None
    url: str | None = None
    brief: list[tuple[str, str]] = field(default_factory=list)  # (title, text); title may be ""
    brief_ja: list[tuple[str, str]] = field(default_factory=list)  # same shape
    brief_ja_matched: bool = False  # brief_ja is brief's translation, bullet for bullet (else: from the briefing)
    torimatome: bool = False


@dataclass
class WeeklyReport:
    start: date
    end: date
    summarised: list[WeeklyItem]
    late: list[WeeklyItem]
    held: list[WeeklyItem]
    undated: int = 0  # meetings detected in the past week with no known date (so not listed)

    @property
    def total_held(self) -> int:
        return len(self.summarised) + len(self.held)


# ── Brief extraction (pure) ──────────────────────────────────────────────────
_CITE_RE = re.compile(r"\s*\[\d+(?:\s*[-–,]\s*\d+)*\]")
# The Japanese briefing cites its papers inline: ［資料１ p.7］, [資料2], `[出典: 資料3]`,
# 【出典：資料3】, （出典: `x.pdf` P.12）, （議事録 p.1）.
_CITE_JA_RE = re.compile(
    r"\s*(?:［[^］]*］|`?\[(?:資料|出典)[^\]]*\]`?|【(?:出典|資料)[^】]*】|[（(]出典[^）)]*[）)]"
    r"|[（(](?:資料|議事録)[^）)]{0,15}[）)])"
)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*(.*?)\s*$")
_BULLET_RE = re.compile(r"^(\s*)(?:[*\-•]|\d+[.)])\s+(.*)$")
_TITLED_RE = re.compile(r"^\*\*(.+?)\*\*\s*[:：]?\s*(.*)$")
_GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ", "lambda": "λ", "sigma": "σ"}
# The briefing's conclusions section: "(3) 結論・決定事項", "3. 結論および事務局提案事項" —
# not "約定価格の決定方法".
_CONCLUSIONS_JA_RE = re.compile(r"結論|(?:決定|確定|合意).{0,10}事項")
_PAREN_JA_RE = re.compile(r"（[^）]*）")
_HEADING_LEVEL_RE = re.compile(r"^\s*(#{1,6})")
_BOLD_LINE_RE = re.compile(r"^\s*\*\*([^*]+)\*\*\s*$")  # "**【継続検討・事務局提案事項】**"


def _clean(s: str) -> str:
    s = _CITE_RE.sub("", s)
    s = re.sub(r"\\+[()\[\]]", "", s)  # LaTeX inline-math delimiters \( \) \[ \]
    s = re.sub(r"\\+([A-Za-z]+)", lambda m: _GREEK.get(m.group(1), m.group(1)), s)
    s = s.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", s).strip()


def _clean_ja(s: str) -> str:
    return _clean(_CITE_JA_RE.sub("", s))


def _undecided_ja(title: str) -> bool:
    """A 継続検討 / 未確定 / bare 事務局提案 heading — not "事務局提案に対し合意が得られた事項"
    or "決定・概ね合意された事項（事務局提案）"."""
    t = _PAREN_JA_RE.sub("", _clean_ja(title))
    if re.search(r"継続|未確定", t):
        return True
    return "提案" in t and not re.search(r"決定|確定|合意", t)


def _split_bullet(raw: str, ja: bool = False) -> tuple[str, str]:
    """``**Title**: body`` → (title, body). A title-only bullet ("**Title:**", its
    content in sub-bullets) returns an empty body for the caller to fill."""
    clean = _clean_ja if ja else _clean
    m = _TITLED_RE.match(raw.strip())
    if m:
        return clean(m.group(1)).rstrip(":： "), clean(m.group(2))
    return "", clean(raw)


def _digest_answer(digest_en_json: str | None) -> str:
    if not digest_en_json:
        return ""
    try:
        return (json.loads(digest_en_json) or {}).get("answer") or ""
    except (json.JSONDecodeError, TypeError, AttributeError):
        return ""


def _bullets(lines: list[str], from_idx: int, *, stop_at_heading: bool, limit: int,
             ja: bool = False) -> list[tuple[str, str]]:
    """The first ``limit`` top-level bullets from ``lines[from_idx:]``.

    With ``ja``, a bold-only line or top-level bullet naming undecided items (a
    pseudo-heading inside a combined 決定事項・継続検討 section) also ends the run.
    """
    out: list[tuple[str, str]] = []
    for ln in lines[from_idx:]:
        if stop_at_heading and (_HEADING_RE.match(ln) or ln.strip() == "---"):
            break
        if ja and (b := _BOLD_LINE_RE.match(ln)) and _undecided_ja(b.group(1)):
            break
        m = _BULLET_RE.match(ln)
        if not m:
            # An indented continuation line: the body of a title-only parent.
            if ln[:1].isspace() and ln.strip() and out and not out[-1][1]:
                out[-1] = (out[-1][0], _split_bullet(ln, ja)[1])
            continue
        if not m.group(2).strip():
            continue
        if len(m.group(1).expandtabs()) >= 2:
            # A sub-bullet: only used to fill a title-only parent.
            if out and not out[-1][1]:
                out[-1] = (out[-1][0], _split_bullet(m.group(2), ja)[1])
            continue
        if len(out) >= limit and out[-1][1]:
            break
        item = _split_bullet(m.group(2), ja)
        if ja and not item[1] and _undecided_ja(item[0]):
            break  # "- **事務局提案・継続検討事項：**" heading a group of sub-bullets
        out.append(item)
    return [(t, b) if b else ("", t) for t, b in out[:limit] if t or b]


def extract_brief(answer: str, limit: int = BRIEF_BULLETS) -> list[tuple[str, str]]:
    """The first ``limit`` top-level bullets of the digest's "Key decisions" (決定事項) section.

    Falls back to the first top-level bullets anywhere, then to the first paragraph,
    so a digest with a different shape still yields something. Citation markers,
    bold and LaTeX delimiters are stripped; bullets stay whole.
    """
    lines = (answer or "").splitlines()
    for i, ln in enumerate(lines):
        h = _HEADING_RE.match(ln)
        if h and re.search("key decision|決定事項", _clean(h.group(1)).lower()):
            found = _bullets(lines, i + 1, stop_at_heading=True, limit=limit)
            if found:
                return found
    found = _bullets(lines, 0, stop_at_heading=False, limit=limit)
    if found:
        return found
    for para in re.split(r"\n\s*\n", answer or ""):
        text = " ".join(ln for ln in para.splitlines() if not _HEADING_RE.match(ln) and ln.strip() != "---")
        if _clean(text):
            return [("", _clean(text))]
    return []


def _decided_blocks(lines: list[str], start: int) -> list[int]:
    """Heading indices of the section at *start* and its subsections, less the
    undecided ones (and everything nested under them)."""
    level = len(_HEADING_LEVEL_RE.match(lines[start]).group(1))  # type: ignore[union-attr]
    blocks = [start]
    skip_below: int | None = None
    for i in range(start + 1, len(lines)):
        h = _HEADING_RE.match(lines[i])
        if not h:
            continue
        lv = len(_HEADING_LEVEL_RE.match(lines[i]).group(1))  # type: ignore[union-attr]
        if lv <= level:
            break
        if skip_below is not None and lv > skip_below:
            continue
        skip_below = lv if _undecided_ja(h.group(1)) else None
        if skip_below is None:
            blocks.append(i)
    return blocks


def _first_paragraph_ja(lines: list[str], from_idx: int) -> str:
    body: list[str] = []
    for ln in lines[from_idx:]:
        if _HEADING_RE.match(ln) or ln.strip() == "---":
            break
        body.append(ln)
    for para in re.split(r"\n\s*\n", "\n".join(body)):
        text = _clean_ja(" ".join(para.splitlines()))
        if text and not text.startswith("出典") and not _BOLD_LINE_RE.match(para.strip()):
            return text
    return ""


def extract_brief_ja(briefing: str, limit: int = BRIEF_BULLETS) -> list[tuple[str, str]]:
    """The first ``limit`` top-level bullets of the Japanese briefing's decisions.

    The briefing prompt asks for a "(3) 結論・決定事項" section that keeps decisions
    apart from 事務局提案・継続検討 items. Its wording and layout vary — subsections,
    bold pseudo-headings, or a bullet heading each group — so this walks that section
    and skips whatever is marked undecided. When the decided part has no bullets (a
    hearing-only meeting says in prose that nothing was decided) its first paragraph
    stands in. No such section → no brief: falling back to the first bullets anywhere
    would surface the agenda list, which reads like decisions.
    """
    lines = (briefing or "").splitlines()
    covered: set[int] = set()
    for start, ln in enumerate(lines):
        h = _HEADING_RE.match(ln)
        if start in covered or not h or not _CONCLUSIONS_JA_RE.search(_PAREN_JA_RE.sub("", _clean_ja(h.group(1)))):
            continue
        blocks = _decided_blocks(lines, start)
        covered.update(blocks)
        for b in blocks:
            found = _bullets(lines, b + 1, stop_at_heading=True, limit=limit, ja=True)
            if found:
                return found
        for b in blocks:
            if text := _first_paragraph_ja(lines, b + 1):
                return [("", text)]
    return []


def _set_briefs(it: WeeklyItem, m: dict) -> None:
    """Both briefs of a summarised meeting. The Japanese digest counts only when it has as many
    bullets as the English, the one sign available here that it did not merge or drop any."""
    en, ja = _digest_answer(m["digest_en_json"]), _digest_answer(m["digest_ja_json"])
    it.brief = extract_brief(en)
    if ja and len(extract_brief(ja, limit=999)) == len(extract_brief(en, limit=999)):
        it.brief_ja, it.brief_ja_matched = extract_brief(ja), True
    else:
        it.brief_ja = extract_brief_ja(m["briefing_md"])


# ── Assembly ─────────────────────────────────────────────────────────────────
def _norm(s: str | None) -> str:
    s = re.sub(r"第\s*\d+\s*回", "", s or "")
    return re.sub(r"[\s　（）()・,、]+", "", s)


def _match_registry(name: str | None, committees: list[dict]) -> str | None:
    """The catalog committee whose Japanese name appears in *name* (longest wins)."""
    n = _norm(name)
    best: tuple[int, str] | None = None
    for c in committees:
        cn = _norm(c.get("name_ja"))
        if len(cn) >= 4 and cn in n and (best is None or len(cn) > best[0]):
            best = (len(cn), c["key"])
    return best[1] if best else None


def _meeting_status(state: str | None) -> str:
    if state == "done":
        return SUMMARISED
    if state == "error":
        return FAILED
    return PENDING


def _sort(items: list[WeeklyItem]) -> list[WeeklyItem]:
    return sorted(items, key=lambda x: (-x.date.toordinal(), x.name, x.meeting_num or 0))


def build_report(
    db_path: str | None = None,
    *,
    end: date | None = None,
    now: datetime | None = None,
    board: list | None = None,
    days: int = WINDOW_DAYS,
) -> WeeklyReport:
    """Assemble the weekly report for the ``days`` ending on *end* (inclusive).

    *end* defaults to yesterday (JST): only complete days, so the Monday-morning run
    covers the previous Monday–Sunday and never lists that morning's meetings as held.
    *board* is the energy-board feed (``energy_board.BoardEntry`` list), fetched by
    the caller so this function never touches the network.
    """
    end = end or yesterday_jst()
    now = now or datetime.now(UTC)
    start = end - timedelta(days=days - 1)
    since = now - timedelta(days=days)

    committees = store.list_committees(db_path=db_path)
    by_key = {c["key"]: c for c in committees}
    dir_to_key: dict[str, str] = {}
    for c in committees:
        d = committee_meti_dir(SimpleNamespace(url=c.get("url")))
        if d:
            dir_to_key.setdefault(d, c["key"])

    def tracked(key: str | None) -> bool:
        return bool(key and by_key.get(key, {}).get("enabled"))

    def item(key: str | None, *, day: date, num: int | None, status: str, raw_name: str | None = None,
             org: str | None = None, url: str | None = None) -> WeeklyItem:
        c = by_key.get(key) if key else None
        name_ja = (c or {}).get("name_ja") or raw_name
        name_en = (c or {}).get("name_en")
        name = name_en if name_en and name_en != key else (name_ja or key or "")
        return WeeklyItem(
            date=day, name=name, name_ja=name_ja if name_ja != name else None,
            org=(c or {}).get("source") or org or "METI", status=status, tracked=tracked(key),
            committee_key=key, meeting_num=num, url=(c or {}).get("url") or url,
        )

    summarised: list[WeeklyItem] = []
    held: list[WeeklyItem] = []
    seen_num: set[tuple[str, int]] = set()
    seen_day: set[tuple[str, date]] = set()
    seen_name: dict[date, list[str]] = {}

    # 1) Detected meetings (any catalog committee) held in the window.
    for m in store.meetings_for_week(start, end, db_path=db_path):
        key, num, day = m["committee_key"], m["meeting_num"], m["meeting_date"]
        it = item(key, day=day, num=num, status=_meeting_status(m["state"]))
        it.torimatome = m["has_torimatome"]
        if it.tracked and m["state"] == "done":
            _set_briefs(it, m)
            summarised.append(it)
        else:
            held.append(it)
        seen_num.add((key, num))
        seen_day.add((key, day))

    known_cache: dict[str, set[int]] = {}

    def known(key: str) -> set[int]:
        if key not in known_cache:
            known_cache[key] = store.known_meeting_nums(key, db_path=db_path)
        return known_cache[key]

    # 2) + 3) Calendar history and the energy-board feed: meetings that left no
    # detection row (untracked committees, or materials not yet published).
    def add_external(day: date, raw_name: str, key: str | None, num: int | None,
                     org: str | None, url: str | None) -> None:
        if key and ((num is not None and (key, num) in seen_num) or (key, day) in seen_day):
            return
        if not key:
            n = _norm(raw_name)
            if not n or any(n in s or s in n for s in seen_name.get(day, [])):
                return
            seen_name.setdefault(day, []).append(n)
        if key is None or not tracked(key):
            status = UNTRACKED
        elif num is not None and num in known(key):
            status = PENDING  # detected, but its date is not filled in yet
        else:
            status = NOT_PUBLISHED
        held.append(item(key, day=day, num=num, status=status, raw_name=raw_name, org=org, url=url))
        if key:
            if num is not None:
                seen_num.add((key, num))
            seen_day.add((key, day))

    for u in store.calendar_entries(start, end, db_path=db_path):
        key = u["committee_key"] or _match_registry(u["name_ja"], committees)
        add_external(date.fromisoformat(u["date"]), u["name_ja"], key, u["meeting_num"],
                     u["org"], u["source_url"])
    for b in board or []:
        if b.date is None or not (start <= b.date <= end):
            continue
        key = dir_to_key.get(b.meti_dir or "") or _match_registry(b.council, committees)
        add_external(b.date, b.title or b.council, key, b.meeting_num, "METI", b.meeting_url)

    # Summaries now available: held before the window, summary landed this week.
    late = []
    for m in store.meetings_for_week(start - timedelta(days=LATE_DAYS), start - timedelta(days=1),
                                     db_path=db_path, summarised_since=since):
        if not tracked(m["committee_key"]):
            continue
        it = item(m["committee_key"], day=m["meeting_date"], num=m["meeting_num"], status=SUMMARISED)
        it.torimatome = m["has_torimatome"]
        _set_briefs(it, m)
        late.append(it)

    return WeeklyReport(
        start=start, end=end, summarised=_sort(summarised), late=_sort(late), held=_sort(held),
        undated=store.undated_meetings_detected_since(since, db_path=db_path),
    )


# ── Rendering ────────────────────────────────────────────────────────────────
def fmt_range(start: date, end: date) -> str:
    if start.year != end.year:
        return f"{start.day} {start:%b %Y} – {end.day} {end:%b %Y}"
    if start.month != end.month:
        return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"
    return f"{start.day}–{end.day} {end:%b %Y}"


def _fmt_day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _label(it: WeeklyItem) -> str:
    if it.meeting_num is None or re.search(rf"第\s*{it.meeting_num}\s*回", it.name):
        return it.name  # a raw calendar/feed name already carries its number
    return f"{it.name} 第{it.meeting_num}回"


def subject(report: WeeklyReport) -> str:
    n = report.total_held
    held = f"{n} meeting{'s' if n != 1 else ''} held" if n else "no meetings held"
    return f"JEMA weekly policy summary — {fmt_range(report.start, report.end)} ({held})"


_EMPTY_SUMMARISED = "No tracked meeting held last week has a summary yet."
_EMPTY_HELD = "No other committee meetings were recorded last week."


def _briefs(it: WeeklyItem) -> list[tuple[str, str, str, list[tuple[str, str]]]]:
    """(label, lang, title separator, bullets) for each language that has a brief."""
    ja = "日本語" if it.brief_ja_matched or not it.brief else "日本語（ブリーフィングより抜粋）"
    out = [("English", "en", ": ", it.brief), (ja, "ja", "：", it.brief_ja)]
    return [b for b in out if b[3]]


def render_text(report: WeeklyReport) -> str:
    out = ["JEMA weekly policy summary", f"Committee meetings held {fmt_range(report.start, report.end)}", ""]

    def block(title: str, items: list[WeeklyItem], empty: str | None, with_status: bool) -> None:
        if not items and empty is None:
            return
        out.append(f"{title.upper()} ({len(items)})")
        if not items:
            out.extend([f"  {empty}", ""])
            return
        for it in items:
            status = f" — {it.status}" if with_status else ""
            flag = " [とりまとめ]" if it.torimatome else ""
            out.append(f"- {_fmt_day(it.date)} · {_label(it)} [{it.org}]{flag}{status}")
            if it.name_ja:
                out.append(f"  {it.name_ja}")
            briefs = _briefs(it)
            for label, _, sep, bullets in briefs:
                if len(briefs) > 1:
                    out.append(f"  [{label}]")
                for t, body in bullets:
                    out.append(f"  • {t}{sep}{body}" if t else f"  • {body}")
            if it.url:
                out.append(f"  {it.url}")
        out.append("")

    block("Tracked & summarised", report.summarised, _EMPTY_SUMMARISED, False)
    block("Summaries now available (held earlier)", report.late, None, False)
    block("Also held last week", report.held, _EMPTY_HELD, True)
    if report.undated:
        out.append(_undated_note(report.undated))
    return "\n".join(out).rstrip() + "\n"


def _undated_note(n: int) -> str:
    if n == 1:
        return "1 meeting detected in the past week has no known date yet, so it is not listed."
    return f"{n} meetings detected in the past week have no known date yet, so they are not listed."


_STATUS_COLORS = {
    SUMMARISED: ("#065f46", "#d1fae5"),
    PENDING: ("#92400e", "#fef3c7"),
    NOT_PUBLISHED: ("#92400e", "#fef3c7"),
    FAILED: ("#991b1b", "#fee2e2"),
    UNTRACKED: ("#374151", "#e5e7eb"),
}


def _source_note(report: WeeklyReport) -> str:
    note = "Briefs are extracts of each meeting's English digest and its Japanese translation."
    if any(it.brief_ja and not it.brief_ja_matched for it in report.summarised + report.late):
        note += (" Japanese briefs marked ブリーフィングより抜粋 come from the meeting's Japanese briefing, "
                 "a separate document, so they may cover different points.")
    return note


def render_html(report: WeeklyReport) -> str:
    e = html.escape
    parts = [
        '<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#1f2937;max-width:680px;'
        'margin:0 auto;font-size:14px;line-height:1.5">',
        '<h1 style="font-size:20px;margin:0 0 4px">JEMA weekly policy summary</h1>',
        f'<p style="margin:0 0 20px;color:#6b7280">Committee meetings held '
        f"{e(fmt_range(report.start, report.end))}</p>",
    ]

    def pill(status: str) -> str:
        fg, bg = _STATUS_COLORS.get(status, ("#374151", "#e5e7eb"))
        return (f'<span style="display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;'
                f'color:{fg};background:{bg}">{e(status)}</span>')

    def block(title: str, items: list[WeeklyItem], empty: str | None, with_status: bool) -> None:
        if not items and empty is None:
            return
        parts.append(f'<h2 style="font-size:16px;margin:24px 0 8px;padding-bottom:4px;'
                     f'border-bottom:1px solid #e5e7eb">{e(title)} ({len(items)})</h2>')
        if not items:
            parts.append(f'<p style="color:#6b7280;margin:0">{e(empty or "")}</p>')
            return
        for it in items:
            name = e(_label(it))
            if it.url:
                name = f'<a href="{e(it.url, quote=True)}" style="color:#1d4ed8;text-decoration:none">{name}</a>'
            meta = f"{e(_fmt_day(it.date))} · {e(it.org)}"
            if it.torimatome:
                meta += " · とりまとめ"
            parts.append('<div style="margin:0 0 14px">')
            parts.append(f'<div style="font-weight:600">{name}'
                         + (f" {pill(it.status)}" if with_status else "") + "</div>")
            sub = meta + (f" · {e(it.name_ja)}" if it.name_ja else "")
            parts.append(f'<div style="color:#6b7280;font-size:12px">{sub}</div>')
            briefs = _briefs(it)
            for label, lang, sep, bullets in briefs:
                if len(briefs) > 1:
                    parts.append(f'<div style="margin:8px 0 0;color:#6b7280;font-size:11px;font-weight:600;'
                                 f'letter-spacing:.04em">{e(label)}</div>')
                top = "2px" if len(briefs) > 1 else "6px"
                parts.append(f'<ul lang="{lang}" style="margin:{top} 0 0;padding-left:20px">')
                for t, body in bullets:
                    head = f"<b>{e(t)}</b>{sep}" if t else ""
                    parts.append(f'<li style="margin:2px 0">{head}{e(body)}</li>')
                parts.append("</ul>")
            parts.append("</div>")

    block("Tracked & summarised", report.summarised, _EMPTY_SUMMARISED, False)
    block("Summaries now available (held earlier)", report.late, None, False)
    block("Also held last week", report.held, _EMPTY_HELD, True)
    if report.undated:
        parts.append(f'<p style="color:#6b7280;font-size:12px;margin-top:20px">{e(_undated_note(report.undated))}</p>')
    parts.append('<p style="color:#9ca3af;font-size:12px;margin-top:24px">Sent by the weekly-summary '
                 f"workflow. {e(_source_note(report))}</p></div>")
    return "\n".join(parts)
