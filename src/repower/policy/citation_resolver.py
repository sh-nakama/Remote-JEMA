"""Resolve the citations of meetings that were summarised before pages were tracked.

New digests are resolved by the pipeline at ingest, from PDFs it already holds. This
module is for the rest: it fetches a meeting's source PDFs, finds each citation's page
(:mod:`repower.policy.citations`) and stores the result. Two callers:

* the local web API, when someone clicks a citation that has no page yet — one human
  click, one meeting, at human pace; and
* ``repower policy resolve-citations`` — a resumable sweep that works through the
  back-catalogue a few meetings at a time and stops when the host's request budget is
  spent, so it can be re-run until nothing is left.

Everything is routed through :func:`pipeline._download_pdf` (the WAF clearance, pacing
and circuit breaker the rest of the policy fetchers share) and paced by
:func:`pipeline._batch_interval`, because a meeting is a dozen files from one host.
"""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repower.config import POLICY_DIR
from repower.policy import citations
from repower.policy.pipeline import (
    _HOSTILE_FETCH_KINDS,
    _TRANSIENT_FETCH_KINDS,
    _batch_interval,
    _download_pdf,
    _select_materials,
)
from repower.policy.store import (
    meeting_digest,
    meeting_materials,
    meetings_missing_citations,
    set_meeting_citations,
)
from repower.scrapers.http_cache import budget_exhausted, host_pace

logger = logging.getLogger(__name__)

# One resolution per meeting at a time. A second click on the same chip while the first is still
# downloading would otherwise start a parallel crawl of the same dozen files.
_locks: dict[tuple[str, int], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str, num: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((key, num), threading.Lock())


def pdf_cache_dir(key: str, num: int) -> Path:
    """Where a meeting's PDFs are kept (``data/policy/pdf/…`` — gitignored with the rest of ``data/policy``)."""
    return POLICY_DIR / "pdf" / key / str(num)


def resolve_meeting(key: str, num: int, *, db_path: str | None = None, keep_pdfs: bool = True,
                    force: bool = False) -> dict[str, Any]:
    """Resolve and store one meeting's citations. Never raises for an expected failure.

    ``status``: ``resolved`` | ``blocked`` (the host refused us — transient, retry later) |
    ``error`` (a document is permanently unavailable) | ``unavailable`` (PyMuPDF missing) |
    ``no_digest``. ``items`` / ``resolved`` count what was stored; ``pages`` how many carry a page.

    ``keep_pdfs`` leaves the downloaded files in :func:`pdf_cache_dir`, so a re-run (or the next
    click) costs no request; a sweep passes False so it does not accumulate gigabytes.
    """
    with _lock_for(key, num):
        digest = meeting_digest(key, num, db_path=db_path)
        if digest is None:
            return {"status": "no_digest"}
        refs = digest.get("references") or []
        selected = _select_materials(meeting_materials(key, num, db_path=db_path))

        # Which documents must be read? If every cited source id maps to a material we know
        # exactly which ones; otherwise (digests older than source-id tracking) the passage text
        # is all there is to go on, and any document may hold it.
        by_source = {m["nblm_source_id"]: m for m in selected if m.get("nblm_source_id")}
        cited_ids = {r.get("source_id") for r in refs if r.get("source_id")}
        needed = [by_source[s] for s in cited_ids] if cited_ids and cited_ids <= by_source.keys() else selected
        needed = list({m["pdf_id"]: m for m in needed}.values())

        try:
            import pymupdf  # noqa: F401  # fail before downloading a dozen PDFs we cannot read
        except ImportError:
            return {"status": "unavailable", "detail": "PyMuPDF is not installed (pip install pymupdf)"}

        work = pdf_cache_dir(key, num)
        paths: dict[str, Path] = {}
        missing = []
        for m in needed:
            dest = work / f"{m['pdf_id']}.pdf"
            if dest.exists() and dest.stat().st_size > 0:
                paths[m["pdf_id"]] = dest
            else:
                missing.append((m, dest))
        failures: list[str] = []
        with host_pace(_batch_interval(len(missing))):
            for m, dest in missing:
                kind = _download_pdf(m["url"], dest, db_path=db_path)
                if kind == "ok":
                    paths[m["pdf_id"]] = dest
                    continue
                failures.append(kind)
                if kind in _HOSTILE_FETCH_KINDS:
                    break  # the rest cannot succeed, and each try is a strike on the breaker
        if failures:
            detail = ",".join(sorted(set(failures)))
            logger.warning("citations %s 第%d回: %d/%d documents not fetched (%s)",
                           key, num, len(failures), len(needed), detail)
            # Same verdict as the pipeline: a host refusing us is its condition, not the
            # meeting's. Nothing is stored, and what did download stays cached, so a retry
            # only asks for the rest.
            if any(k in _TRANSIENT_FETCH_KINDS for k in failures):
                return {"status": "blocked", "detail": detail}
            # A document that is permanently gone (404…) must not pin the meeting to the front
            # of the sweep forever: resolve against the ones we have. Citations into the lost
            # document simply stay unlinked.
            needed = [m for m in needed if m["pdf_id"] in paths]

        docs = [
            citations.Doc(url=m["url"] or "", title=m["title"] or "", path=paths[m["pdf_id"]],
                          source_id=m.get("nblm_source_id"))
            for m in needed
        ]
        try:
            items = citations.resolve_refs(refs, docs)
        except Exception as e:  # noqa: BLE001 — a corrupt PDF must not take the caller down
            logger.warning("citations %s 第%d回: could not read the PDFs", key, num, exc_info=True)
            return {"status": "error", "detail": f"could not read the PDFs ({type(e).__name__})"}
        set_meeting_citations(key, num, citations.dump(items, datetime.now(UTC).isoformat(timespec="seconds")),
                              db_path=db_path)
        if not keep_pdfs:
            shutil.rmtree(work, ignore_errors=True)
        return {"status": "resolved", "items": len(items), "pages": sum(1 for i in items if i.get("page")),
                "refs": len(refs)}


def backfill(db_path: str | None = None, *, max_meetings: int = 5, committee_key: str | None = None,
             keep_pdfs: bool = False) -> dict[str, Any]:
    """Resolve up to *max_meetings* not-yet-resolved meetings, newest first.

    Resumable: a resolved meeting leaves the worklist (``citations_json`` is set even when
    nothing could be placed), so re-running continues where it stopped. Stops early — and says
    why in ``stopped_early`` — when the host's request budget is spent or the host refuses us;
    pushing on would only deepen a WAF block that clears on its own schedule.
    """
    todo = meetings_missing_citations(db_path, committee_key)
    summary: dict[str, Any] = {"pending": len(todo), "attempted": 0, "resolved": 0, "pages": 0, "refs": 0,
                               "errors": [], "stopped_early": None}
    for key, num in todo[:max_meetings]:
        first = next((m["url"] for m in meeting_materials(key, num, db_path=db_path) if m.get("url")), None)
        if first and budget_exhausted(first):
            summary["stopped_early"] = "budget_exhausted"
            break
        res = resolve_meeting(key, num, db_path=db_path, keep_pdfs=keep_pdfs)
        summary["attempted"] += 1
        logger.info("citations %s 第%d回: %s", key, num, res)
        if res["status"] == "resolved":
            summary["resolved"] += 1
            summary["pages"] += res["pages"]
            summary["refs"] += res["refs"]
        elif res["status"] == "unavailable":
            summary["stopped_early"] = "pymupdf_missing"
            break
        elif res["status"] == "blocked":
            summary["stopped_early"] = "host_blocked"
            break
        else:
            summary["errors"].append(f"{key} 第{num}回: {res['status']} {res.get('detail', '')}".strip())
    return summary
