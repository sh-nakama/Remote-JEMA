"""Summarisation state machine: per-meeting briefings + per-committee synthesis.

Per new meeting: stage its key PDFs → ephemeral NotebookLM notebook → detailed
Japanese briefing (``generate report --format custom``) + a compact English digest
(``ask``) → persist → **delete the notebook**. Per committee: a persistent
synthesis notebook whose sources are the small per-meeting briefing markdowns is
refreshed and re-summarised into the running document.

Crash-safety: the notebook id and each state transition are committed *before* the
next network call, so a re-run (``resume``) picks up where it left off; the
ephemeral notebook is deleted only *after* its briefing is persisted.

Everything here needs valid NotebookLM auth; ``run``/``resume`` gate on it first.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from repower.config import NOTEBOOKLM_SOURCE_CAP
from repower.policy import notebook as nb
from repower.policy.committees import Committee
from repower.policy.scraper import list_materials
from repower.policy.store import (
    clear_generation_request,
    committee_or_config,
    forget_staged_materials,
    get_committee,
    mark_synthesized,
    meeting_materials,
    meetings_for_synthesis,
    pending_meetings,
    record_meeting,
    regenerate_running_doc,
    reset_synthesized,
    set_material_state,
    stalled_synthesis_committees,
    synthesized_meeting_nums,
    update_committee,
    update_meeting,
)
from repower.scrapers.http_cache import (
    circuit_cooldown,
    classify,
    conditional_get,
    host_pace,
    min_host_interval,
)

logger = logging.getLogger(__name__)

# Per-meeting ingestion budget — small handful of sources, well under any tier cap.
MEETING_SOURCE_BUDGET = min(NOTEBOOKLM_SOURCE_CAP, 12)
# Kind priority for selecting which documents to ingest (minutes first).
_KIND_PRIORITY = {"minutes": 0, "brief": 1, "compilation": 2, "handout": 3, "agenda": 4, "appendix": 5}
# Kinds the pipeline will ever ingest. Exported so reporting can count "how many of
# this meeting's documents were *meant* to reach NotebookLM" — counting every PDF on
# the page instead makes a perfectly complete meeting look short by however many
# 委員名簿-style files it happens to list.
INGESTABLE_KINDS = frozenset(_KIND_PRIORITY)

_MEETING_PROMPT = """この会合（{name_ja} 第{num}回）の議論を、提供された資料すべてに基づいて詳細に要約してください。

【最重要】本会合は複数の議題（配布資料）で構成される場合があります。特定の資料だけに偏らず、提供された全ての議題・資料を必ず網羅してください。冒頭でこの会合の議題一覧を示し、各議題ごとに論点・数値・結論を整理すること。

必ず以下の4部構成とし、各項目に出典資料名を明記してください。憶測は避け、資料に書かれていない決定を創作しないこと。「決定事項」と「事務局提案・継続検討事項（この回では確定していない事項）」は明確に区別すること。

(1) 主要な論点（議題ごとに整理）
(2) 主要な数値・データ
(3) 結論・決定事項（および継続検討・引き続き議論となった事項）
(4) 今後の検討課題
"""

_ENGLISH_DIGEST_Q = (
    "Summarize this meeting in English as concise bullet points under three headings: "
    "Key decisions, Points of disagreement, Action items. Base everything strictly on the sources."
)

_SYNTHESIS_PROMPT = """\
この委員会のこれまでの会合要約に基づき、現在の政策的な議論の全体像を、会合番号を付して要約してください。
必ず以下の4部構成とすること。

(1) 現在の主要論点
(2) 未解決の争点
(3) 会合を跨ぐ議論の推移
(4) 直近の決定事項
"""


def _scratch() -> Path:
    base = Path(os.getenv("RUNNER_TEMP") or tempfile.gettempdir()) / "repower_policy_pdfs"
    base.mkdir(parents=True, exist_ok=True)
    return base


# Fetch outcomes that mean "this host refused us today", as distinct from "this
# document is gone". Only the latter should count against a meeting's retry
# budget: a WAF block is a property of the host at that moment, and the very same
# PDFs download fine on a calm day. Anything not listed here is treated as a
# property of the document (see the verdict in ``summarize_meeting``).
_TRANSIENT_FETCH_KINDS = frozenset({
    "circuit_open",          # host is cooling down after repeated blocks
    "challenge_unresolved",  # WAF 202 ladder ran out
    "blocked_403",           # host refused this client outright
    "deadline_exceeded",     # ran out of time, not out of document
    "network_error",         # DNS/TLS/connection/timeout
    "server_error",          # 5xx/429 that survived the transient retries
})

# Fetch outcomes that mean the *host* has turned on us, so the rest of this
# meeting's documents are already lost. Continuing would spend requests that
# cannot succeed and, worse, each one is another strike against the per-host
# circuit breaker — three of them open it for 5 minutes and take every other
# committee on that host down with it. Observed: a meeting abandoned at the first
# challenge takes one strike; running the batch to the end took three.
_HOSTILE_FETCH_KINDS = frozenset({"challenge_unresolved", "blocked_403", "circuit_open"})

# Batch pacing. The 2s floor is sized for detection sweeps, which fetch one page per
# host; a meeting is a dozen files from the *same* host, and METI's edge treats that
# as a burst — measured, it served six PDFs at 2s spacing and challenged the seventh
# ~12s in. So the gap widens with the size of the batch: the more documents a meeting
# has, the slower we walk through them.
#
#   files ≤4 → 2.0s (unchanged) · 6 → 4.0s · 12 → 10.0s · 16+ → 12.0s (capped)
_BATCH_PACE_FREE = 4      # documents that pace at the ordinary floor
_BATCH_PACE_STEP = 1.0    # extra seconds per document beyond that
_BATCH_PACE_CAP = 12.0    # never crawl slower than this, however large the meeting


def _batch_interval(n: int) -> float:
    """Seconds between requests when pulling *n* documents from one host."""
    return min(_BATCH_PACE_CAP,
               min_host_interval() + _BATCH_PACE_STEP * max(0, n - _BATCH_PACE_FREE))


# Blocked meetings cost no NotebookLM quota, so they don't spend a slot of
# ``max_per_run`` — but a run still has to stop looking eventually. This bounds one
# round to roughly a single sweep of the tracked set (~85 committees) rather than
# letting a host-wide outage walk a backlog of thousands. Hitting it is logged, not
# silent.
_MAX_BLOCKED_ATTEMPTS = 50

# Errors that are properties of the *account or session*, not of the meeting being
# worked on: the quota is spent, the browser cookie lapsed mid-run, or NotebookLM
# stopped answering. The next meeting would fail identically, so these halt the run
# instead of being retried down the worklist. Anything else is the meeting's own
# problem and stays a per-meeting 'error'.
_HALTING = (nb.NotebookLMRateLimitError, nb.NotebookLMAuthError, nb.NotebookLMTimeout)


def _stop_reason(exc: nb.NotebookLMError) -> str:
    """Which summary flag explains a run halted by *exc*."""
    if isinstance(exc, nb.NotebookLMRateLimitError):
        return "rate_limited"
    if isinstance(exc, nb.NotebookLMAuthError):
        return "auth_expired"
    return "timed_out"


def _download_pdf(url: str, dest: Path, *, db_path: str | None = None,
                  timeout: float = 180.0) -> str:
    """Download a committee PDF to *dest*. Returns a :data:`FETCH_KINDS` slug.

    Routed through :mod:`repower.scrapers.http_cache` rather than issuing its own
    requests, so a PDF gets exactly what the committee index page beside it gets:
    the host's reused curl_cffi session (replaying a WAF clearance cookie the
    index fetch already earned, instead of re-earning it per file), the 202
    challenge ladder, per-host pacing, and the circuit breaker. Fetching these by
    hand was why a 202 on a PDF used to be a one-shot give-up while the index it
    came from patiently retried.

    ``force=True``: we keep no persistent copy of the bytes (the scratch dir is
    wiped per run, and lives under RUNNER_TEMP in CI), so a 304 would leave
    nothing to ingest. The other policy fetchers force for the same reason.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        status, content = conditional_get(
            url, db_path=db_path, headers={"Accept-Language": "ja,en;q=0.9"},
            allow_curl_fallback=True, force=True, timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001 — typed by http_cache; classify and report
        kind = classify(e)
        logger.warning("policy pdf %s -> %s: %s", url, kind, e)
        return kind
    if status == "not_found":
        logger.warning("policy pdf %s -> 404", url)
        return "not_found"
    if status != "ok" or not content:
        logger.warning("policy pdf %s -> %s with no body", url, status)
        return "parse_error"
    dest.write_bytes(content)
    if dest.stat().st_size <= 0:
        logger.warning("policy pdf %s -> empty file", url)
        return "parse_error"
    return "ok"


def _fail_meeting(meeting_row: int, db_path: str | None, *, flag: str | None,
                  message: str, **fields) -> None:
    """Mark a meeting errored *and say why*, in words.

    ``quality_flag`` is a coarse slug and the generic NotebookLM path has none at
    all, so on its own the DB could only report "this broke" — never what broke.
    The message is what the Manage status table shows; it is capped because it can
    carry an upstream response body, and it rides the Hugging Face sync.
    """
    from datetime import UTC, datetime

    update_meeting(
        meeting_row, db_path=db_path, state="error", quality_flag=flag,
        last_error=" ".join(str(message).split())[:500],
        last_error_at=datetime.now(UTC), **fields,
    )


def _select_materials(materials: list[dict]) -> list[dict]:
    """Code-enforced source selection: minutes (or brief if none), handouts,
    compilation, agenda; appendices only if budget remains. Capped to the budget."""
    usable = [m for m in materials if m["kind"] in _KIND_PRIORITY]
    has_minutes = any(m["kind"] == "minutes" for m in usable)
    if has_minutes:
        usable = [m for m in usable if m["kind"] != "brief"]  # minutes supersede the brief
    usable.sort(key=lambda m: _KIND_PRIORITY.get(m["kind"], 9))
    if len(usable) > MEETING_SOURCE_BUDGET:
        usable = [m for m in usable if m["kind"] != "appendix"]
    return usable[:MEETING_SOURCE_BUDGET]


def summarize_meeting(committee: Committee, meeting_num: int, *, db_path: str | None = None) -> str:
    """Summarise one meeting end-to-end. Returns the final state.

    ``'done'`` | ``'error'`` | ``'generating'`` (left for resume) | ``'blocked'``.
    ``'blocked'`` means the source host stopped us before anything reached
    NotebookLM: the DB row is still marked errored, but no quota was spent, so the
    caller must not charge it against the run's budget.

    Looks up the meeting by (committee, number); the caller ensures the row exists.
    """
    # Ensure materials are enumerated (detection may have only recorded the number).
    materials = meeting_materials(committee.key, meeting_num, db_path=db_path)
    if not materials:
        found = list_materials(committee, meeting_num, db_path=db_path)
        record_meeting(committee.key, meeting_num, found, db_path=db_path)
        materials = meeting_materials(committee.key, meeting_num, db_path=db_path)

    selected = _select_materials(materials)
    meeting_row = _meeting_id(committee.key, meeting_num, db_path)
    if meeting_row is None:
        record_meeting(committee.key, meeting_num, None, db_path=db_path)
        meeting_row = _meeting_id(committee.key, meeting_num, db_path)
    if not selected:
        _fail_meeting(
            meeting_row, db_path, flag="no_sources",
            message=(
                f"No usable source documents: the committee page lists {len(materials)} "
                "material(s), none of an ingestable kind."
            ),
        )
        return "error"

    work = _scratch() / committee.key / str(meeting_num)
    started = time.monotonic()
    notebook_id: str | None = None
    # Documents already fetched are kept when a meeting is left pending, so the next
    # attempt only asks for what is missing (see the `finally` below).
    keep_scratch = False
    try:
        update_meeting(meeting_row, db_path=db_path, state="downloading")
        # (material, staged path) pairs — the material travels with the file so an
        # ingest failure can name the document it lost, not just a count.
        staged: list[tuple[dict, Path]] = []
        failures: list[str] = []
        reused = 0
        unattempted = 0
        with host_pace(_batch_interval(len(selected))):
            for i, m in enumerate(selected):
                dest = work / f"{m['pdf_id']}.pdf"
                if dest.exists() and dest.stat().st_size > 0:
                    # Left by an earlier attempt that couldn't finish the set. Re-asking
                    # for it would spend one of the few requests this host allows us
                    # before it starts challenging — on bytes already on disk.
                    reused += 1
                    staged.append((m, dest))
                    set_material_state(committee.key, m["pdf_id"], db_path=db_path,
                                       status="downloaded", nblm_source_id=None)
                    continue
                kind = _download_pdf(m["url"], dest, db_path=db_path)
                set_material_state(committee.key, m["pdf_id"], db_path=db_path,
                                   status="downloaded" if kind == "ok" else "error",
                                   nblm_source_id=None)
                if kind == "ok":
                    staged.append((m, dest))
                    continue
                failures.append(kind)
                if kind in _HOSTILE_FETCH_KINDS:
                    # Stop asking. Under all-or-nothing this meeting is already lost,
                    # and every further request is both futile and a strike towards
                    # opening the host's breaker on the rest of the run.
                    unattempted = len(selected) - i - 1
                    logger.warning(
                        "policy %s 第%d回: %s on %s — abandoning the batch with %d "
                        "document(s) unattempted (%d already on disk for the retry)",
                        committee.key, meeting_num, kind, m["pdf_id"], unattempted, len(staged),
                    )
                    break
        if reused:
            logger.info("policy %s 第%d回: reused %d document(s) staged by an earlier attempt",
                        committee.key, meeting_num, reused)
        if failures:
            # All-or-nothing: a briefing written from a subset of a meeting's papers
            # is worse than no briefing, because it reads like a complete one. The
            # case that forced this: 11 of 12 documents were blocked mid-download and
            # the only one that landed was 配布資料一覧 — the *list* of documents — so
            # NotebookLM dutifully summarised a table of contents and the meeting was
            # marked done.
            #
            # A host that blocked us is not a meeting beyond saving, so leave the
            # retry budget alone and try the same PDFs again on a calm day — one
            # mixed verdict counts as blocked, since a single transient kind is
            # enough to make "these documents are gone" the wrong conclusion.
            # Documents that are genuinely absent do burn a retry, so a meeting with
            # a permanently dead link leaves the worklist after MAX_RETRIES instead
            # of being re-attempted every run forever.
            detail = ",".join(sorted(set(failures))) or "no materials"
            hosts = sorted({urlsplit(m["url"] or "").hostname or "?" for m in selected})
            why = (
                f"{len(failures) + unattempted} of {len(selected)} document(s) could not be "
                f"downloaded ({detail}) from {', '.join(hosts)}"
                + (f"; {unattempted} not attempted after the host turned us away" if unattempted else "")
                + f"; {len(staged)} kept for the next attempt"
            )
            if any(k in _TRANSIENT_FETCH_KINDS for k in failures):
                logger.warning(
                    "policy %s 第%d回: %d/%d sources not downloaded (host blocked: %s) — "
                    "will retry on a later run without burning a retry",
                    committee.key, meeting_num, len(failures), len(selected), detail,
                )
                _fail_meeting(meeting_row, db_path, flag="download_blocked",
                              message=why + " — the host blocked us; will be retried")
                # Keep what did download: the next attempt then spends its requests
                # only on the missing files, so a large meeting converges over a
                # couple of passes instead of re-burning the same budget forever.
                keep_scratch = True
                # Not "error" to the caller: nothing reached NotebookLM, so this
                # must not spend a slot of the run's quota budget.
                return "blocked"
            else:
                logger.error("policy %s 第%d回: %d/%d sources not downloaded (%s)",
                             committee.key, meeting_num, len(failures), len(selected), detail)
                _fail_meeting(meeting_row, db_path, flag="download_failed", message=why,
                              retry_count=_bump_retry(committee.key, meeting_num, db_path))
            return "error"

        title = f"{committee.key} 第{meeting_num}回"
        # A resumed/retried meeting may still own the notebook from its earlier
        # interrupted attempt (the wait-timeout path deliberately keeps it). The
        # rerun restages every source from scratch, so reusing that notebook would
        # duplicate them — delete it first instead of orphaning it.
        stale_notebook_id = _meeting_notebook_id(meeting_row, db_path)
        if stale_notebook_id:
            try:
                nb.delete_notebook(stale_notebook_id)
            except nb.NotebookLMError as e:
                logger.warning("could not delete stale notebook %s: %s", stale_notebook_id, e)
        notebook_id = nb.create_notebook(title)
        # Persist the notebook id + state BEFORE generation, so a crash is recoverable.
        update_meeting(meeting_row, db_path=db_path, state="ingesting", notebook_id=notebook_id)

        source_ids = []
        not_ingested: list[str] = []
        for m, path in staged:
            try:
                sid = nb.add_source(notebook_id, str(path))
            except _HALTING:
                # Quota spent / session lapsed / NotebookLM stopped answering: the
                # account is the problem, not this document. Let the outer handlers
                # halt the run instead of blaming the meeting.
                raise
            except nb.NotebookLMError as e:
                # Same rule as a failed download: a notebook missing one of the
                # meeting's papers writes a briefing that reads complete and isn't.
                logger.warning("add_source failed (%s): %s", path.name, e)
                not_ingested.append(f"{m['pdf_id']} ({type(e).__name__})")
                continue
            source_ids.append(sid)
            set_material_state(committee.key, m["pdf_id"], db_path=db_path,
                               status="ingested", nblm_source_id=sid)
        if not_ingested:
            try:
                nb.delete_notebook(notebook_id)  # nothing was generated from it yet
            except nb.NotebookLMError as e:
                logger.warning("could not delete notebook %s: %s", notebook_id, e)
            notebook_id = None
            _fail_meeting(
                meeting_row, db_path, flag="ingest_failed",
                message=(f"{len(not_ingested)} of {len(staged)} downloaded document(s) could "
                         f"not be added to the notebook: {', '.join(not_ingested[:4])}"),
                notebook_id=None,
                retry_count=_bump_retry(committee.key, meeting_num, db_path),
            )
            return "error"
        for sid in source_ids:
            nb.wait_source(notebook_id, sid)

        quality_flag = _ocr_guard(notebook_id, source_ids)

        prompt = _MEETING_PROMPT.format(name_ja=committee.name_ja, num=meeting_num)
        task_id = nb.generate_report(notebook_id, prompt, language="ja", fmt="custom")
        update_meeting(meeting_row, db_path=db_path, state="generating", report_task_id=task_id)
        if not nb.wait_artifact(notebook_id, task_id):
            keep_scratch = True  # resume restages from scratch; don't re-fetch these
            return "generating"  # leave for resume; do NOT delete the notebook

        out_md = work / "briefing.md"
        if not nb.download_report(notebook_id, task_id, out_md):
            keep_scratch = True
            return "generating"
        briefing = out_md.read_text(encoding="utf-8")

        digest_json = None
        try:
            digest_json = json.dumps(nb.ask(notebook_id, _ENGLISH_DIGEST_Q), ensure_ascii=False)
        except nb.NotebookLMError as e:
            logger.warning("english digest failed for %s 第%d回: %s", committee.key, meeting_num, e)

        if quality_flag is None and len(briefing) < 400:
            quality_flag = "short_output"

        update_meeting(
            meeting_row, db_path=db_path, state="done", briefing_md=briefing,
            digest_en_json=digest_json, quality_flag=quality_flag,
            gen_seconds=round(time.monotonic() - started, 1),
            # This attempt succeeded, so any message from an earlier failed one no
            # longer describes the meeting — clear it rather than leave the status
            # table reporting a resolved error against a summarised meeting.
            last_error=None, last_error_at=None,
        )
        regenerate_running_doc(committee.key, db_path=db_path)

        # Delete the ephemeral notebook only AFTER the briefing is persisted.
        try:
            nb.delete_notebook(notebook_id)
        except nb.NotebookLMError as e:
            logger.warning("could not delete notebook %s: %s", notebook_id, e)
        return "done"
    except nb.NotebookLMAuthError:
        raise  # bubble up — the whole run should stop and alert
    except (nb.NotebookLMRateLimitError, nb.NotebookLMTimeout) as e:
        # Account-wide and transient — not a bad meeting. A rate limit says the
        # quota is spent; a timeout says NotebookLM (or a lapsing session) stopped
        # answering. Either way the *next* meeting would fail identically, so don't
        # burn this one's retry budget or leak its ephemeral notebook: delete it and
        # reset to 'detected' so a later run reprocesses cleanly, then bubble up
        # so the whole run stops (continuing would only burn the next meetings).
        logger.warning("summarize_meeting %s 第%d回 deferred — NotebookLM %s",
                       committee.key, meeting_num, e)
        if notebook_id:
            try:
                nb.delete_notebook(notebook_id)
            except nb.NotebookLMError:
                pass
        # Also clear any quality_flag from an earlier failed attempt (e.g. a stale
        # 'no_sources' from before materials were enumerated) — this attempt got far
        # enough to have sources, so the old flag no longer describes the meeting.
        update_meeting(meeting_row, db_path=db_path, state="detected", notebook_id=None,
                       quality_flag=None, last_error=None, last_error_at=None)
        # This meeting is explicitly being handed back to a later run, so its
        # documents must survive with it. Losing them here was worse than losing
        # them on the blocked path: the downloads had all *succeeded*, and throwing
        # them away meant the retry re-ran the whole burst against a WAF that only
        # tolerates a handful of requests — to fetch bytes we already had.
        keep_scratch = True
        raise
    except nb.NotebookLMError as e:
        logger.error("summarize_meeting %s 第%d回 failed: %s", committee.key, meeting_num, e)
        # No slug fits this one — it is whatever NotebookLM refused to do — so the
        # message is the only record of the cause. Name the exception type too: the
        # text alone is often an opaque upstream string.
        _fail_meeting(meeting_row, db_path, flag=None,
                      message=f"NotebookLM {type(e).__name__}: {e}",
                      retry_count=_bump_retry(committee.key, meeting_num, db_path))
        return "error"
    finally:
        if not keep_scratch:
            shutil.rmtree(work, ignore_errors=True)
            # The staged files are gone, so "downloaded" would be a claim about
            # disk that is no longer true and the next attempt's resume check
            # would disagree with. Ingested rows keep their state — that happened.
            forget_staged_materials(committee.key, meeting_num, db_path=db_path)


def _ocr_guard(notebook_id: str, source_ids: list[str]) -> str | None:
    """Flag scanned/empty minutes: if the first source indexes to ~no text, the PDF
    is probably image-only and the briefing will be weak."""
    if not source_ids:
        return None
    try:
        ft = nb.source_fulltext(notebook_id, source_ids[0])
        if (ft.get("char_count") or 0) < 200:
            return "ocr_suspect"
    except nb.NotebookLMError:
        return None
    return None


def _rollover_synthesis(committee: Committee, watermark: int, *,
                        db_path: str | None = None) -> str:
    """Continue a full committee synthesis in a fresh notebook; return its id.

    NotebookLM caps sources per notebook, so a long-running committee eventually
    fills one (``chousei_jukyu`` reached 50/50 with 44 meetings still queued).
    Rather than compacting the oldest briefings into an archive source, the
    synthesis simply moves on: the full notebook is left intact and untouched, and
    ``archive_watermark_meeting`` records the last meeting it covers so the new
    notebook starts clean at the next one. The title carries that boundary too, so
    a committee's notebooks stay tellable apart in the NotebookLM account.

    Only the NotebookLM-generated *synthesis narrative* narrows to the new
    notebook's meetings. The per-committee running document is regenerated from
    the briefings held in the DB, so it stays complete across a rollover.
    """
    nb_id = nb.create_notebook(f"{committee.key} synthesis (第{watermark + 1}回〜)")
    update_committee(committee.key, db_path=db_path, synthesis_notebook_id=nb_id,
                     source_count=0, archive_watermark_meeting=watermark)
    logger.warning(
        "policy synthesis for %s hit the %d-source cap — continuing in a new notebook "
        "(%s); meetings up to 第%d回 stay in the superseded one",
        committee.key, NOTEBOOKLM_SOURCE_CAP, nb_id, watermark,
    )
    return nb_id


def synthesize_committee(committee: Committee, *, db_path: str | None = None) -> bool:
    """Refresh the persistent per-committee synthesis notebook + running document.

    Adds the briefing markdowns of any newly-``done`` meetings as sources, then
    regenerates the committee-level synthesis. Returns True if it ran.
    """
    state = get_committee(committee.key, db_path=db_path)
    new_meetings = meetings_for_synthesis(committee.key, db_path=db_path)
    folded = synthesized_meeting_nums(committee.key, db_path=db_path)
    # Recovery: an earlier run folded briefings into the synthesis notebook
    # (synth_done set) but was interrupted (rate limit / crash) before the
    # report was generated, leaving running_summary_md empty. Nothing is "new"
    # then, but the report must still be generated from the existing notebook —
    # otherwise the committee's synthesis stays empty until its NEXT meeting.
    needs_recovery = bool(
        folded and state is not None
        and state.synthesis_notebook_id and not state.running_summary_md
    )
    if not new_meetings and not needs_recovery:
        regenerate_running_doc(committee.key, db_path=db_path)
        return False

    nb_id = state.synthesis_notebook_id if state else None
    if not nb_id:
        nb_id = nb.create_notebook(f"{committee.key} synthesis")
        update_committee(committee.key, db_path=db_path, synthesis_notebook_id=nb_id)

    # The synth_done meetings above the watermark are exactly the live notebook's
    # sources, so count those rather than trusting the cached ``source_count`` —
    # an interrupted run can leave that NULL or stale, and after a rollover
    # ``folded`` spans every notebook the committee has ever used.
    watermark = (state.archive_watermark_meeting if state else None) or 0
    src_count = len([n for n in folded if n > watermark])

    work = _scratch() / committee.key / "synthesis"
    work.mkdir(parents=True, exist_ok=True)
    try:
        added_nums: list[int] = []
        for m in new_meetings:
            if src_count >= NOTEBOOKLM_SOURCE_CAP:
                nb_id = _rollover_synthesis(
                    committee, max([*folded, *added_nums], default=0), db_path=db_path,
                )
                src_count = 0
            md = work / f"meeting_{m['meeting_num']:03d}.md"
            md.write_text(m["briefing_md"], encoding="utf-8")
            try:
                nb.add_source(nb_id, str(md))
            except _HALTING:
                raise  # bubble up: stop synthesis, leave the rest for a later run
            except nb.NotebookLMError as e:
                logger.warning("synthesis add_source failed (%s 第%d回): %s",
                               committee.key, m["meeting_num"], e)
                continue
            # Mark as folded in as soon as the source lands, so a later failure
            # (e.g. a rate-limited report) doesn't re-add it as a duplicate.
            mark_synthesized(committee.key, m["meeting_num"], db_path=db_path)
            src_count += 1
            added_nums.append(m["meeting_num"])

        task_id = nb.generate_report(nb_id, _SYNTHESIS_PROMPT, language="ja", fmt="custom")
        if not nb.wait_artifact(nb_id, task_id):
            return False
        out_md = work / "synthesis.md"
        synthesis_md = out_md.read_text(encoding="utf-8") if nb.download_report(nb_id, task_id, out_md) else None

        digest_md = None
        try:
            d = nb.ask(nb_id, "Give a one-paragraph English overview of where this committee's "
                              "discussion currently stands.")
            digest_md = (d or {}).get("answer")
        except nb.NotebookLMError:
            pass

        # last_synth_meeting is now informational (the highest meeting in the synthesis);
        # selection is driven by the per-meeting synth_done flag, not this value.
        prior = state.last_synth_meeting if state and state.last_synth_meeting else 0
        latest_num = max([prior, *added_nums, *folded]) if (added_nums or folded) else prior
        update_committee(
            committee.key, db_path=db_path,
            running_summary_md=synthesis_md, running_digest_en_md=digest_md,
            last_synth_meeting=latest_num, source_count=src_count,
        )
        regenerate_running_doc(committee.key, db_path=db_path)
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run(keys: list[str] | None = None, *, max_per_run: int | None = None,
        db_path: str | None = None, states: tuple[str, ...] | None = None,
        breadth_first: bool = False, meeting_num: int | None = None) -> dict:
    """Summarise pending meetings (gated on auth), then refresh each committee's synthesis.

    ``states`` lets ``resume`` target in-flight rows; default is all not-done work.
    ``breadth_first`` spreads the run across committees (newest meeting of each, in
    priority order) rather than draining one committee's backlog — see
    ``pending_meetings``. Returns a summary dict.

    ``meeting_num`` (with exactly one committee key) targets that one meeting and
    nothing else, *bypassing the pending worklist entirely* — so an already-``done``
    meeting can be re-summarised. That is the repair path for a briefing written
    from an incomplete source set; it clears ``synth_done`` so the corrected
    briefing is folded back into the committee synthesis.

    Past the opening ``require_auth`` gate, an ``_HALTING`` error stops the run
    cleanly and names itself in the summary's ``stopped_early`` rather than
    propagating — so a session that lapses mid-run ends the round with a partial
    result, not a traceback.
    """
    nb.require_auth()

    # When no committees are named ("all"), restrict to tracked (enabled) ones so
    # untracking a committee removes it from the daily run. Explicit --committee
    # keys are an intentional override and run regardless of the enabled flag.
    if meeting_num is not None:
        if not keys or len(keys) != 1:
            raise ValueError("meeting_num needs exactly one committee key")
        work = [{"committee_key": keys[0], "meeting_num": meeting_num, "state": "targeted"}]
        # A re-run replaces the briefing, so the copy already folded into the
        # synthesis is stale — let the synthesis pick the new one up.
        reset_synthesized(keys[0], meeting_num, db_path=db_path)
    else:
        work = pending_meetings(db_path=db_path, only_enabled=(not keys),
                                breadth_first=breadth_first)
        if keys:
            work = [m for m in work if m["committee_key"] in keys]
        if states:
            work = [m for m in work if m["state"] in states]

    # ``max_per_run`` exists to guard the NotebookLM daily quota, so it counts the
    # attempts that actually reach NotebookLM. A meeting whose source host blocked
    # the downloads never got that far and cost nothing, so it does not spend a
    # slot — pre-slicing the worklist instead let a bad METI day silently halve the
    # round (4 of 8 slots produced nothing on the day this was written).
    done = errored = blocked = charged = 0
    stop_reason: str | None = None
    touched_committees: set[str] = set()
    # Meetings passed over because their source host is cooling down, per host.
    # Skipping is free (no request is issued) and changes no DB state, so these
    # stay pending and are simply reported at the end.
    skipped_hosts: dict[str, int] = {}
    for item in work:
        if max_per_run and charged >= max_per_run:
            break
        if blocked >= _MAX_BLOCKED_ATTEMPTS:
            logger.warning(
                "policy run: %d meetings blocked by their source hosts before reaching "
                "NotebookLM — stopping this round early with %d meeting(s) still pending",
                blocked, len(work) - charged - blocked,
            )
            break
        committee = committee_or_config(item["committee_key"], db_path=db_path)
        if committee is None:
            continue
        # Don't queue work at a host that is already short-circuiting. Every
        # download would fail instantly with `circuit_open`, marking meeting after
        # meeting blocked and burning the round's blocked budget — while committees
        # on healthy hosts (OCCTO, EGC) never got a turn. Skipping keeps those
        # moving through a METI outage.
        cooldown = circuit_cooldown(committee.url) if committee.url else 0.0
        if cooldown > 0:
            host = urlsplit(committee.url).hostname or "?"
            skipped_hosts[host] = skipped_hosts.get(host, 0) + 1
            continue
        try:
            state = summarize_meeting(committee, item["meeting_num"], db_path=db_path)
        except _HALTING as e:
            stop_reason = _stop_reason(e)
            logger.warning("NotebookLM %s — stopping run after %d meeting(s); the rest stay "
                           "pending: %s", stop_reason, charged, e)
            break
        if state == "blocked":
            # Host trouble, not quota. Leave any queued dashboard request in place
            # so the meeting stays at the front of the next round's worklist.
            blocked += 1
            continue
        charged += 1
        touched_committees.add(item["committee_key"])
        # Clear any queued dashboard request once the meeting has been processed.
        if state in ("done", "error"):
            clear_generation_request(item["committee_key"], item["meeting_num"], db_path=db_path)
        if state == "done":
            done += 1
        elif state == "error":
            errored += 1

    # Skip synthesis once the account/session is the problem (it also generates a
    # report and would just fail the same way).
    synthesized = 0
    if stop_reason is None:
        # Beyond committees touched this run, sweep committees whose synthesis
        # stalled mid-run earlier (sources folded in, report never generated) —
        # they may have nothing pending, so they'd never be touched again.
        stalled = stalled_synthesis_committees(db_path=db_path, only_enabled=(not keys))
        synth_keys = touched_committees | {k for k in stalled if not keys or k in keys}
        for key in sorted(synth_keys):
            committee = committee_or_config(key, db_path=db_path)
            if committee is None:
                continue
            try:
                if synthesize_committee(committee, db_path=db_path):
                    synthesized += 1
            except _HALTING as e:
                stop_reason = _stop_reason(e)
                logger.warning("NotebookLM %s during synthesis of %s — deferring: %s",
                               stop_reason, key, e)
                break

    for host, n in sorted(skipped_hosts.items()):
        logger.warning(
            "policy run: skipped %d meeting(s) on %s — its circuit breaker is open "
            "(they stay pending; retry once the host cools down)", n, host,
        )

    # 'processed' counts meetings actually attempted, not the whole worklist the
    # run was free to draw from.
    return {"processed": charged + blocked, "done": done, "errored": errored,
            "blocked": blocked, "synthesized": synthesized,
            "skipped": sum(skipped_hosts.values()), "skipped_hosts": skipped_hosts,
            "rate_limited": stop_reason == "rate_limited", "stopped_early": stop_reason}


def resume(*, db_path: str | None = None) -> dict:
    """Drain meetings left mid-flight (downloading/ingesting/generating)."""
    return run(db_path=db_path, states=("downloading", "ingesting", "generating"))


# ── small DB helpers kept local to avoid widening store's surface ────────────
def _meeting_id(key: str, meeting_num: int, db_path: str | None) -> int | None:
    from repower.db import PolicyMeeting, get_session, init_db

    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.query(PolicyMeeting.id).filter_by(committee_key=key, meeting_num=meeting_num).one_or_none()
        return row[0] if row else None
    finally:
        session.close()


def _meeting_notebook_id(meeting_id: int, db_path: str | None) -> str | None:
    from repower.db import PolicyMeeting, get_session, init_db

    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.get(PolicyMeeting, meeting_id)
        return row.notebook_id if row is not None else None
    finally:
        session.close()


def _bump_retry(key: str, meeting_num: int, db_path: str | None) -> int:
    from repower.db import PolicyMeeting, get_session, init_db

    init_db(db_path)
    session = get_session(db_path)
    try:
        row = session.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=meeting_num).one_or_none()
        return (row.retry_count or 0) + 1 if row else 1
    finally:
        session.close()
