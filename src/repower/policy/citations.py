"""Turn a NotebookLM citation into "this document, this page".

A digest's ``references[]`` say *which source* (``source_id``) and *what text*
(``cited_text``) a bullet rests on, but never which page — NotebookLM indexes
extracted text, not pages. The page is recovered here by finding the cited
passage in the source PDF's own text, page by page. That is also what makes the
resolver independent of NotebookLM: it needs only the digest and the PDFs, so it
works for digests whose notebook (and ``source_id`` mapping) is long gone.

How a passage is located: both texts are normalised (NFKC, whitespace removed —
PDF extraction and NotebookLM disagree about line breaks, never about glyphs), then
short overlapping *shingles* of the passage's head are looked up in every page. A
shingle that appears on one page is strong evidence; one that appears on every page
(a slide footer) is nearly none, so each hit is weighted by ``1 / pages containing
it``. The passage's *tail* is located the same way, which is what turns a chunk that
straddles a page break into a range (``pp.6–7``) instead of a wrong single page.
Measured on a real 43-page METI deck: 20 of 20 citations resolved, the winning page
always carrying over half of the head's shingles.

A passage that cannot be located confidently yields **no page** — never a guess. The
deep-link then opens the document at page 1, which is honest; a wrong page is not.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Schema version of ``policy_meeting.citations_json``.
SCHEMA = 1

_SHINGLE = 10          # characters per probe
_STEP = 4              # probe stride — overlapping, so one OCR/extraction glitch costs one probe
_EDGE = 160            # characters of the passage's head / tail that get probed
_MIN_CONFIDENCE = 0.35  # share of probes the winning page must contain, else: no page
_MIN_PROBE_TEXT = 2 * _SHINGLE  # shorter passages are matched whole, and only if unambiguous
_MIN_EXACT = 8         # below this a fragment ("4", a bullet) identifies nothing, so it gets no link


class CitationsUnavailable(RuntimeError):
    """PyMuPDF is not installed, so page text cannot be read."""


def normalize(text: str | None) -> str:
    """Comparison form of *text*: NFKC with every run of whitespace removed."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def pdf_page_texts(path: Path | str) -> list[str]:
    """Normalised text of each page of the PDF at *path* (index 0 = page 1).

    A scanned PDF yields empty strings, which simply never match — the citation then
    resolves without a page.
    """
    try:
        import pymupdf  # AGPL: used only by the pipeline / local API, never shipped to the Space or Pages
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise CitationsUnavailable(
            "PyMuPDF is not installed — `pip install pymupdf` (the `policy` extra) to resolve citation pages"
        ) from e
    with pymupdf.open(str(path)) as doc:
        return [normalize(page.get_text()) for page in doc]


@dataclass(frozen=True)
class Location:
    """Where a passage sits in a document (1-based page numbers, inclusive)."""

    page: int
    page_end: int
    confidence: float


def _probes(text: str) -> list[str]:
    return [text[i:i + _SHINGLE] for i in range(0, max(1, len(text) - _SHINGLE + 1), _STEP)]


def _vote(probes: Sequence[str], pages: Sequence[str]) -> tuple[int, float, float] | None:
    """Best page for *probes*: ``(index, confidence, weighted score)``, or None.

    Confidence is the plain share of probes the page contains; the weighted score
    (rare probes count more) only breaks the choice between pages. Ties go to the
    earlier page, so a passage repeated verbatim is attributed to where it first
    appears.
    """
    if not probes:
        return None
    hits: list[tuple[int, str]] = []
    df: Counter[str] = Counter()  # in how many pages each probe appears
    for i, page in enumerate(pages):
        for p in set(probes):
            if p in page:
                df[p] += 1
                hits.append((i, p))
    if not hits:
        return None
    score: dict[int, float] = {}
    for i, p in hits:
        score[i] = score.get(i, 0.0) + 1.0 / df[p]
    best = max(score, key=lambda i: (round(score[i], 6), -i))
    share = sum(1 for p in probes if p in pages[best]) / len(probes)
    return best, share, score[best]


def locate(cited_text: str | None, pages: Sequence[str]) -> Location | None:
    """Find *cited_text* in a document whose normalised page texts are *pages*."""
    text = normalize(cited_text)
    if not text or not any(pages):
        return None
    if len(text) < _MIN_EXACT:
        return None
    if len(text) < _MIN_PROBE_TEXT:
        # Too short to probe. Trust it only if exactly one page holds it.
        where = [i for i, page in enumerate(pages) if text in page]
        return Location(where[0] + 1, where[0] + 1, 1.0) if len(where) == 1 else None
    # Head and tail must stay distinct windows, or a short chunk's "end" would just repeat
    # its start: take at most a third of the text each way (and at most _EDGE characters).
    edge = min(_EDGE, max(_MIN_PROBE_TEXT, len(text) // 3))
    head = _vote(_probes(text[:edge]), pages)
    if head is None or head[1] < _MIN_CONFIDENCE:
        return None
    start = head[0]
    tail = _vote(_probes(text[-edge:]), pages)
    end = tail[0] if tail is not None and tail[1] >= _MIN_CONFIDENCE and tail[0] >= start else start
    return Location(start + 1, end + 1, head[1])


@dataclass
class Doc:
    """One source document a digest may cite."""

    url: str
    title: str
    path: Path | None = None
    source_id: str | None = None
    _pages: list[str] | None = field(default=None, repr=False)

    def pages(self) -> list[str]:
        if self._pages is None:
            self._pages = pdf_page_texts(self.path) if self.path is not None else []
        return self._pages


def resolve_refs(references: Iterable[dict[str, Any]], docs: Sequence[Doc]) -> list[dict[str, Any]]:
    """Resolve each reference to a document (and, where findable, a page).

    A reference whose ``source_id`` names one of *docs* is attributed to it outright —
    the page may still be unknown. One with no such match (a digest from before source
    ids were kept) is attributed to whichever document its text is found in; if it is
    found in none it is left out, because naming a guessed document is worse than
    naming none. Returns the ``items`` list of ``citations_json``.
    """
    by_source = {d.source_id: d for d in docs if d.source_id}
    items: list[dict[str, Any]] = []
    for ref in references:
        n = ref.get("citation_number")
        if n is None:
            continue
        cited = ref.get("cited_text")
        source_id = ref.get("source_id")
        doc = by_source.get(source_id) if source_id else None
        loc: Location | None = None
        if doc is not None:
            loc = locate(cited, doc.pages())
        else:
            matches = [(found, cand) for cand in docs if (found := locate(cited, cand.pages())) is not None]
            # A short passage turning up in several documents says nothing about which one
            # it came from (a heading, a standard phrase); only a long one is distinctive.
            if len(matches) == 1 or (matches and len(normalize(cited)) >= _MIN_PROBE_TEXT):
                loc, doc = max(matches, key=lambda m: m[0].confidence)
        if doc is None:
            continue
        item: dict[str, Any] = {"n": n, "url": doc.url, "doc": doc.title}
        if loc is not None:
            item["page"] = loc.page
            if loc.page_end > loc.page:
                item["pageEnd"] = loc.page_end
        items.append(item)
    return items


def dump(items: list[dict[str, Any]], resolved_at: str) -> str:
    return json.dumps({"v": SCHEMA, "resolvedAt": resolved_at, "items": items}, ensure_ascii=False)


def load_items(citations_json: str | None) -> dict[int, dict[str, Any]]:
    """``citations_json`` → ``{citation_number: item}``. Empty for NULL or unreadable data."""
    if not citations_json:
        return {}
    try:
        data = json.loads(citations_json)
        return {int(it["n"]): it for it in data.get("items", []) if "n" in it}
    except (ValueError, TypeError, AttributeError, KeyError):
        logger.warning("unreadable citations_json ignored")
        return {}
