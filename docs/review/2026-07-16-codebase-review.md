# JEMA / RePower — Codebase & Workflow Review

**Date:** 2026-07-16 · **Branch:** `fable_review` (from `feat/ui-ux-redesign` @ `b353a94`)

## Methodology

Multi-agent review: 8 subsystem mappers → 6 dimension reviewers (correctness, security,
testing/CI, architecture, ops/automation, frontend) → 2 independent adversarial verifiers per
non-trivial finding (accuracy lens + impact lens) → completeness critic. 71 agents total; every
finding below marked **CONFIRMED** was independently upheld by both verifiers reading the actual
code. Ground truth established by the critic: **`pytest -q` → 143 passed, 0 failed** and
**`npm run build` (tsc -b + vite) → clean** — nothing below is "currently broken CI"; the two HIGH
correctness items are wrong *output*, not broken builds.

## Health summary

The codebase is in good shape for a 1–2 dev product: idempotent upserts everywhere, a genuinely
well-designed conditional-GET HTTP cache with WAF fallback, hermetic network-free tests (2,636
lines / 16 files), crash-recoverable policy summarisation state machine, and one exemplary
workflow (`web-deploy.yml`: least-privilege permissions, concurrency guard, DB fingerprinting).

The main weaknesses cluster in four themes:

1. **Two live wrong-output bugs** — the daily analysis mixes all 9 TSO areas into one "Tokyo"
   figure, and the web frontend computes date countdowns against a hardcoded July-2 anchor even
   for live data.
2. **Silent failure modes** — crons don't alert on failure, a failed analysis discards the day's
   scrape, and a broken HF token would deploy an empty public site daily with no signal.
3. **The frontend has no safety net** — no CI build/typecheck gate on PRs, no lint, no tests, no
   accessibility semantics.
4. **Production-path modules with zero test coverage** — `cli.py`, `hf_sync.py`, `web_api.py`
   HTTP layer, `notify/webhook.py`.

---

## System map (stock-take)

| Subsystem | Shape | Test coverage |
|---|---|---|
| **Scrapers & ingestion** (`src/repower/scrapers/`, `analysis/`) | 9 per-TSO scrapers on `BaseAreaScraper`, JEPX spot, EPRX→Parquet, fuels (yfinance), news RSS; all HTTP through `http_cache.conditional_get` (ETag/304 + curl_cffi WAF fallback) | Parsers/upserts well covered; `areas.py` URL templates, `analysis/features.py`, fetch orchestration untested |
| **Data layer** (`db.py`, `config.py`, `hf_sync.py`, `cli.py`) | SQLAlchemy ORM + additive SQLite migrations, lock-guarded engine memoization; HF Dataset mirror; Typer CLI (~25 commands) is the sole process entrypoint | db.py upserts/engine covered; **cli.py, hf_sync.py, config.py: zero tests** |
| **Policy observer** (`src/repower/policy/`, 11 modules) | Cheap no-auth detection decoupled from budget-gated NotebookLM summarisation; catalog/discovery; forward calendar; energy-board backup + cross-check | Broadly well covered (mocked); `digest.py` and the real `notebooklm` CLI contract untested |
| **Streamlit dashboard** (`src/repower/dashboard/`) | 5 views, D3-iframe chart components, Excel/PDF export, policy management UI; entries: `dashboard/app.py` (local), `space/app.py` (HF Space) | `read.py` aggregation covered; one Policy AppTest smoke test; chart components / exports untested |
| **Web export & API** (`export_web.py`, `web_api.py`, `notify/`) | Static JSON snapshots for the Pages deploy (reuses `read.py` loaders — single source of aggregation truth); stdlib localhost dev API with subprocess job runner; Discord/Slack webhook | Pure helpers covered; **DB-heavy exporters, HTTP routes, webhook.py: zero tests** |
| **Web frontend** (`web/`, Vite + React 18 + TS strict) | 4 screens ported from hi-fi exports; `.data.ts` fixtures as loading/fallback state, `.live.ts` adapters over snapshots or the dev API; self-hosted fonts; read-only prod enforced by dev-only `/api` proxy | **Zero automated tests, no lint, no PR build gate** |
| **CI/CD & automation** (8 workflows) | Daily scrape (05:30 JST), weekly + dispatch backfills, weekly policy run, monthly cross-check, Space sync, Pages deploy, PR gate (brand grep + ruff + pytest) | Workflows exercised only by running live |
| **Test suite** (`tests/`, 16 files) | Hermetic (lowest-level I/O boundary monkeypatched), idempotency treated as first-class invariant, real cp932 byte fixtures | See per-row gaps above |

**Data flow:** GH Actions crons do pull-HF → scrape/process → push-HF around one SQLite DB in a
private HF Dataset; `web-deploy.yml` turns it into static JSON + Vite build on GitHub Pages;
`sync-space.yml` mirrors the Streamlit app to an HF Docker Space.

---

## Findings — fix first (HIGH, all CONFIRMED)

### H1. Daily analysis mixes all 9 TSO areas into one "Tokyo" figure
`src/repower/analysis/features.py:31` — `_query_demand_supply` filters only by date, with no
`area` predicate, while the table now holds all 9 TSOs. Every daily `run-all` therefore computes
peak/min/avg demand, peak time, generation mix and renewable share across mashed-together areas,
persists it to `analyses`, posts it to the webhook as "Tokyo Power Market", and renders it in the
dashboard. Every other consumer (`dashboard/read.py:218,485,592`) filters by area — this is a
missed update from when multi-area scraping was added.
**Fix:** add an `area` parameter (default `tepco`) or aggregate deliberately.

### H2. Hardcoded "today" anchor (2026-07-02) applied to live data in the web app
`web/src/screens/PolicyDeepDive.tsx:21` (`dUntil`) and `web/src/screens/MarketData.tsx:95`
(`dateLabel`) compute countdowns/labels against `new Date(2026, 6, 2)`. Both are applied to the
**live** arrays when `pol.ready`/`useLive` is true (PolicyDeepDive.tsx:109-113, 237, 347, 419;
MarketData.tsx:240-266, 698), so every deployed "next meeting in Nd" / "あとN日" / peak-date label
is already ~2 weeks stale and drifts daily. `MarketOverview.tsx:135` already does it right
(`todayMid` from `new Date()`).
**Fix:** shared `now()` helper; keep the fixed anchor only inside the fixture-only path.

### H3. No keyboard or screen-reader semantics anywhere in the frontend
`web/src/lib/style.tsx:81-109` — 167 `onClick` handlers all on `<div>`/`<span>` via `Hoverable`;
zero `<button>`, `role=`, `aria-*`, or `tabIndex` in all of `web/src`. Primary nav, theme/lang
toggles, and modal close buttons are unreachable by keyboard (the ⌘K palette's arrow-key nav and
the global Escape handler are the only mitigations). Also `index.html` hardcodes `lang="ja"`
while the default UI language is English and `setLang` never updates `document.documentElement.lang`.
The design spec explicitly promises WCAG AA / accessible labels for a client-facing product.
**Fix:** give `Hoverable` an interactive mode rendering a real `<button>` (or `role="button"` +
`tabIndex=0` + Enter/Space), add `aria-label` to icon-only controls, sync the document lang.

### H4. Production pipeline modules have zero test coverage
`src/repower/cli.py` (sole entrypoint for every cron, ~25 commands — no CliRunner test),
`src/repower/hf_sync.py` (every workflow depends on it — no test file), `web_api.py`'s HTTP layer
(only `_build_policy_argv` is tested), `notify/webhook.py` (no reference in tests/). A broken
subcommand or sync regression merges green and surfaces only as a silent 05:30-JST production
failure.
**Fix:** CliRunner tests for exit-code paths, mocked HF push/pull test, HTTP-level route test,
webhook formatting test.

## Findings — plan next (MEDIUM, all CONFIRMED)

| # | Finding | Where | Fix |
|---|---|---|---|
| M1 | A failed ANALYZE/NOTIFY kills the whole `run-all` step → the day's *successful* scrape is never pushed to HF. `idxmax()` on an all-NaN column raises `ValueError` (guarded only by `.empty`); ANALYZE/NOTIFY are the only `run_all` sections without try/except; `daily.yml`'s push step is skipped on failure. Broken state then repeats daily. | `features.py:94,132`, `cli.py:193,225`, `daily.yml` | Guard idxmax/idxmin; wrap ANALYZE/NOTIFY like the policy sections |
| M2 | No CI gate for `web/`: no PR build/typecheck (a TS compile error merges cleanly, caught only at deploy), no eslint (three `eslint-disable` comments are inert — no linter installed), no tests | `ci.yml`, `web/package.json` | Add PR job: `npm ci && npm run build`; add eslint + react-hooks plugin; vitest for `lib/*.ts` |
| M3 | No `concurrency:` guard on the 5 HF-mutating crons; weekly-backfill (Sun 19:30 UTC, 90-min timeout) genuinely overlaps daily (20:30 UTC) — last push-hf silently clobbers the other. Market data self-heals in 24 h; lost policy rows delay summaries up to a week | `weekly-backfill.yml:12`, `daily.yml:5` | Shared `concurrency: group: hf-dataset` (no cancel-in-progress) on all five |
| M4 | `web-deploy.yml` silently deploys with **no DB** if the HF pull fails (`continue-on-error: true`, nothing checks it). Worse: the fingerprint becomes `nodb-<run_id>` (unique per run), so the skip-if-unchanged logic never triggers — a broken HF_TOKEN redeploys an empty public site *every day* with zero signal | `web-deploy.yml:68-70,78-85` | Alert on pull failure on scheduled runs, mirroring `policy.yml`'s auth-check pattern |
| M5 | Cron failures are silent: daily/backfill/weekly-backfill/sync-space have no failure alerting (daily.yml even declares `WEBHOOK_URL` in env but never uses it — dead wiring); `policy.yml` alerts only on stale auth, not on run failures; `policy-crosscheck.yml`'s push-hf has `continue-on-error: true`, reporting green when its entire purpose fails | `daily.yml:31`, `policy-crosscheck.yml:43-45` | `if: failure()` webhook step in every cron; drop the crosscheck `continue-on-error` |
| M6 | Brand-scrub gates are narrower than the rule: CI greps only `src space`; the pytest gate rglobs only `src/repower/**/*.py`. Neither covers `web/` (actively developed, deploys to a public site), `docs/`, or workflow YAML. `.design-sync/NOTES.md` documents a real 2026-07-03 leak into `docs/design/` caught only by a *manual* grep — the gap has already bitten once | `ci.yml:18`, `tests/test_policy.py:469` | Widen CI grep to `web docs .github` (exclude node_modules/dist); broaden the pytest rglob beyond `.py` |
| M7 | `summarize_meeting` never reuses `meeting_row.notebook_id` on resume — always creates a fresh NotebookLM notebook, orphaning the previous one (delete happens only on success/rate-limit paths; the timeout path deliberately keeps it). Each stalled-then-resumed meeting leaks one notebook + sources against the shared account quota, contradicting the module's own crash-recoverable promise | `policy/pipeline.py:172` | Reuse the stored notebook_id, or delete-before-recreate |
| M8 | `MarketDataScreen` (1,278 lines) and `MarketOverviewScreen` (914 lines) are single-function components mixing 4 sub-views, live/fixture merge logic and all JSX — the two files most likely to eat a bad merge | `MarketData.tsx:102`, `MarketOverview.tsx:105` | Extract per-view subcomponents next time either needs nontrivial change |

## Findings — hygiene backlog (LOW, confirmed unless noted)

**Correctness/robustness**
- `date.today()` (UTC) instead of `timeutil.today_jst()` decides "current" period at
  `area_base.py:274`, `eprx.py:51`, `jepx_spot.py:183,204`, `cli.py:101`, `schedule.py:211` —
  and (critic sweep) `export_web.py:129`, `app_main.py` ×3, `legacy.py` ×2. Self-healing ~1-day
  lag for scrapers, but `schedule.py`/`export_web.py` affect live output. Sweep once; consider a
  ruff/CI ban on bare `date.today()` outside `timeutil.py`.
- `db.py:155-184` — `PolicyCommittee` defines 7 attributes **twice** with conflicting defaults
  (merge damage from `b353a94`; second block silently wins). Delete the duplicate block.
- `hf_sync.py:76` — `pull_db_from_hf` downloads to `<dir>/repower.db` regardless of a custom
  `REPOWER_DB_PATH` filename (dormant landmine).
- `web_api.py:217` — wildcard CORS + zero auth on DB-mutating/subprocess endpoints; localhost dev
  helper by design, but any webpage in the same browser can drive it (drive-by-localhost). Argv
  allowlist and METI-only URL validation cap the blast radius. Cheap fix: pin ACAO to the Vite
  origin + shared-secret header. *(Related, verifier-split: the job subprocess has no timeout — a
  stalled NotebookLM job holds the single-flight lock until the server restarts.)*

**Frontend**
- Live-fetch failure is indistinguishable from "still loading" in 3 of 4 screens — fixtures render
  as if real, no error surfaced; the proper `useSnapshot`/`useManifest` hooks in `lib/data.ts:38`
  are dead code. Only PolicyDeepDive has a `stale` banner. Adopt or delete.
- Copy-pasted `chip`/`makeChip` have already drifted: flat-threshold `0.5%` vs `0.05%`
  (`MarketOverview.tsx:48` vs `MarketData.tsx:50`) — same metric renders flat on one screen,
  directional on the other. Extract to `lib/` with one constant (also `slotLabel`, `segBase`).
- `menus.tsx:609` — policy job state typed `Record<string, any>` across a 470-line
  `CommitteesManage`; `CapacityAuctions.tsx:89` — Y-axis max hardcoded to `16000`.

**Ops/tooling**
- `Dockerfile:17` — `COPY app.py app.py` references a root file that has *never existed*;
  `docker compose build` has been broken since day one (the HF Space path works because
  `sync-space.yml` assembles a deploy dir where `space/app.py` lands at root). Fix or delete
  docker-compose. Also: no `USER` (runs as root), and the layer ordering forces full dependency
  reinstall on any `src/` change.
- Actions pinned to mutable tags (`@v5`…) not SHAs, in workflows exporting `HF_TOKEN`/
  `NOTEBOOKLM_AUTH_JSON`; all GitHub-owned actions, so risk is modest — SHA-pin + Dependabot
  when convenient.
- 7 of 8 workflows omit a `permissions:` block (repo default verified `read` via API — no live
  escalation; add `contents: read` as defense-in-depth).
- `backfill.yml:39` — `${{ inputs.since }}`/`inputs.area` spliced directly into a `run:` script
  (shell-injection footgun, gated on repo-write dispatch rights). Route through `env:`.
- Ruff runs bare defaults (E4/E7/E9 + F only — no bugbear/imports/security rules); no mypy/pyright
  anywhere despite a heavily type-hinted codebase.

**Tests/debt (noted, unverified)**
- No `conftest.py`: `sync_committees(db_path=…)` boilerplate duplicated 30× across 6 files;
  METI/OCCTO HTML fixtures re-declared per file.
- `test_policy.py:480` hardcodes committee count `== 14` — fails on every registry change.
- Dead code: `legacy.py` `main()` + 4 helpers (~380-450 lines), `product_price_chart.py` (entire
  component), ~⅔ of `i18n.py`'s string table.
- `store.py`: identical session open/close boilerplate in ~32 of 34 functions — one
  `@contextmanager` would collapse it.
- `app_main.py:24` imports `AREA_NAMES` from the scraper layer for a 9-entry label dict — move to
  a neutral constants module.

## Strengths (keep doing these)

- **`http_cache.py`** — conditional-GET with explicit `invalidate()` on unparseable 200s
  (prevents permanent false-304s), shared consistently by every fetcher.
- **Idempotency as a tested invariant** — upserts keyed on real unique constraints everywhere;
  tests re-run them and assert no duplicates.
- **Hermetic test design** — monkeypatching at the lowest I/O boundary, real cp932 byte fixtures,
  behavioral assertions.
- **Single source of aggregation truth** — `export_web.py` and `web_api.py` are thin drivers over
  `read.py`; three consumers, one reducer implementation.
- **`web-deploy.yml`** — least-privilege permissions, concurrency guard, DB fingerprint skip;
  the template the other workflows should copy.
- **`policy.yml`'s auth-stale handling** — never fabricates, alerts on both channels, still
  pushes DB state with `if: always()`.
- **Policy store's `synth_done` flag** — correctly handles out-of-order backfill, avoiding the
  classic high-water-mark bug.
- **`download.ts`** — BOM for Excel CJK, RFC 5545 folding on code-point boundaries, deliberate
  date-only parsing.
- **No secrets in tracked history**; frontend has no dynamic HTML injection (only static SVG via
  the porting shim); `web_api`'s subprocess path is a strict argv allowlist, no `shell=True`.

## Residual blind spots (from the completeness critic)

- **`dashboard/components/*.py` (D3-iframe builders)** — three dimensions independently deferred
  reviewing how DB-derived strings are templated into iframe HTML/JS; nobody closed it. Worth one
  targeted injection-focused read.
- **`policy/committees.py` and `policy/discover.py`** — skipped by the correctness pass, not
  covered by any other dimension.
- `energy_board.py` module-level feed cache (`_feed_cache`/`_feed_ts`) mutated without a lock —
  benign under current single-flight usage; the unlocked-module-cache pattern wasn't checked as a
  category.
- No reviewer executed live scrapes; per-TSO URL/encoding assumptions are taken from code comments.
- Dependency audit (`pip-audit`/`npm audit`) not run; `huggingface-hub` pinned `==1.8.0` in
  `sync-space.yml` vs `>=0.23` in pyproject (skew unchecked).

## Prioritized action plan

| Priority | Batch | Items |
|---|---|---|
| **P0 — wrong output today** | ~half a day | H1 (area filter), H2 (date anchors) |
| **P1 — stop silent failures** | ~1 day | M1 (guard analyze/notify), M5 (failure webhooks + drop crosscheck continue-on-error), M4 (deploy pull alert), M3 (concurrency groups) |
| **P2 — safety nets** | ~1-2 days | M2 (web PR gate + eslint), M6 (widen brand gates), H4 (cli/hf_sync/webhook/web_api tests), ruff select + mypy |
| **P3 — debt & hardening** | opportunistic | M7 (notebook leak), H3 (a11y pass), M8 + frontend dedup/typing, dead-code removal, Docker fix-or-delete, SHA pinning + permissions blocks, `date.today()` sweep, conftest.py |
| **P4 — close blind spots** | 1 short pass | D3 component injection read, committees/discover read, dependency audit |
