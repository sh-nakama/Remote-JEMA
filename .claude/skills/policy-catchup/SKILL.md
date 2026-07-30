---
name: policy-catchup
description: Run one NotebookLM policy-summarisation catch-up round for the RePower policy observer — pull the synced DB, summarise the newest pending meeting of each tracked committee (breadth-first, priority order) until the daily quota is hit, then push. Use after the user has run `notebooklm login`, when they ask to "run the policy catch-up", "advance the policy backfill", "summarise more policy meetings", or "summarise the <committee> policy meetings".
---

# Policy catch-up routine

Drives one **daily** catch-up round for the policy observer (`repower policy`):
pull the latest DB, summarise as many pending meetings as the NotebookLM quota
allows — breadth-first across the tracked committees (newest meeting of each first) —
then push the results back to Hugging Face.

## When to use
The user has just run `notebooklm login` (or confirms auth is fresh) and asks to
advance the policy backfill. This is **once per ~24h** — NotebookLM's
report-generation quota is a small daily cap (only a handful of generations/day on
the standard tier), so one round drains the day's quota and there's nothing more to
do until it resets. Do **not** `/loop` or schedule repeats; a second run the same
day only hits the spent quota.

## How to run the commands
- Run every command with the **Bash tool** (POSIX sh), not PowerShell — the blocks
  use `export` / `"$VAR"` syntax.
- **Each Bash invocation is a fresh shell; env does NOT persist between calls.** So
  set `NOTEBOOKLM_BIN` at the top of *every* block (shown below). `notebooklm` is on
  PATH, so this just pins the exact binary; the value is required for the literal
  `"$NOTEBOOKLM_BIN"` call in step 1, and harmless-but-good for the `policy run`
  path (which otherwise defaults to the on-PATH `notebooklm`).
- cwd is the repo root; invoke the CLI as `.venv/Scripts/python.exe -m repower.cli`.

## Scope
Default **breadth-first across all tracked committees** — `policy run --committee all`
summarises the **newest pending meeting of each committee first** (in priority order),
then each committee's second-newest, and so on. This keeps the latest meeting of every
tracked committee current before draining any one committee's back-catalogue — what a
small daily quota should buy. (`--committee all` defaults to breadth-first; pass
`--depth-first` to drain strictly in priority order instead, or name a single committee
to backfill just its history.)

Priority lives in the DB registry (`policy_committee.priority`, seeded from
`committees.py` and editable in the dashboard's *Manage tracked committees* panel) and
breaks ties between committees at the same depth — by default `system_review`,
`emissions_trading`, `chousei_jukyu` lead.

**Dashboard-queued meetings drain first.** Meetings the operator queued from the
Policy tab's "Summarise …" buttons (when auth was stale) are flagged
`gen_requested`; `pending_meetings` sorts those ahead of everything else, so a
plain `policy run` (or this skill) picks them up first, before the breadth order.
Disabled committees are skipped entirely.

`--max-per-run 8` is the **total** meetings for the run (the CLI default is 5, so pass
`8` explicitly). It's just an upper bound — the real limiter is the account-wide **daily
generation quota**, which normally stops the round after only a few meetings. With
breadth-first those few land on the newest meeting of the top committees.

## Steps

1. **Auth gate (fail fast).** Run as one self-contained block:
   ```bash
   export NOTEBOOKLM_BIN="C:/Users/SehunNakama/.local/bin/notebooklm.exe"
   "$NOTEBOOKLM_BIN" auth check --test --json
   ```
   Require `status == "ok"` AND `checks.token_fetch == true`. If not, **STOP** and
   ask the user to run `notebooklm login`, then re-invoke this skill. (`policy run`
   also self-gates and exits 2 with a clean message on stale auth, so this is a
   fast-fail convenience, not the only guard.)

2. **Pull the latest DB** so the round builds on current market+policy data:
   ```bash
   .venv/Scripts/python.exe -m repower.cli pull-hf
   ```

3. **Summarise breadth-first across all tracked committees** in one pass — the newest
   pending meeting of each committee first (priority order), spreading the day's quota
   across committees:
   ```bash
   export NOTEBOOKLM_BIN="C:/Users/SehunNakama/.local/bin/notebooklm.exe"
   .venv/Scripts/python.exe -m repower.cli policy run --committee all --breadth --max-per-run 8
   ```
   This is long-running (minutes per meeting); run it foreground (or background and
   wait for it to finish). It prints `processed=… done=… errored=… synthesized=…`.

   **Stop condition:** the run stops itself when it prints `WARNING: NotebookLM rate
   limit hit` (or reports `done=0` due to a rate limit) — that's the normal
   end-of-day stopping point, not a failure. If the user named specific committees,
   run one `policy run --committee <key> --max-per-run 8` per key instead, sequentially
   (a single committee runs depth-first through its backlog).

4. **Push if anything changed.** Sum the counters across the runs that executed. If
   `done > 0` OR `synthesized > 0` OR `errored > 0`, persist:
   ```bash
   .venv/Scripts/python.exe -m repower.cli push-hf
   ```
   Only skip the push if the round was a **pure no-op** (every counter 0 — i.e. the
   very first meeting rate-limited and nothing was written). Skipping a push that had
   real changes would lose them: the next round's `pull-hf` overwrites the local DB.

5. **Report.** Show a short summary — meetings summarised this round, whether the
   quota was hit, and the remaining backlog:
   ```bash
   .venv/Scripts/python.exe -m repower.cli policy status
   ```

## Guardrails
- Never fabricate summaries or bypass the auth gate.
- `done=0` with a rate-limit WARNING is **success-for-today**, not a failure — report
  it plainly and stop.
- The default `--committee all` pass is a single sequential process. If the user names
  multiple explicit `--committee` passes, run them **sequentially, never in parallel**
  (shared account + daily quota).
- **Do not `/loop` or schedule** this skill — strictly once per ~24h.
- `push-hf` overwrites the whole DB file. `pull-hf` first guards against clobbering
  the daily market cron, but the summarisation window is multi-minute; if the market
  cron might push during it, re-run `pull-hf` (and re-apply) before pushing, or run
  outside the cron window.
- Optional `policy digest --since-days 1` posts to the webhook (outward-facing) — run
  it only if the user wants the digest posted.
- If the user names committees, run one `policy run --committee <key> --max-per-run 8`
  per key, in the order given (`--committee` is single-valued; use `all` for the set).
