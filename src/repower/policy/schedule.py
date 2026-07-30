"""Fetch + parse the forward-looking committee meeting schedule.

Committee pages only publish a meeting once its materials exist, so they cannot
supply genuinely *upcoming* meetings. The **METI committee calendar**
(``wwws.meti.go.jp/.../committee/``) can — it is the authoritative forward list of
METI 審議会・研究会. It covers all of METI (not just energy), so entries are filtered
by an energy-relevance keyword set.

Each entry is matched to a tracked committee where possible (so it lines up with
follow / the radar) and otherwise surfaced as an untracked energy meeting.

Pure parse functions (``parse_*``, ``is_energy_relevant``, ``match_committee``) do
no network and are unit-tested against fixtures; ``fetch_upcoming`` / ``refresh_upcoming``
compose them with the shared HTTP cache.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from repower.policy.committees import COMMITTEES
from repower.policy.scraper import parse_jp_date
from repower.scrapers.http_cache import conditional_get
from repower.timeutil import today_jst

logger = logging.getLogger(__name__)

METI_CALENDAR_URL = "https://wwws.meti.go.jp/interface/honsho/committee/index.cgi/committee/"
REQUEST_TIMEOUT = 40.0

# The METI site answers with an HTTP-200 "overload/failover" holding page when it is
# busy ("ただいまアクセスが集中しております") instead of the calendar. It carries no dates, so a
# naive parse yields zero meetings — which must NOT be mistaken for "no upcoming
# meetings" and used to wipe the snapshot. These markers identify that holding page.
_UNAVAILABLE_MARKERS = ("アクセスが集中", "ただいまアクセス")


class ScheduleUnavailable(RuntimeError):
    """The upcoming-schedule feed could not be fetched — a network error or the METI
    overload/failover holding page (HTTP 200 with no calendar). Raised by
    ``refresh_upcoming`` so a transient outage is reported *without* replacing the
    existing ``policy_upcoming`` snapshot with an empty set."""

# Standalone category tokens on the METI calendar (a line that is *exactly* one of
# these is a category label, not a meeting name).
_METI_CATEGORIES = {"審議会", "研究会", "会合", "検討会", "懇談会", "会議", "分科会"}

# Energy-market relevance keywords (used to keep only energy entries from the
# all-of-METI calendar).
_ENERGY_KEYWORDS = (
    "電力", "電気", "ガス", "エネルギー", "再生可能", "再エネ", "需給", "容量",
    "系統", "送配電", "調整力", "広域", "排出量", "脱炭素", "洋上風力", "電源",
    "資源エネルギー", "燃料", "蓄電", "調達価格", "託送", "インバランス",
    "制度設計", "市場", "原子力",
)
# Terms that share a kanji with an energy keyword (電気通信 → 電気) but are not the
# energy market. Excluded unless a stronger energy term is also present.
_ENERGY_EXCLUDE = ("電気通信", "情報通信", "電波", "郵政", "モバイル", "放送", "通信技術")
_STRONG_ENERGY = ("電力", "エネルギー", "ガス", "需給", "系統", "再生可能", "再エネ",
                  "送配電", "容量", "脱炭素", "調整力", "排出量")

_FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


@dataclass
class Upcoming:
    """One scheduled (future) committee meeting."""

    date: datetime.date
    name_ja: str
    org: str  # METI | OCCTO | EGC (from the matched committee)
    source: str  # meti (the METI committee calendar)
    source_url: str
    meeting_num: int | None = None
    committee_key: str | None = None  # matched tracked committee, else None

    @property
    def source_key(self) -> str:
        """Normalised name for cross-source dedup (drops 第N回 + whitespace)."""
        return _norm(re.sub(r"第\s*\d+\s*回", "", self.name_ja))


# ── Pure helpers (no network) ────────────────────────────────────────────────
def _norm(s: str | None) -> str:
    return re.sub(r"[\s　]+", "", (s or "")).translate(_FULLWIDTH)


def _text_lines(content: bytes | str) -> list[str]:
    soup = BeautifulSoup(content, "lxml")
    out = []
    for ln in soup.get_text("\n", strip=True).split("\n"):
        ln = ln.strip().translate(_FULLWIDTH)
        if ln:
            out.append(ln)
    return out


# A full date anchored at the very start of the line (a schedule date header).
# Anchoring the whole date — not just a leading year — stops a meeting NAME that
# begins with a fiscal/target year (e.g. ``2030年度…（2030年3月1日…）``) from being
# misread as a date row, which would drop the real entry.
_DATE_HEADER_RE = re.compile(
    r"^\s*(?:(?:令和|平成|昭和)\s*(?:元|\d{1,2})\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|20\d{2}\s*[年./\-]\s*\d{1,2}\s*[月./\-]\s*\d{1,2})"
)


def _date_at_start(line: str) -> datetime.date | None:
    """Parse a date only when the line *begins* with a full date (a schedule date
    header), so meeting names that merely contain a year/number aren't mistaken
    for dates."""
    if _DATE_HEADER_RE.match(line):
        return parse_jp_date(line)
    return None


def _meeting_num(name: str) -> int | None:
    m = re.search(r"第\s*(\d+)\s*回", name)
    return int(m.group(1)) if m else None


def is_energy_relevant(name: str) -> bool:
    """True if a meeting name is about the energy market / grid / energy policy.

    A name that merely shares a kanji with an energy term but is really telecoms /
    broadcasting (e.g. ``電気通信`` → ``電気``) is excluded unless it also carries a
    strong energy term.
    """
    if any(x in name for x in _ENERGY_EXCLUDE) and not any(k in name for k in _STRONG_ENERGY):
        return False
    return any(k in name for k in _ENERGY_KEYWORDS)


def match_committee(name: str) -> str | None:
    """Match a schedule entry to a tracked committee by its official JA name.

    Returns the committee key whose ``name_ja`` appears (whitespace-insensitive)
    inside the entry text, else None. Longest committee name wins on overlap.
    """
    n = _norm(name)
    best: tuple[int, str] | None = None
    for c in COMMITTEES:
        cn = _norm(c.name_ja)
        if cn and cn in n and (best is None or len(cn) > best[0]):
            best = (len(cn), c.key)
    return best[1] if best else None


def _make(date: datetime.date, name: str, org: str, source: str, url: str) -> Upcoming:
    key = match_committee(name)
    if key:
        org = next((c.source for c in COMMITTEES if c.key == key), org)
    return Upcoming(
        date=date, name_ja=name, org=org, source=source, source_url=url,
        meeting_num=_meeting_num(name), committee_key=key,
    )


def parse_meti_calendar(content: bytes | str, base_url: str = METI_CALENDAR_URL) -> list[Upcoming]:
    """Parse the METI committee calendar → energy-relevant upcoming meetings.

    The page repeats ``<date> / <category> / <name>`` per entry. For each date
    line, the meeting name is the first following non-category line (bounded to a
    few lines so trailing footer text can't be picked up).
    """
    lines = _text_lines(content)
    n = len(lines)
    out: list[Upcoming] = []
    for i, line in enumerate(lines):
        d = _date_at_start(line)
        if d is None:
            continue
        name = None
        for k in range(i + 1, min(i + 4, n)):
            cand = lines[k]
            if _date_at_start(cand) is not None:
                break
            if cand in _METI_CATEGORIES or len(cand) < 5:
                continue
            name = cand
            break
        if name and (is_energy_relevant(name) or match_committee(name)):
            out.append(_make(d, name, "METI", "meti", base_url))
    return out


def _dedupe_future(items: list[Upcoming], today: datetime.date) -> list[Upcoming]:
    """Keep only future (>= today) entries, deduped on (date, source_key).

    A tracked-committee match wins over an unmatched duplicate; otherwise the
    first seen wins. Sorted by date ascending.
    """
    best: dict[tuple, Upcoming] = {}
    for it in items:
        if it.date < today:
            continue
        k = (it.date, it.source_key)
        cur = best.get(k)
        if cur is None or (it.committee_key and not cur.committee_key):
            best[k] = it
    return sorted(best.values(), key=lambda x: (x.date, x.org, x.name_ja))


# ── Networked fetch ──────────────────────────────────────────────────────────
def _looks_unavailable(content: bytes) -> bool:
    """True if *content* is the METI overload/failover holding page (not real data)."""
    head = content[:8192].decode("utf-8", "replace")
    return any(m in head for m in _UNAVAILABLE_MARKERS)


def _fetch(url: str, *, db_path: str | None = None) -> bytes | None:
    try:
        status, content = conditional_get(
            url, db_path=db_path, headers={"Accept-Language": "ja,en;q=0.9"},
            allow_curl_fallback=True, force=True, timeout=REQUEST_TIMEOUT,
        )
        if status != "ok" or content is None:
            return None
        if _looks_unavailable(content):
            logger.warning(
                "schedule fetch: %s served the site's overload/failover page; treating as unavailable", url,
            )
            return None
        return content
    except Exception as e:  # noqa: BLE001 — one bad source must not abort the refresh
        logger.warning("schedule fetch failed %s: %s", url, e)
        return None


def fetch_upcoming(*, db_path: str | None = None, today: datetime.date | None = None) -> list[Upcoming]:
    """Fetch the METI committee calendar, filter to energy + future, dedupe, and
    match committees. Returns upcoming meetings sorted by date (soonest first)."""
    today = today or today_jst()
    items: list[Upcoming] = []
    meti = _fetch(METI_CALENDAR_URL, db_path=db_path)
    if meti is not None:
        items.extend(parse_meti_calendar(meti))
    return _dedupe_future(items, today)


def refresh_upcoming(*, db_path: str | None = None, today: datetime.date | None = None) -> int:
    """Refresh the ``policy_upcoming`` snapshot from the live schedule sources.

    Fully replaces the table (it's a rolling snapshot). Returns the row count.

    Raises ``ScheduleUnavailable`` when the feed can't be fetched (network error or the
    METI overload/failover page) so a transient outage does NOT clobber the existing
    snapshot with an empty set. Both callers — the CLI pipeline and the web-api catch-up
    job — already treat that as a soft, non-fatal "feed unavailable".
    """
    from repower.policy.store import replace_upcoming

    today = today or today_jst()
    meti = _fetch(METI_CALENDAR_URL, db_path=db_path)
    if meti is None:
        raise ScheduleUnavailable(
            "METI committee calendar unavailable (network error or overload page); "
            "keeping the existing upcoming snapshot"
        )
    rows = _dedupe_future(parse_meti_calendar(meti), today)
    replace_upcoming(rows, db_path=db_path)
    logger.info("policy schedule: %d upcoming meeting(s) (%d matched to tracked committees)",
                len(rows), sum(1 for r in rows if r.committee_key))
    return len(rows)
