"""Discover *new* energy-policy committees from the web, to add to tracking.

Two entry points, both best-effort and network-injectable (so they're unit-tested
against saved HTML without hitting the network):

- :func:`search_committees` crawls a curated set of METI / OCCTO / EGC index
  roots, extracts links that look like committee homepages, filters them by a
  free-text query (Japanese names + URL slugs, with a small English→Japanese
  keyword bridge), and flags the ones already tracked. (Distinct from
  :func:`repower.policy.catalog.discover_committees`, which enumerates the org
  indexes and persists catalog rows.)
- :func:`probe_url` takes a committee URL the user pasted, guesses its source /
  key / name, and (optionally) validates it by running the real detector so the
  UI can preview "N meetings found" before the committee is added.

Discovery is inherently fuzzy — the reliable path is always "paste the committee
URL" — so every candidate is editable in the UI before it's saved.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from repower.policy.committees import Committee
from repower.policy.scraper import _fetch, discover_meetings
from repower.policy.store import _norm_url

logger = logging.getLogger(__name__)

FetchFn = Callable[[str], tuple[str, "bytes | None"]]

# Curated index roots where Japanese energy committees are published. These are
# the parent directories of the committees we already track, so newly-created
# committees almost always appear under one of them.
INDEX_ROOTS: tuple[str, ...] = (
    "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/",
    "https://www.meti.go.jp/shingikai/enecho/",
    "https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/",
    "https://www.meti.go.jp/shingikai/energy_environment/",
    "https://www.occto.or.jp/iinkai/",
    "https://www.egc.meti.go.jp/activity/",
)

# Cap on OCCTO by-number page probes when previewing a pasted URL (each probe
# sleeps ~1s, so an unbounded scan stalls the UI). Detection stays unbounded.
PROBE_PREVIEW_MAX = 15

# A link is treated as a committee homepage if its text contains one of these.
_COMMITTEE_MARKERS = ("委員会", "小委員会", "部会", "分科会", "検討会", "研究会",
                      "ワーキンググループ", "ワーキング", "会合", "作業部会")

# Navigation / chrome links to ignore even if they contain a marker substring.
_NAV_BLOCKLIST = ("一覧", "トップ", "サイトマップ", "english", "お問い合わせ",
                  "ホーム", "戻る", "次へ", "前へ", "pdf", "議事")

# Small English→Japanese bridge so an English query still matches Japanese names.
_EN_JA_HINTS: dict[str, tuple[str, ...]] = {
    "emissions": ("排出",), "trading": ("取引",), "carbon": ("炭素", "カーボン"),
    "capacity": ("容量",), "balancing": ("調整", "需給"), "market": ("市場",),
    "renewable": ("再生", "再エネ"), "wind": ("風力",), "offshore": ("洋上",),
    "solar": ("太陽光",), "grid": ("系統", "ネットワーク"), "transmission": ("送電",),
    "hydrogen": ("水素",), "nuclear": ("原子力",), "storage": ("蓄電",),
    "price": ("価格",), "fit": ("調達価格",), "gas": ("ガス",), "power": ("電力",),
    "electricity": ("電力",), "energy": ("エネルギー",), "system": ("制度", "システム"),
}


@dataclass
class Candidate:
    """A committee we might start tracking."""

    key: str
    name_ja: str
    name_en: str
    url: str
    source: str  # METI | OCCTO | EGC
    already_tracked: bool = False
    note: str = ""  # e.g. "24 meetings found" from a probe


# ── URL / source / key heuristics ────────────────────────────────────────────
def normalize_url(url: str) -> str:
    """Canonical form for dedup: drop fragment/query + trailing index.html + slash,
    lowercased. Delegates to :func:`repower.policy.store._norm_url` so discovery
    and the store agree on what counts as "the same committee URL"."""
    return _norm_url(url)


def guess_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "occto.or.jp" in host:
        return "OCCTO"
    if "egc.meti.go.jp" in host:
        return "EGC"
    return "METI"


def guess_key(url: str) -> str:
    """A stable committee key from the URL's last meaningful path segment.

    EGC pages are all flat files under ``/activity/`` (``index_<slug>.html``), so
    stripping the filename would collapse every EGC committee to key "activity" —
    those map to ``emsc_<slug>`` instead, aligned with
    :func:`repower.policy.catalog.parse_egc_committees`.
    """
    path = urlparse(url).path
    egc = re.match(r"^/activity/index_([a-z0-9_]+)\.html$", path, flags=re.IGNORECASE)
    if egc and "egc.meti.go.jp" in urlparse(url).netloc.lower():
        return f"emsc_{egc.group(1).lower()}"
    path = re.sub(r"/index\.html?$", "/", path, flags=re.IGNORECASE)
    segs = [s for s in path.split("/") if s and not s.endswith((".html", ".htm"))]
    seg = segs[-1] if segs else "committee"
    key = re.sub(r"[^0-9a-zA-Z_]", "_", seg).strip("_").lower()
    return key or "committee"


def _clean_name(text: str) -> str:
    """Trim a page title / link text down to the committee name."""
    text = re.sub(r"\s+", " ", text or "").strip()
    # Drop trailing site suffixes: "…｜経済産業省", "…（METI/経済産業省）", "- METI".
    text = re.split(r"[｜|]|（METI|\(METI|- ?METI|｜経済産業省", text)[0].strip()
    return text.strip(" 　-—:：")


# ── Parse committee links from an index page (no network) ─────────────────────
def parse_committee_links(content: bytes | str, index_url: str) -> list[Candidate]:
    """Extract committee-homepage candidates from an index page's ``<a>`` links."""
    soup = BeautifulSoup(content, "lxml")
    host = urlparse(index_url).netloc
    seen: set[str] = set()
    out: list[Candidate] = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if not text or len(text) < 4:
            continue
        low = text.lower()
        if any(b in low for b in _NAV_BLOCKLIST):
            continue
        if not any(mark in text for mark in _COMMITTEE_MARKERS):
            continue
        full = urljoin(index_url, a["href"])
        if urlparse(full).netloc != host:  # stay on-site; skip cross-links
            continue
        if full.lower().split("?")[0].endswith(".pdf"):
            continue
        norm = normalize_url(full)
        if norm in seen or norm == normalize_url(index_url):
            continue
        seen.add(norm)
        src = guess_source(full)
        out.append(Candidate(
            key=guess_key(full), name_ja=_clean_name(text), name_en="",
            url=full, source=src,
        ))
    return out


# ── Query matching ────────────────────────────────────────────────────────────
def _matches(cand: Candidate, tokens: list[str]) -> bool:
    """All query tokens must hit the name (JA) or URL/key (with EN→JA bridge)."""
    if not tokens:
        return True
    hay_name = cand.name_ja
    hay_slug = f"{cand.url} {cand.key} {cand.name_en}".lower()
    for tok in tokens:
        t = tok.lower()
        hit = t in hay_slug or tok in hay_name
        if not hit:
            for ja in _EN_JA_HINTS.get(t, ()):  # English token → Japanese name match
                if ja in hay_name:
                    hit = True
                    break
        if not hit:
            return False
    return True


# ── Public: search the curated index roots ────────────────────────────────────
def search_committees(
    query: str = "", *, db_path: str | None = None, roots: tuple[str, ...] | None = None,
    fetch: FetchFn | None = None, tracked_urls: set[str] | None = None,
    tracked_keys: set[str] | None = None, limit: int = 40,
) -> list[Candidate]:
    """Crawl the index roots and return committee candidates matching *query*.

    ``fetch`` defaults to a **forced** fetch (inject a fake in tests): the index
    roots overlap the catalog/detect crawls, so a conditional GET of an
    already-cached root would 304 with no body and the search would silently
    return zero candidates. ``tracked_urls``/``tracked_keys`` mark
    already-tracked committees; if omitted they're read from the registry.
    """
    # force=True: we always need a body to parse, never a 304 (see docstring).
    fetch = fetch or (lambda u: _fetch(u, db_path=db_path, force=True))
    roots = roots or INDEX_ROOTS
    if tracked_urls is None or tracked_keys is None:
        from repower.policy.store import list_committees
        rows = list_committees(db_path=db_path)
        tracked_urls = {normalize_url(r["url"]) for r in rows if r["url"]}
        tracked_keys = {r["committee_key"] for r in rows}

    tokens = query.split()
    by_url: dict[str, Candidate] = {}
    for root in roots:
        try:
            status, content = fetch(root)
        except Exception as e:  # noqa: BLE001 — one bad root must not abort discovery
            logger.warning("discover: fetch failed for %s: %s", root, e)
            continue
        if status != "ok" or not content:
            continue
        for cand in parse_committee_links(content, root):
            if not _matches(cand, tokens):
                continue
            norm = normalize_url(cand.url)
            cand.already_tracked = norm in tracked_urls or cand.key in tracked_keys
            by_url.setdefault(norm, cand)  # first root wins on dupes

    # Untracked first, then by name, capped.
    cands = sorted(by_url.values(), key=lambda c: (c.already_tracked, c.name_ja))
    return cands[:limit]


# ── Public: probe a pasted URL ────────────────────────────────────────────────
def probe_url(
    url: str, *, db_path: str | None = None, fetch: FetchFn | None = None,
    validate: bool = True, tracked_urls: set[str] | None = None,
    tracked_keys: set[str] | None = None,
) -> Candidate | None:
    """Inspect a pasted committee URL → a :class:`Candidate`.

    Returns ``None`` only for non-http(s) input; an unreachable URL still yields
    a Candidate, with ``note="unreachable"``. Guesses source/key from the URL,
    reads the page ``<title>``/``<h1>`` for a name, and — when ``validate`` —
    runs the real detector so the UI can preview how many meetings would be
    tracked.
    """
    url = url.strip()
    if not re.match(r"^https?://", url):
        return None
    # force=True: the URL may already be in the conditional-GET cache (e.g. an
    # index the catalog crawl touched), and a 304 carries no body to parse.
    fetch = fetch or (lambda u: _fetch(u, db_path=db_path, force=True))
    source = guess_source(url)
    key = guess_key(url)

    name_ja = ""
    unreachable = False
    try:
        status, content = fetch(url)
        if status == "ok" and content:
            soup = BeautifulSoup(content, "lxml")
            h1 = soup.find("h1")
            title = soup.find("title")
            raw = (h1.get_text(strip=True) if h1 else "") or (
                title.get_text(strip=True) if title else "")
            name_ja = _clean_name(raw)
        else:
            unreachable = True
    except Exception as e:  # noqa: BLE001
        logger.warning("probe_url fetch failed for %s: %s", url, e)
        unreachable = True

    if tracked_urls is None or tracked_keys is None:
        from repower.policy.store import list_committees
        rows = list_committees(db_path=db_path)
        tracked_urls = {normalize_url(r["url"]) for r in rows if r["url"]}
        tracked_keys = {r["committee_key"] for r in rows}

    cand = Candidate(
        key=key, name_ja=name_ja or key, name_en="", url=url, source=source,
        already_tracked=normalize_url(url) in tracked_urls or key in tracked_keys,
        note="unreachable" if unreachable else "",
    )

    if validate:
        try:
            probe = Committee(key=key, name_ja=cand.name_ja, name_en=key,
                              url=url, source=source)
            # force=True: this re-fetches the URL we just fetched, so a
            # conditional GET would 304 and the meeting preview would break.
            # max_probes bounds the OCCTO by-number scan (1s sleep per probe) so
            # a UI preview stays snappy; detect keeps the unbounded scan.
            disc = discover_meetings(probe, db_path=db_path, force=True,
                                     max_probes=PROBE_PREVIEW_MAX)
            if disc.status == "ok":
                n = len(disc.meeting_nums)
                cand.note = f"{n} meeting(s) found" if n else "reachable (0 numbered meetings parsed)"
            elif not unreachable:
                cand.note = "could not parse meetings — check the URL"
        except Exception as e:  # noqa: BLE001
            logger.warning("probe_url validate failed for %s: %s", url, e)
            if not unreachable:
                cand.note = "could not validate"
    return cand
