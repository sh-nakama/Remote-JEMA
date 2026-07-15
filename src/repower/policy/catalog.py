"""Enumerate energy-policy committees from each organisation's index page.

Distinct from :mod:`repower.policy.scraper` (which enumerates *meetings within* a
known committee): this module enumerates the *committees themselves* from the METI
資源エネルギー庁 committee index, the OCCTO 委員会・検討会 index, and the EGC 活動 index —
so the observer can surface energy-related committees we do not yet track and let
the user start tracking them.

Two responsibilities, kept separate (same split as the scraper):
- **Pure parse functions** (``parse_*``) take page bytes/strings + a base URL and
  return ``{key, name_ja, source, url, …}`` dicts. No network — unit-tested against
  saved HTML fixtures.
- **Networked discovery** (``fetch_catalog`` / ``discover_committees``) composes the
  parsers with the shared HTTP cache and persists newly-found committees as
  untracked catalog rows via :func:`repower.policy.store.upsert_discovered_committees`.

Committee URLs are what make a discovered committee scrapeable: OCCTO/EGC/METI
committees found here carry the same URL/source shape as the hand-written config in
:mod:`repower.policy.committees`, so ``detect`` can process them once tracked. (OCCTO
needs a ``prefix`` — set to the URL slug here; EGC ``log_pages`` are left empty, so a
newly-tracked EGC committee reads only its main index until configured.)
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from repower.policy.schedule import is_energy_relevant
from repower.scrapers.http_cache import conditional_get

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 40.0

METI_INDEX_URL = "https://www.meti.go.jp/shingikai/enecho/index.html"
OCCTO_INDEX_URL = "https://www.occto.or.jp/iinkai/"
EGC_INDEX_URL = "https://www.egc.meti.go.jp/activity/"


# ── Pure parse functions (no network) ────────────────────────────────────────
def _soup(content: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(content, "lxml")


def parse_occto_committees(content: bytes | str, base_url: str = OCCTO_INDEX_URL) -> list[dict]:
    """OCCTO 委員会一覧 → committee dicts.

    Committee links are ``/iinkai/<slug>/index.html`` on ``occto.or.jp``; the slug
    doubles as the material-id prefix. OCCTO is wholly grid/energy, so no keyword
    filter is applied. External links (e.g. the METI 同時市場 study group) are skipped.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for a in _soup(content).find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        p = urlparse(full)
        if "occto.or.jp" not in p.netloc:
            continue
        m = re.match(r"^/iinkai/([a-z0-9_]+)/index\.html$", p.path)
        if not m:
            continue
        slug = m.group(1)
        name = a.get_text(" ", strip=True)
        if not name or p.path in seen:
            continue
        seen.add(p.path)
        out.append({"key": slug, "name_ja": name, "source": "OCCTO", "url": full, "prefix": slug})
    return out


def parse_egc_committees(content: bytes | str, base_url: str = EGC_INDEX_URL) -> list[dict]:
    """EGC 活動 index → committee dicts.

    Committee links are ``/activity/index_<slug>.html`` on ``egc.meti.go.jp``. Keyed
    ``emsc_<slug>`` to line up with the config keys (``emsc_system`` etc.). EGC is
    wholly energy-market, so no keyword filter is applied.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for a in _soup(content).find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        p = urlparse(full)
        if "egc.meti.go.jp" not in p.netloc:
            continue
        m = re.match(r"^/activity/index_([a-z0-9]+)\.html$", p.path)
        if not m:
            continue
        slug = m.group(1)
        name = a.get_text(" ", strip=True)
        if not name or p.path in seen:
            continue
        seen.add(p.path)
        out.append({"key": f"emsc_{slug}", "name_ja": name, "source": "EGC", "url": full})
    return out


def parse_meti_enecho_committees(content: bytes | str, base_url: str = METI_INDEX_URL) -> list[dict]:
    """METI 資源エネルギー庁 committee index → committee dicts.

    Accepts the classic ``meti.go.jp/shingikai/.../<slug>/index.html`` committee
    pages (the shape ``scraper``'s METI path can enumerate); the newer
    ``enecho.meti.go.jp/committee/...`` anchor links use a different structure and
    are skipped. The index spans all of 資源エネルギー庁, so names are filtered by the
    energy-relevance keyword set (drops e.g. 鉱業小委員会). The URL is normalised to the
    config's trailing-slash form.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for a in _soup(content).find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        p = urlparse(full)
        if p.netloc and p.netloc != "www.meti.go.jp":
            continue
        m = re.match(r"^/shingikai/.+/([a-z0-9_]+)/index\.html$", p.path)
        if not m:
            continue
        slug = m.group(1)
        name = a.get_text(" ", strip=True)
        if not name or p.path in seen or not is_energy_relevant(name):
            continue
        seen.add(p.path)
        out.append({"key": slug, "name_ja": name, "source": "METI",
                    "url": re.sub(r"index\.html$", "", full)})
    return out


# ── Networked discovery ──────────────────────────────────────────────────────
_INDEXES = [
    (METI_INDEX_URL, parse_meti_enecho_committees),
    (OCCTO_INDEX_URL, parse_occto_committees),
    (EGC_INDEX_URL, parse_egc_committees),
]


def _fetch(url: str, *, db_path: str | None = None) -> bytes | None:
    try:
        status, content = conditional_get(
            url, db_path=db_path, headers={"Accept-Language": "ja,en;q=0.9"},
            allow_curl_fallback=True, force=True, timeout=REQUEST_TIMEOUT,
        )
        return content if status == "ok" else None
    except Exception as e:  # noqa: BLE001 — one bad index must not abort discovery
        logger.warning("catalog fetch failed %s: %s", url, e)
        return None


def fetch_catalog(*, db_path: str | None = None) -> list[dict]:
    """Fetch + parse all three org indexes into committee dicts (no DB writes)."""
    items: list[dict] = []
    for url, parser in _INDEXES:
        content = _fetch(url, db_path=db_path)
        if content is not None:
            items.extend(parser(content, url))
    return items


# ── Manual add-by-URL ────────────────────────────────────────────────────────
# Any /shingikai/<dir>/ page is scrapeable by the generic METI enumerator
# (numbered NNN.html subpages), so a manual add needs no per-committee config —
# the same claim the energy-board cross-check relies on. This is the escape
# hatch for committees the three org indexes never list (e.g. WGs nested under
# a 小委員会, which the top-level METI index stops short of).
_METI_SHINGIKAI_RE = re.compile(
    r"^https?://www\.meti\.go\.jp/shingikai/([a-z0-9_]+(?:/[a-z0-9_]+)*)/?(?:index\.html)?$"
)


def parse_meti_committee_url(url: str) -> dict | None:
    """Validate + normalise a METI committee URL for a manual add.

    Returns ``{key, url, dir}`` (key = last path segment, url in the config's
    trailing-slash form) or ``None`` if the URL is not a meti.go.jp/shingikai
    committee page.
    """
    m = _METI_SHINGIKAI_RE.match((url or "").split("#")[0].split("?")[0].strip())
    if not m:
        return None
    d = m.group(1).rstrip("/")
    return {"key": d.split("/")[-1], "url": f"https://www.meti.go.jp/shingikai/{d}/", "dir": d}


def parse_meti_page_title(content: bytes | str) -> str | None:
    """The committee name from a METI committee page: the ``<h1>`` if present,
    else the ``<title>`` with the boilerplate "（METI/経済産業省）" suffix stripped."""
    soup = _soup(content)
    h1 = soup.find("h1")
    if h1 is not None:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title is not None:
        t = re.sub(r"[（(]\s*METI[^）)]*[）)]\s*$", "", soup.title.get_text(" ", strip=True)).strip()
        return t or None
    return None


def add_committee_by_url(url: str, *, db_path: str | None = None, track: bool = True) -> dict:
    """Add one committee to the catalog from its METI page URL (user-initiated).

    Validates the URL shape, fetches the page for its Japanese name (falling
    back to the URL slug if METI is unreachable — e.g. WAF-challenged), and
    inserts it ``user_added=1`` and tracked by default. If the URL is already
    in the catalog, returns the existing key untouched.

    Returns ``{"ok", "key", "name_ja", "existing"}``; raises ``ValueError``
    on a URL that is not a METI /shingikai/ committee page.
    """
    from repower.policy.store import add_user_committee

    parsed = parse_meti_committee_url(url)
    if parsed is None:
        raise ValueError("not a meti.go.jp/shingikai committee URL")
    name_ja = ""
    content = _fetch(parsed["url"], db_path=db_path)
    if content is not None:
        name_ja = parse_meti_page_title(content) or ""
    res = add_user_committee(
        {"key": parsed["key"], "name_ja": name_ja, "source": "METI", "url": parsed["url"]},
        enabled=track, db_path=db_path,
    )
    if res["existing"]:
        from repower.policy.store import get_committee

        row = get_committee(res["key"], db_path=db_path)
        name_ja = (row.name_ja if row else "") or name_ja
    logger.info("policy catalog: add-by-url %s -> %s (existing=%s)",
                parsed["url"], res["key"], res["existing"])
    return {"ok": True, "key": res["key"], "name_ja": name_ja, "existing": res["existing"]}


def discover_committees(*, db_path: str | None = None) -> dict:
    """Refresh the committee catalog: enumerate energy committees from the three
    org indexes and persist any not already known as untracked rows.

    Returns ``{"found", "inserted", "by_source"}``.
    """
    from repower.policy.store import sync_committees, upsert_discovered_committees

    sync_committees(db_path)  # ensure config committees exist so dedup is correct
    items = fetch_catalog(db_path=db_path)
    inserted = upsert_discovered_committees(items, db_path=db_path)
    by_source: dict[str, int] = {}
    for it in items:
        by_source[it["source"]] = by_source.get(it["source"], 0) + 1
    logger.info("policy catalog: %d committees listed, %d newly discovered", len(items), inserted)
    return {"found": len(items), "inserted": inserted, "by_source": by_source}
