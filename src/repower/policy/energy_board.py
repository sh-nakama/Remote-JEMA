"""Backup + cross-check source: energy-board.xvps.jp ("Energy Board Japan").

A third-party aggregator that scrapes the most recent METI 審議会 documents into a
single feed (``robots.txt``: ``Allow: /``). We use it two ways:

1. **Backup** — when a direct METI fetch fails (Akamai 403 / timeout / a changed
   index), :mod:`repower.policy.scraper` falls back here to still discover a METI
   committee's recent meetings + their document URLs. Its links point back to the
   same ``meti.go.jp`` PDFs, and it also carries the meeting *date* (which the METI
   subpages don't always expose).
2. **Cross-check** — a monthly diff of the committees energy-board surfaces vs our
   catalog, to flag active energy committees we don't yet track.

Only the site's latest-meetings feed is server-rendered (its ``?search=`` is a
client-side filter), so this covers *recent* documents — what daily detection
needs — not deep history, and only METI committees (the aggregator is METI-only).

Pure ``parse_feed`` is fixture-tested; networked ``fetch_feed`` uses the shared
HTTP cache and memoises for a few minutes. Every failure degrades to an empty
result (never raised into the caller) so a flaky third-party site can't break
detection.
"""

from __future__ import annotations

import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from repower.policy.scraper import Material, _materials_from_links, parse_jp_date
from repower.scrapers.http_cache import conditional_get

logger = logging.getLogger(__name__)

BASE_URL = "https://energy-board.xvps.jp/"
REQUEST_TIMEOUT = 40.0
_FEED_TTL = 600.0  # seconds — memoise the feed so a detect pass doesn't refetch it


@dataclass
class BoardEntry:
    """One meeting row from the energy-board feed."""

    council: str  # 審議会名 (span.council-link)
    title: str  # full meeting title (contains 第N回)
    meti_dir: str | None  # METI path between /shingikai/ and /NNN.html (committee id)
    meeting_url: str  # meti.go.jp NNN.html
    meeting_num: int | None
    date: datetime.date | None
    pdfs: list[dict] = field(default_factory=list)  # [{url, text}] — meti.go.jp PDFs


# ── Pure parsing (no network) ────────────────────────────────────────────────
def meti_dir_of(url: str | None) -> str | None:
    """The committee id from a METI meeting URL: the path between ``/shingikai/``
    and ``/NNN.html`` (e.g. ``enecho/denryoku_gas/saisei_kano``). None if not a
    METI numbered-meeting URL."""
    if not url:
        return None
    m = re.match(r"^https?://www\.meti\.go\.jp/shingikai/(.+?)/\d+\.html", url)
    return m.group(1) if m else None


def _meeting_num(title: str, url: str) -> int | None:
    m = re.search(r"第\s*(\d+)\s*回", title or "")
    if m:
        return int(m.group(1))
    m = re.search(r"/(\d+)\.html", url or "")
    return int(m.group(1)) if m else None


def parse_feed(content: bytes | str, base_url: str = BASE_URL) -> list[BoardEntry]:
    """Parse the energy-board latest-meetings table into :class:`BoardEntry` rows.

    Each ``<td class="meeting-content">`` holds the meeting title link + a
    ``<ol class="doc-list">`` of PDFs; the sibling cells carry the date and council.
    """
    soup = BeautifulSoup(content, "lxml")
    out: list[BoardEntry] = []
    for cell in soup.select("td.meeting-content"):
        a = cell.select_one("div.meeting-title a[href]")
        if not a:
            continue
        url = urljoin(base_url, a["href"])
        title = a.get_text(" ", strip=True)
        council = ""
        date = None
        tr = cell.find_parent("tr")
        if tr is not None:
            cl = tr.select_one("span.council-link")
            council = cl.get_text(" ", strip=True) if cl else ""
            dc = tr.select_one("td.date-col")
            if dc is not None:
                date = parse_jp_date(dc.get_text(" ", strip=True))
        pdfs: list[dict] = []
        for p in cell.select("ol.doc-list a[href]"):
            href = p["href"]
            if href.lower().split("?")[0].endswith(".pdf"):
                pdfs.append({"url": urljoin(base_url, href), "text": p.get_text(" ", strip=True)})
        out.append(
            BoardEntry(
                council=council,
                title=title,
                meti_dir=meti_dir_of(url),
                meeting_url=url,
                meeting_num=_meeting_num(title, url),
                date=date,
                pdfs=pdfs,
            )
        )
    return out


def committee_meti_dir(committee) -> str | None:
    """The energy-board committee id for one of our committees, or None for a
    non-METI (OCCTO/EGC) committee that the aggregator won't carry."""
    return _url_to_dir(getattr(committee, "url", None))


def _url_to_dir(url: str | None) -> str | None:
    if not url:
        return None
    p = urlparse(url)
    if "meti.go.jp" not in (p.netloc or ""):
        return None
    m = re.match(r"^/shingikai/(.+?)/?$", re.sub(r"index\.html$", "", p.path or ""))
    return m.group(1).rstrip("/") if m else None


# ── Networked fetch (memoised) ───────────────────────────────────────────────
_feed_cache: list[BoardEntry] | None = None
_feed_ts: float = 0.0


def _fetch(url: str, *, db_path: str | None = None) -> bytes | None:
    try:
        status, content = conditional_get(
            url, db_path=db_path, headers={"Accept-Language": "ja,en;q=0.9"},
            allow_curl_fallback=True, force=True, timeout=REQUEST_TIMEOUT,
        )
        return content if status == "ok" else None
    except Exception as e:  # noqa: BLE001 — third-party site must never break detection
        logger.warning("energy-board fetch failed %s: %s", url, e)
        return None


def fetch_feed(*, db_path: str | None = None, refresh: bool = False) -> list[BoardEntry]:
    """The current energy-board feed, memoised for ``_FEED_TTL`` seconds."""
    global _feed_cache, _feed_ts
    now = time.time()
    if _feed_cache is not None and not refresh and (now - _feed_ts) < _FEED_TTL:
        return _feed_cache
    content = _fetch(BASE_URL, db_path=db_path)
    if content is not None:
        _feed_cache, _feed_ts = parse_feed(content), now
    elif _feed_cache is None:
        _feed_cache = []
    return _feed_cache


# ── Backup helpers (used by the scraper on METI failure) ─────────────────────
def entries_for_committee(committee, *, db_path: str | None = None) -> list[BoardEntry]:
    d = committee_meti_dir(committee)
    if not d:
        return []
    return [e for e in fetch_feed(db_path=db_path) if e.meti_dir == d]


def recent_meeting_nums(committee, *, db_path: str | None = None) -> list[int]:
    """Recent meeting numbers energy-board knows for *committee* (backup for a
    failed METI index fetch). Empty for non-METI committees or when unavailable."""
    return sorted({e.meeting_num for e in entries_for_committee(committee, db_path=db_path) if e.meeting_num})


def materials_for(committee, meeting_num: int, *, db_path: str | None = None) -> list[Material]:
    """Documents for one meeting from energy-board (backup for a failed METI meeting
    page). The PDF URLs are the same meti.go.jp files; empty if not in the feed."""
    for e in entries_for_committee(committee, db_path=db_path):
        if e.meeting_num == meeting_num and e.pdfs:
            return _materials_from_links(meeting_num, e.pdfs)
    return []


# ── Cross-check (monthly) ────────────────────────────────────────────────────
def _missing_to_items(missing: list[dict]) -> list[dict]:
    """Map cross-check ``missing`` rows to catalog items for the discovered-committee
    upsert. energy-board only carries METI committees, whose committee index is
    ``/shingikai/<dir>/`` — the same shape the METI scraper enumerates generically,
    so a committee added this way is scrapeable once the user tracks it. The key is
    the last path segment (``energy_environment/gx_demand`` → ``gx_demand``); the
    upsert disambiguates a colliding key and dedups by normalised URL."""
    items: list[dict] = []
    for m in missing:
        d = (m.get("dir") or "").strip("/")
        if not d:
            continue
        key = d.split("/")[-1]
        items.append({
            "key": key,
            "name_ja": m.get("council") or key,
            "source": "METI",
            "url": f"https://www.meti.go.jp/shingikai/{d}/",
        })
    return items


def cross_check(*, db_path: str | None = None, persist: bool = True) -> dict:
    """Diff the committees in energy-board's recent feed against our catalog and
    accumulate any we're missing into the catalog.

    Returns ``{"theirs", "matched", "missing": [{dir, council, url, date}], "added"}``
    where *missing* are committees energy-board is surfacing that our catalog did not
    contain (by METI path) — i.e. energy committees we were failing to track. With
    ``persist`` (the default) those are upserted as **discovered / untracked**
    catalog rows, so they show up in the Manage modal and ``committees.json`` for the
    user to start tracking — this is what makes the monthly run *accumulate* coverage
    (a committee found once stays known, and on the next run counts as ``matched``).
    Only the aggregator's recent feed is visible, hence the monthly cadence.
    """
    from repower.policy.store import list_committees, upsert_discovered_committees

    entries = fetch_feed(db_path=db_path, refresh=True)
    theirs: dict[str, dict] = {}
    for e in entries:
        if e.meti_dir and e.meti_dir not in theirs:
            theirs[e.meti_dir] = {
                "dir": e.meti_dir,
                "council": e.council or e.title,
                "url": e.meeting_url,
                "date": e.date.isoformat() if e.date else None,
            }
    ours = {d for d in (_url_to_dir(c["url"]) for c in list_committees(db_path=db_path)) if d}
    missing = [info for d, info in sorted(theirs.items()) if d not in ours]
    added = 0
    if persist and missing:
        added = upsert_discovered_committees(_missing_to_items(missing), db_path=db_path)
    return {"theirs": len(theirs), "matched": len(theirs) - len(missing),
            "missing": missing, "added": added}
