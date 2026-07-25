"""Fetch + parse policy-committee pages to discover meetings and their materials.

Ported from the reference ``committee_scraper.py`` (requests + bs4) onto the
project's shared ``conditional_get`` HTTP cache (httpx) + ``BeautifulSoup(lxml)``,
with prior branding stripped. Two responsibilities, kept separate:

- **Pure parse functions** (``parse_*``, ``classify_material``, ``extract_*``) take
  bytes/strings and do no network — these are unit-tested against saved fixtures.
- **Networked discovery** (``discover_meetings``, ``list_materials``) compose the
  parse functions with ``conditional_get`` and the OCCTO meeting-number probe.

Discovery is split into *which meetings exist* (cheap: one cached index fetch, or
a bounded probe) and *what documents a meeting has* (one fetch of that meeting's
page), so the daily no-auth detection stays cheap while material enumeration is
done only for genuinely new meetings.
"""

from __future__ import annotations

import datetime
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from repower.policy.committees import EGC_ACTIVITY_BASE, Committee
from repower.scrapers.http_cache import conditional_get

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30.0
POLITE_DELAY = 1.0  # seconds between consecutive page fetches (be a good citizen)
PROBE_GAP_TOLERANCE = 3  # consecutive missing OCCTO pages before declaring "no more"
PROBE_HARD_CAP = 400  # absolute ceiling on probe range, just in case

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0 Safari/537.36"
)


# ── Result types ─────────────────────────────────────────────────────────────
@dataclass
class Material:
    """One source document (PDF) found on a meeting page."""

    meeting_num: int
    pdf_id: str
    url: str
    title: str  # link text
    kind: str  # minutes | brief | compilation | appendix | handout | agenda | other


@dataclass
class Discovery:
    """Result of ``discover_meetings``.

    ``status`` is ``ok`` (meeting list valid), ``unchanged`` (index 304'd — no new
    meetings), or ``error`` (fetch/parse failed; ``meeting_nums`` is empty).
    """

    status: str
    meeting_nums: list[int] = field(default_factory=list)


# ── Pure helpers (no network) ────────────────────────────────────────────────
def _soup(content: bytes | str) -> BeautifulSoup:
    """Parse HTML bytes/str. Passing bytes lets bs4 sniff the page encoding
    (METI pages are often Shift_JIS; OCCTO/EGC are UTF-8)."""
    return BeautifulSoup(content, "lxml")


def extract_meeting_number(filename: str) -> int | None:
    """Meeting number from a PDF filename. METI ``001_x.pdf`` → 1; OCCTO
    ``prefix_71_01.pdf`` → 71. Returns None if no pattern matches."""
    meti = re.match(r"^(\d{3})_", filename)
    if meti:
        return int(meti.group(1))
    occto = re.search(r"_([0-9]{1,3})_(?:gijiroku|\d{2}|besshi|betten|sannkou)", filename, re.IGNORECASE)
    if occto:
        return int(occto.group(1))
    return None


def meeting_num_from_url(url: str) -> int | None:
    """Meeting number from a meeting-page URL like ``.../001.html`` or ``.../71.html``."""
    m = re.search(r"/(\d+)\.html(?:[?#].*)?$", url)
    return int(m.group(1)) if m else None


# ── Meeting-date parsing (no network) ────────────────────────────────────────
# Japanese era → the number you add to the era-year to get the Gregorian year:
#   令和 (Reiwa) 1 = 2019, 平成 (Heisei) 1 = 1989, 昭和 (Showa) 1 = 1926.
_ERA_OFFSET = {"令和": 2018, "平成": 1988, "昭和": 1925}
_ERA_DATE_RE = re.compile(r"(令和|平成|昭和)\s*(元|\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_GREG_DATE_RE = re.compile(r"(20\d{2})\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})")


def parse_jp_date(text: str | None) -> datetime.date | None:
    """First Japanese meeting date in *text*, or None.

    Handles both era dates (``令和6年8月27日``, ``令和元年…``) and Gregorian dates
    (``2026年5月8日`` / ``2026/5/8`` / ``2026-05-08``). Era form is tried first so a
    stray ``2019`` inside an era string can't shadow it. Out-of-range values (e.g.
    ``13月``) return None rather than raising.
    """
    if not text:
        return None
    m = _ERA_DATE_RE.search(text)
    if m:
        era, yr, mo, day = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        era_year = 1 if yr == "元" else int(yr)
        if era_year < 1:  # era years start at 1 (元年); 令和0年 is invalid
            return None
        try:
            return datetime.date(_ERA_OFFSET[era] + era_year, mo, day)
        except ValueError:
            return None
    m = _GREG_DATE_RE.search(text)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def parse_meti_meeting_dates(content: bytes | str, index_url: str) -> dict[int, datetime.date]:
    """Map ``meeting_num → date`` from a METI index page.

    Each meeting is a list row carrying both its date and its ``NNN.html`` link
    (e.g. ``2026年5月8日 第114回`` → ``114.html``). The date is read from the row
    (``<li>``/``<tr>``/…) enclosing the meeting link. First date per meeting wins.
    """
    soup = _soup(content)
    out: dict[int, datetime.date] = {}
    for a in soup.find_all("a", href=True):
        full = a["href"] if a["href"].startswith("http") else urljoin(index_url, a["href"])
        num = meeting_num_from_url(full)
        if num is None or num in out:
            continue
        row = a.find_parent(["li", "tr", "dd", "dt", "p"]) or a
        d = parse_jp_date(row.get_text(" ", strip=True))
        if d is not None:
            out[num] = d
    return out


def parse_egc_meeting_dates(content: bytes | str) -> dict[int, datetime.date]:
    """Map ``meeting_num → date`` from an EGC index/log table.

    Rows look like ``令和6年8月27日 第100回 議事概要 議事録 …``. First date per
    meeting wins (index before older log pages when merged by the caller).
    """
    soup = _soup(content)
    out: dict[int, datetime.date] = {}
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        nm = re.search(r"第(\d+)回", text)
        if not nm:
            continue
        num = int(nm.group(1))
        if num in out:
            continue
        d = parse_jp_date(text)
        if d is not None:
            out[num] = d
    return out


def parse_page_date(content: bytes | str) -> datetime.date | None:
    """The meeting date from a single meeting subpage (used for OCCTO).

    Prefers a date next to an explicit ``開催日`` / ``日時`` label; otherwise falls
    back to the first date anywhere on the page.
    """
    soup = _soup(content)
    txt = soup.get_text(" ", strip=True)
    for label in ("開催日時", "開催日", "日時"):
        idx = txt.find(label)
        if idx != -1:
            d = parse_jp_date(txt[idx : idx + 60])
            if d is not None:
                return d
    return parse_jp_date(txt)


def extract_pdf_id(filename: str) -> str:
    """Stable dedup id from a filename (ported from the reference scraper).

    METI ``001_a_b_...`` → ``001_a_b``; OCCTO ``prefix_71_01x.pdf`` → ``071_01x``;
    otherwise the filename stem. Used by ``material_id`` and unit tests.
    """
    meti = re.match(r"^(\d{3}_[^_]+_[^_]+)", filename)
    if meti:
        return meti.group(1)
    occto = re.search(r"_(\d{1,3})_(\d{2}[^.]*?)\.pdf$", filename, re.IGNORECASE)
    if occto:
        return f"{int(occto.group(1)):03d}_{occto.group(2)}"
    return Path(filename).stem


def material_id(meeting_num: int, url: str) -> str:
    """Deterministic, per-committee-unique id for a material.

    ``f"{meeting:03d}_{stem}"`` — the meeting prefix guarantees uniqueness across
    meetings, and the URL stem distinguishes documents within a meeting. Stable
    across runs (derived only from the source URL), so it is the dedup key.
    """
    stem = Path(urlparse(url).path).stem
    stem = re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿_-]", "", stem)[:80] or "doc"
    return f"{meeting_num:03d}_{stem}"


def classify_material(link_text: str, url: str) -> str:
    """Classify a document by its link text + filename into a ``kind``.

    Order matters: specific minute/summary/compilation types are checked before
    the generic 資料 (handout) catch-all.
    """
    text = link_text or ""
    fn = Path(urlparse(url).path).name.lower()
    blob = f"{text} {fn}"
    if "議事録" in text or "gijiroku" in fn:
        return "minutes"
    if "議事要旨" in text or "gijiyoshi" in fn or "gijiyoushi" in fn:
        return "brief"
    if "とりまとめ" in text or "torimatome" in fn:
        return "compilation"
    if "別紙" in text or "besshi" in fn:
        return "appendix"
    if "別添" in text or "betten" in fn:
        return "appendix"
    if "議事次第" in text or "shidai" in fn:
        return "agenda"
    if "参考" in text or "sankou" in fn or "sannkou" in fn:
        return "handout"  # 参考資料 reference material → treated as a handout
    if "資料" in blob or "haifu" in fn or "shiryo" in fn:
        return "handout"
    return "other"


def parse_pdf_links(content: bytes | str, base_url: str) -> list[dict]:
    """Every ``<a href=*.pdf>`` on a page → ``{'url', 'text'}`` (absolute URLs)."""
    soup = _soup(content)
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue
        full = href if href.startswith("http") else urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)
        out.append({"url": full, "text": a.get_text(strip=True)})
    return out


def parse_meti_meeting_urls(content: bytes | str, index_url: str) -> dict[int, str]:
    """Map ``meeting_num → absolute subpage URL`` from a METI index page.

    Matches ``NNN.html`` / ``N.html`` links (the numbered meeting subpages).
    """
    soup = _soup(content)
    out: dict[int, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"(^|/)\d{1,3}\.html(?:[?#].*)?$", href, re.IGNORECASE):
            continue
        full = href if href.startswith("http") else urljoin(index_url, href)
        num = meeting_num_from_url(full)
        if num is not None:
            out.setdefault(num, full)
    return out


def parse_egc_index(content: bytes | str, page_url: str, min_meeting: int | None = None) -> list[dict]:
    """Parse an EGC index/log table → list of ``{meeting_num, direct_pdfs, haifu_url}``.

    Each meeting row carries direct PDFs (議事要旨 / 議事録) plus a 配布資料 (haifu)
    subpage URL holding the handout PDFs. Rows without any PDF/haifu link (e.g.
    ``第1回～第5回`` navigation rows) are skipped.
    """
    soup = _soup(content)
    meetings: list[dict] = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            num_match = re.search(r"第(\d+)回", row.get_text())
            if not num_match:
                continue
            meeting_num = int(num_match.group(1))
            if min_meeting is not None and meeting_num < min_meeting:
                continue
            info: dict = {"meeting_num": meeting_num, "direct_pdfs": [], "haifu_url": None}
            for a in row.find_all("a", href=True):
                href = a["href"]
                full = urljoin(page_url, href)
                if href.lower().split("?")[0].endswith(".pdf"):
                    info["direct_pdfs"].append({"url": full, "text": a.get_text(strip=True)})
                elif "haifu" in href.lower() and href.lower().endswith(".html"):
                    info["haifu_url"] = full
            if info["direct_pdfs"] or info["haifu_url"]:
                meetings.append(info)
    return meetings


def _materials_from_links(meeting_num: int, links: list[dict]) -> list[Material]:
    """Turn raw ``{url, text}`` links into deduped ``Material`` records."""
    out: list[Material] = []
    seen: set[str] = set()
    for link in links:
        pid = material_id(meeting_num, link["url"])
        if pid in seen:
            continue
        seen.add(pid)
        out.append(
            Material(
                meeting_num=meeting_num,
                pdf_id=pid,
                url=link["url"],
                title=link.get("text", ""),
                kind=classify_material(link.get("text", ""), link["url"]),
            )
        )
    return out


# ── Networked fetch ──────────────────────────────────────────────────────────
def _fetch(url: str, *, db_path: str | None = None, force: bool = False) -> tuple[str, bytes | None]:
    """``conditional_get`` wrapper that downgrades exceptions to ``("error", None)``
    so one bad page doesn't abort a whole detection run."""
    try:
        return conditional_get(
            url,
            db_path=db_path,
            headers={"Accept-Language": "ja,en;q=0.9"},
            allow_curl_fallback=True,
            force=force,
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("policy fetch failed %s: %s", url, e)
        return ("error", None)


def _exists(url: str) -> bool:
    """Existence check for OCCTO meeting pages (no cache writes, so a later
    ``conditional_get`` of the same URL still gets a parseable 200).

    Prefer a cheap HEAD; if the host rejects plain Python TLS (some gov sites
    behind Akamai answer 403, as meti.go.jp does), fall back to a curl_cffi
    Chrome-impersonation GET — the same fallback the shared HTTP cache uses.
    """
    headers = {"User-Agent": _UA, "Accept-Language": "ja,en;q=0.9"}
    try:
        r = httpx.head(url, timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers)
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return False
    except Exception as e:  # noqa: BLE001
        logger.debug("HEAD probe error %s: %s", url, e)

    # HEAD inconclusive (403/405/redirect/error) — confirm via curl_cffi, then plain GET.
    try:
        from curl_cffi import requests as cr  # type: ignore

        r = cr.get(url, impersonate="chrome", timeout=REQUEST_TIMEOUT, headers=headers)
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        logger.debug("curl_cffi probe failed %s: %s", url, e)
    try:
        r = httpx.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers)
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        logger.debug("GET probe failed %s: %s", url, e)
        return False


def _occto_base(committee: Committee) -> str:
    return re.sub(r"index\.html$", "", committee.url).rstrip("/")


def probe_occto_latest(committee: Committee, *, start_from: int | None = None,
                       max_probes: int | None = None) -> int | None:
    """Find the latest OCCTO meeting by a linear upward-window probe.

    Replaces the reference's binary search, which mis-fires when meeting pages are
    non-contiguous (a missing middle page makes binary search conclude too low).
    Scans upward from ``start_from + 1`` (the last known meeting) and stops after
    ``PROBE_GAP_TOLERANCE`` consecutive misses — tolerating small gaps while
    staying cheap on re-runs (only a few probes past the known frontier).

    ``max_probes`` optionally bounds the number of page probes (each costs a
    request + a polite ~1s sleep) — used by interactive previews; detection
    passes None and keeps the full scan.
    """
    base = _occto_base(committee)
    cap = (committee.max_meeting or 200) + PROBE_GAP_TOLERANCE
    cap = min(cap, PROBE_HARD_CAP)
    latest = start_from
    misses = 0
    probes = 0
    n = max(1, (start_from or 0) + 1)
    while n <= cap and misses < PROBE_GAP_TOLERANCE:
        if max_probes is not None and probes >= max_probes:
            break
        if _exists(f"{base}/{n}.html"):
            latest = n
            misses = 0
        else:
            misses += 1
        n += 1
        probes += 1
        time.sleep(POLITE_DELAY)
    return latest


# ── Discovery (which meetings exist) ─────────────────────────────────────────
def discover_meetings(committee: Committee, *, db_path: str | None = None,
                      known_latest: int | None = None, force: bool = False,
                      max_probes: int | None = None) -> Discovery:
    """Return the meeting numbers currently available online for *committee*.

    METI/EGC read a single (cached) index; OCCTO probes by number from
    ``known_latest``. A 304 on the METI/EGC index short-circuits to ``unchanged``
    — pass ``force=True`` when a body is always needed (e.g. probe previews of a
    URL that is already in the cache). ``max_probes`` bounds the OCCTO scan for
    interactive callers; detection passes neither and keeps the cheap behaviour.
    """
    if committee.is_occto:
        latest = probe_occto_latest(committee, start_from=known_latest,
                                    max_probes=max_probes)
        if latest is None:
            return Discovery("error", [])
        return Discovery("ok", list(range(latest, 0, -1)))

    status, content = _fetch(committee.url, db_path=db_path, force=force)
    if status == "not_modified":
        return Discovery("unchanged", [])

    if status == "ok" and content is not None:
        if committee.is_egc:
            meetings = parse_egc_index(content, committee.url)
            nums = sorted({m["meeting_num"] for m in meetings}, reverse=True)
            return Discovery("ok", nums)
        # METI
        url_map = parse_meti_meeting_urls(content, committee.url)
        if url_map:
            return Discovery("ok", sorted(url_map, reverse=True))
        logger.info("policy: no numbered meeting subpages for %s", committee.key)

    # Primary METI fetch failed (or the index had no meetings) — fall back to the
    # energy-board aggregator so a blocked/500 METI index still surfaces the recent
    # meetings. OCCTO/EGC aren't on that (METI-only) aggregator.
    if committee.is_meti:
        nums = _energy_board_nums(committee, db_path=db_path)
        if nums:
            logger.info("policy: %s METI index unavailable — energy-board backup (%d meetings)",
                        committee.key, len(nums))
            return Discovery("ok", sorted(nums, reverse=True))

    return Discovery("ok", []) if status == "ok" else Discovery("error", [])


def _energy_board_nums(committee: Committee, *, db_path: str | None = None) -> list[int]:
    """Recent meeting numbers from the energy-board backup (lazy import to avoid a
    scraper<->energy_board cycle). Never raises — an unavailable backup is []."""
    try:
        from repower.policy import energy_board

        return energy_board.recent_meeting_nums(committee, db_path=db_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("energy-board backup failed for %s: %s", committee.key, e)
        return []


def _energy_board_dates(committee: Committee, *, db_path: str | None = None) -> dict[int, datetime.date]:
    """Meeting dates from the energy-board backup (lazy import). Never raises."""
    try:
        from repower.policy import energy_board

        return energy_board.meeting_dates_for(committee, db_path=db_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("energy-board date backup failed for %s: %s", committee.key, e)
        return {}


def _energy_board_materials(committee: Committee, meeting_num: int, *, db_path: str | None = None) -> list[Material]:
    """Materials for one meeting from the energy-board backup (lazy import)."""
    try:
        from repower.policy import energy_board

        return energy_board.materials_for(committee, meeting_num, db_path=db_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("energy-board material backup failed for %s 第%d回: %s",
                       committee.key, meeting_num, e)
        return []


# ── Material enumeration (what a meeting contains) ───────────────────────────
def list_materials(committee: Committee, meeting_num: int, *, db_path: str | None = None) -> list[Material]:
    """Enumerate the source documents for one meeting. One fetch of the meeting's
    page (METI/OCCTO) or the index row + 配布資料 subpage (EGC)."""
    if committee.is_occto:
        return _list_occto(committee, meeting_num, db_path=db_path)
    if committee.is_egc:
        return _list_egc(committee, meeting_num, db_path=db_path)
    return _list_meti(committee, meeting_num, db_path=db_path)


def _list_meti(committee: Committee, meeting_num: int, *, db_path: str | None) -> list[Material]:
    # force=True: detection may have already cached (and 304'd) the index this run;
    # we need a real body to parse, so bypass the conditional cache here.
    status, content = _fetch(committee.url, db_path=db_path, force=True)
    if status == "ok" and content is not None:
        url_map = parse_meti_meeting_urls(content, committee.url)
        page_url = url_map.get(meeting_num)
        if page_url:
            time.sleep(POLITE_DELAY)
            s, body = _fetch(page_url, db_path=db_path, force=True)
            if s == "ok" and body is not None:
                mats = _materials_from_links(meeting_num, parse_pdf_links(body, page_url))
                if mats:
                    return mats
    # METI meeting page unavailable/empty — energy-board backup (same meti.go.jp PDFs).
    return _energy_board_materials(committee, meeting_num, db_path=db_path)


def _list_occto(committee: Committee, meeting_num: int, *, db_path: str | None) -> list[Material]:
    base = _occto_base(committee)
    page_url = f"{base}/{meeting_num}.html"
    s, body = _fetch(page_url, db_path=db_path, force=True)
    if s != "ok" or body is None:
        return []
    return _materials_from_links(meeting_num, parse_pdf_links(body, page_url))


# ── Meeting-date discovery (networked) ───────────────────────────────────────
def fetch_committee_dates(committee: Committee, *, db_path: str | None = None) -> dict[int, datetime.date]:
    """Map ``meeting_num → date`` for a committee from its index page(s).

    METI reads one index; EGC merges the main index + historical log pages
    (index first, so it wins on overlap). OCCTO indexes are JS-rendered and carry
    no dates, so this returns ``{}`` for OCCTO — use :func:`fetch_occto_meeting_date`
    per subpage instead.
    """
    if committee.is_occto:
        return {}
    if committee.is_egc:
        out: dict[int, datetime.date] = {}
        pages = [committee.url] + [urljoin(EGC_ACTIVITY_BASE, p) for p in committee.log_pages]
        for page in pages:
            status, content = _fetch(page, db_path=db_path, force=True)
            if status == "ok" and content is not None:
                for num, d in parse_egc_meeting_dates(content).items():
                    out.setdefault(num, d)
            time.sleep(POLITE_DELAY)
        return out
    # METI
    status, content = _fetch(committee.url, db_path=db_path, force=True)
    if status == "ok" and content is not None:
        return parse_meti_meeting_dates(content, committee.url)
    # Index blocked/unavailable — energy-board backup (recent meetings only),
    # symmetric with the discovery/materials fallbacks above.
    return _energy_board_dates(committee, db_path=db_path)


def fetch_occto_meeting_date(
    committee: Committee, meeting_num: int, *, db_path: str | None = None
) -> datetime.date | None:
    """The meeting date for one OCCTO meeting, read from its ``{base}/{num}.html`` subpage."""
    base = _occto_base(committee)
    status, body = _fetch(f"{base}/{meeting_num}.html", db_path=db_path, force=True)
    if status != "ok" or body is None:
        return None
    return parse_page_date(body)


def _list_egc(committee: Committee, meeting_num: int, *, db_path: str | None) -> list[Material]:
    # Look on the main index first, then historical log pages if not found.
    pages = [committee.url] + [urljoin(EGC_ACTIVITY_BASE, p) for p in committee.log_pages]
    row: dict | None = None
    for page in pages:
        s, body = _fetch(page, db_path=db_path, force=True)  # need a body to parse, not a 304
        if s != "ok" or body is None:
            continue
        for m in parse_egc_index(body, page):
            if m["meeting_num"] == meeting_num:
                row = m
                break
        if row is not None:
            break
        time.sleep(POLITE_DELAY)
    if row is None:
        return []

    links = list(row["direct_pdfs"])
    if row.get("haifu_url"):
        time.sleep(POLITE_DELAY)
        s, body = _fetch(row["haifu_url"], db_path=db_path, force=True)
        if s == "ok" and body is not None:
            links.extend(parse_pdf_links(body, row["haifu_url"]))
    return _materials_from_links(meeting_num, links)
