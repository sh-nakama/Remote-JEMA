---
name: policy-catchup
description: Run one NotebookLM policy-summarisation catch-up round for the RePower policy observer — pull the synced DB, summarise pending committee meetings (priority committees, newest-first, until the daily quota is hit), then push. Use after the user has run `notebooklm login`, when they ask to "run the policy catch-up", "advance the policy backfill", "summarise more policy meetings", or "summarise the <committee> policy meetings".
---

# Policy catch-up routine

Drives one **daily** catch-up round for the policy observer (`repower policy`):
pull the latest DB, summarise as many pending meetings as the NotebookLM quota
allows for the priority committees, then push the results back to Hugging Face.

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
Default **priority committees, newest-first** (override if the user names others):
1. `emissions_trading`
2. `system_review`
3. `chousei_jukyu`

`--max-per-run 8` per committee (the CLI default is 5, so pass `8` explicitly). This
is just an upper bound per process — the real limiter is the account-wide **daily
generation quota**, which normally stops the round after only a few meetings (often
within committee #1). `--committee` is **single-valued**: one `policy run` per key
(use `all` for every committee).

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

3. **Summarise the priority committees ONE AT A TIME, sequentially** — never
   concurrently (they share one NotebookLM account and one daily quota). Run each as
   its own Bash invocation and read its summary line before deciding to continue:
   ```bash
   export NOTEBOOKLM_BIN="C:/Users/SehunNakama/.local/bin/notebooklm.exe"
   .venv/Scripts/python.exe -m repower.cli policy run --committee emissions_trading --max-per-run 8
   ```
   then `system_review`, then `chousei_jukyu` (same pattern). These are long-running
   (minutes per meeting); run them foreground (or background and wait for each to
   finish before the next). Each prints `processed=… done=… errored=… synthesized=…`.

   **Stop condition:** if a run prints `WARNING: NotebookLM rate limit hit` (or
   reports `done=0` due to a rate limit), **STOP — do not launch the remaining
   committees this session.** They would only re-hit the same account-wide cap and
   burn work (notebook create/upload/delete churn). A rate limit is the normal
   end-of-day stopping point, not a failure.

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
- Run committees **sequentially, never in parallel** (shared account + daily quota).
- **Do not `/loop` or schedule** this skill — strictly once per ~24h.
- `push-hf` overwrites the whole DB file. `pull-hf` first guards against clobbering
  the daily market cron, but the summarisation window is multi-minute; if the market
  cron might push during it, re-run `pull-hf` (and re-apply) before pushing, or run
  outside the cron window.
- Optional `policy digest --since-days 1` posts to the webhook (outward-facing) — run
  it only if the user wants the digest posted.
- If the user names committees, run one `policy run --committee <key> --max-per-run 8`
  per key, in the order given (`--committee` is single-valued; use `all` for the set).
