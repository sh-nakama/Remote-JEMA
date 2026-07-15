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

import httpx

from repower.config import NOTEBOOKLM_SOURCE_CAP
from repower.policy import notebook as nb
from repower.policy.committees import Committee
from repower.policy.scraper import _UA, list_materials
from repower.policy.store import (
    clear_generation_request,
    committee_or_config,
    get_committee,
    mark_synthesized,
    meeting_materials,
    meetings_for_synthesis,
    pending_meetings,
    record_meeting,
    regenerate_running_doc,
    stalled_synthesis_committees,
    synthesized_meeting_nums,
    update_committee,
    update_meeting,
)

logger = logging.getLogger(__name__)

# Per-meeting ingestion budget — small handful of sources, well under any tier cap.
MEETING_SOURCE_BUDGET = min(NOTEBOOKLM_SOURCE_CAP, 12)
# Kind priority for selecting which documents to ingest (minutes first).
_KIND_PRIORITY = {"minutes": 0, "brief": 1, "compilation": 2, "handout": 3, "agenda": 4, "appendix": 5}

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

_SYNTHESIS_PROMPT = """この委員会のこれまでの会合要約に基づき、現在の政策的な議論の全体像を、会合番号を付して要約してください。
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


_DL_HEADERS = {"User-Agent": _UA, "Accept-Language": "ja,en;q=0.9", "Accept": "application/pdf,*/*"}


def _download_pdf(url: str, dest: Path, *, timeout: float = 180.0) -> bool:
    """Download a committee PDF to *dest*.

    Gov hosts behind Akamai (meti.go.jp) reject/throttle plain Python TLS, so we
    try httpx with a browser UA first, then fall back to a curl_cffi Chrome
    impersonation — the same fallback the shared HTTP cache uses for the HTML.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=timeout, headers=_DL_HEADERS) as r:
            if r.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
                if dest.stat().st_size > 0:
                    return True
    except Exception as e:  # noqa: BLE001
        logger.debug("httpx pdf download failed %s: %s", url, e)

    try:
        from curl_cffi import requests as cr  # type: ignore

        r = cr.get(url, impersonate="chrome", timeout=timeout, headers=_DL_HEADERS)
        if r.status_code == 200 and r.content:
            dest.write_bytes(r.content)
            return dest.stat().st_size > 0
        logger.warning("policy pdf %s -> HTTP %s", url, r.status_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("policy pdf download failed %s: %s", url, e)
    return False


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
    """Summarise one meeting end-to-end. Returns the final state ('done'/'error').

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
        update_meeting(meeting_row, db_path=db_path, state="error", quality_flag="no_sources")
        return "error"

    work = _scratch() / committee.key / str(meeting_num)
    started = time.monotonic()
    notebook_id: str | None = None
    try:
        update_meeting(meeting_row, db_path=db_path, state="downloading")
        staged: list[Path] = []
        for m in selected:
            dest = work / f"{m['pdf_id']}.pdf"
            if _download_pdf(m["url"], dest):
                staged.append(dest)
        if not staged:
            update_meeting(meeting_row, db_path=db_path, state="error", quality_flag="download_failed")
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
        for path in staged:
            try:
                source_ids.append(nb.add_source(notebook_id, str(path)))
            except nb.NotebookLMError as e:
                logger.warning("add_source failed (%s): %s", path.name, e)
        for sid in source_ids:
            nb.wait_source(notebook_id, sid)

        quality_flag = _ocr_guard(notebook_id, source_ids)

        prompt = _MEETING_PROMPT.format(name_ja=committee.name_ja, num=meeting_num)
        task_id = nb.generate_report(notebook_id, prompt, language="ja", fmt="custom")
        update_meeting(meeting_row, db_path=db_path, state="generating", report_task_id=task_id)
        if not nb.wait_artifact(notebook_id, task_id):
            return "generating"  # leave for resume; do NOT delete the notebook

        out_md = work / "briefing.md"
        if not nb.download_report(notebook_id, task_id, out_md):
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
    except nb.NotebookLMRateLimitError:
        # Transient, account-wide limit — not a bad meeting. Don't burn this
        # meeting's retry budget or leak its ephemeral notebook: delete it and
        # reset to 'detected' so a later run reprocesses cleanly, then bubble up
        # so the whole run stops (continuing would only burn the next meetings).
        logger.warning("summarize_meeting %s 第%d回 hit a NotebookLM rate limit — deferring",
                       committee.key, meeting_num)
        if notebook_id:
            try:
                nb.delete_notebook(notebook_id)
            except nb.NotebookLMError:
                pass
        # Also clear any quality_flag from an earlier failed attempt (e.g. a stale
        # 'no_sources' from before materials were enumerated) — this attempt got far
        # enough to have sources, so the old flag no longer describes the meeting.
        update_meeting(meeting_row, db_path=db_path, state="detected", notebook_id=None,
                       quality_flag=None)
        raise
    except nb.NotebookLMError as e:
        logger.error("summarize_meeting %s 第%d回 failed: %s", committee.key, meeting_num, e)
        update_meeting(meeting_row, db_path=db_path, state="error",
                       retry_count=_bump_retry(committee.key, meeting_num, db_path))
        return "error"
    finally:
        shutil.rmtree(work, ignore_errors=True)


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

    # source_count can be NULL after an interrupted run even though sources
    # landed; the synth_done meetings are the ground truth for what's in the
    # notebook.
    src_count = (state.source_count if state and state.source_count else len(folded))
    if src_count >= int(NOTEBOOKLM_SOURCE_CAP * 0.8):
        # Roll-up of the oldest summaries into one archive source is deferred; warn
        # so it can be handled before the cap is actually hit.
        logger.warning(
            "policy synthesis for %s near source cap (%d/%d) — archive roll-up needed",
            committee.key, src_count, NOTEBOOKLM_SOURCE_CAP,
        )

    work = _scratch() / committee.key / "synthesis"
    work.mkdir(parents=True, exist_ok=True)
    try:
        added_nums: list[int] = []
        for m in new_meetings:
            md = work / f"meeting_{m['meeting_num']:03d}.md"
            md.write_text(m["briefing_md"], encoding="utf-8")
            try:
                nb.add_source(nb_id, str(md))
            except nb.NotebookLMRateLimitError:
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
        db_path: str | None = None, states: tuple[str, ...] | None = None) -> dict:
    """Summarise pending meetings (gated on auth), then refresh each committee's synthesis.

    ``states`` lets ``resume`` target in-flight rows; default is all not-done work.
    Returns a summary dict.
    """
    nb.require_auth()

    # When no committees are named ("all"), restrict to tracked (enabled) ones so
    # untracking a committee removes it from the daily run. Explicit --committee
    # keys are an intentional override and run regardless of the enabled flag.
    work = pending_meetings(db_path=db_path, only_enabled=(not keys))
    if keys:
        work = [m for m in work if m["committee_key"] in keys]
    if states:
        work = [m for m in work if m["state"] in states]
    if max_per_run:
        work = work[:max_per_run]

    done = errored = 0
    rate_limited = False
    touched_committees: set[str] = set()
    for item in work:
        committee = committee_or_config(item["committee_key"], db_path=db_path)
        if committee is None:
            continue
        try:
            state = summarize_meeting(committee, item["meeting_num"], db_path=db_path)
        except nb.NotebookLMRateLimitError:
            logger.warning("NotebookLM rate limit reached — stopping run; remaining meetings stay pending")
            rate_limited = True
            break
        touched_committees.add(item["committee_key"])
        # Clear any queued dashboard request once the meeting has been processed.
        if state in ("done", "error"):
            clear_generation_request(item["committee_key"], item["meeting_num"], db_path=db_path)
        if state == "done":
            done += 1
        elif state == "error":
            errored += 1

    # Skip synthesis once rate-limited (it also generates a report and would just fail).
    synthesized = 0
    if not rate_limited:
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
            except nb.NotebookLMRateLimitError:
                logger.warning("NotebookLM rate limit during synthesis of %s — deferring", key)
                rate_limited = True
                break

    return {"processed": len(work), "done": done, "errored": errored,
            "synthesized": synthesized, "rate_limited": rate_limited}


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
