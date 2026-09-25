# JEMA / RePower — Codebase Review (September 2026)

**Date:** 2026-09-25 · **Base:** `main` @ `4010511`, plus the uncommitted Deep Dive feed-sort
change on `feat/most-recent-view` · **Previous review:** [2026-07-16](2026-07-16-codebase-review.md)

Line references point at `4010511`; fixes made after the review move them. Progress is tracked
in the [Tracker](#tracker) at the end — update it in the same commit as each fix.

## Method and baseline

Seven parallel subsystem reviews (scrapers + HTTP, data layer + CLI + sync, policy observer,
web API + exports, Streamlit, React frontend, CI + Docker + tests), then every finding below
re-verified by reading the code. About a dozen sub-review claims did not survive verification;
they are listed under [Checked and not a problem](#checked-and-not-a-problem) so nobody fixes them.

| Check | Result |
|---|---|
| `pytest -q` | 346 passed |
| `ruff check src tests` | clean (rules E, F, I, B, UP) |
| `npx tsc -b` (web) | clean, including the uncommitted Deep Dive change |
| `mypy src/repower` | does not start under the configured `python_version = "3.11"` (numpy stubs use PEP 695 `type`); 133 errors with `--python-version 3.12` |
| `npm audit` (web) | 4 high, 2 moderate — all dev tooling (Vite, esbuild, PostCSS, nanoid, browserslist) |

## Progress since the July review

**Fixed:** per-area analysis (H1), live-data date anchors (H2), guarded analyze/notify in
`run-all` (M1), `hf-dataset` concurrency group with `queue: max` (M3), hard-failing scheduled
deploy pull (M4), `if: failure()` webhooks on every cron and no `continue-on-error` on the
cross-check push (M5), NotebookLM notebook reuse leak (M7), Docker (multi-stage, non-root,
dependency layer first), the JST `date.today()` sweep, pinned CORS origins + optional
`REPOWER_API_TOKEN` + job timeouts, `session_scope` in the policy store, locked energy-board feed
cache, D3 iframe escaping (`js_json` + tests), one shared chip threshold (`CHIP_FLAT_PCT`),
wider ruff rules, `huggingface-hub` range aligned with `sync-space.yml`.

**Partially fixed:** keyboard access (H3: `Hoverable` now has `role="button"`, `tabIndex` and
Enter/Space, and `document.documentElement.lang` follows the UI language, but 66 raw `onClick`
spans/divs bypass it); web-api hardening (see 6); fixture fallback (freshness badges added, but
fixtures still render on failure — see F1).

**Still open:** CI gate for `web/` (M2), brand check breadth (M6), very large screen components
(M8), tests for `cli.py` / `hf_sync.py` / `notify/webhook.py` / web-api routes (H4), dispatch
inputs spliced into shell, SHA-pinned actions and `permissions` blocks, a working type checker.

## P0 — data-loss paths

### 1. EPRX history can be silently overwritten on HF
`src/repower/hf_sync.py:92-95` treats *any* Parquet download error (5xx, timeout, rate limit) as
"not in repo yet" and logs it at INFO. The daily EPRX scrape then finds no local file, and
`_merge_parquet` (`src/repower/scrapers/eprx.py:396-403`) writes a new one holding only the
current fiscal year's rows; push-hf uploads it over the full history. The ETags for earlier
fiscal years live in the DB, which *did* pull, so those ZIPs return 304 from then on — the loss
is permanent until a forced backfill.
**Fix:** skip a Parquet only when the repo listing says it is absent; raise on every other error.

### 2. The Parquet write is not atomic
`src/repower/scrapers/eprx.py:403` writes in place. A crash or full disk mid-write leaves a
truncated file: every later merge fails (caught per file, so EPRX quietly stops ingesting) and
push-hf uploads the corrupt file.
**Fix:** write to a temp file next to the target, then `os.replace`.

### 3. Manual runs can overwrite the dataset; `backfill.yml` always can
`backfill.yml` ignores pull failures unconditionally (`:42`) and always pushes (`:51`); it is
dispatch-only, so any failed pull pushes a fresh DB over history. `daily.yml:41/58`,
`weekly-backfill.yml:45/64`, `policy.yml:64/99` and `policy-crosscheck.yml:52/60` treat every
manual dispatch as a bootstrap, so a re-run during an HF outage does the same.
**Fix:** an explicit `bootstrap` boolean dispatch input (default false) is the only thing that
may tolerate a failed pull; the push is gated on a successful pull or that input.

### 4. push-hf uploads the raw SQLite file unchecked, as three commits
`src/repower/hf_sync.py:56` uploads the live file with `upload_file`, one commit per file.
`policy.yml` pushes under `always()` even after a timeout kill (a hot `-journal` is not
uploaded), and a local `repower push-hf` can overlap web-api writes. Separate commits also let
the DB (which holds the ETags) and the Parquets land out of step.
**Fix:** snapshot the DB with SQLite's backup API, `PRAGMA quick_check` the snapshot, and upload
the snapshot and both Parquets in one `create_commit`.

## P1 — security

### 5. The Vite dev server exposes the web-api to the local network
`web/vite.config.ts:23` sets `host: true` (all interfaces) and proxies `/api` with
`changeOrigin` (`:28`), so anyone on the same network can reach `http://<dev-ip>:5173/api/...`:
start NotebookLM runs (daily quota), full scrapes (METI WAF budget), untrack or archive
committees. This defeats the "never bind beyond 127.0.0.1" rule in `docs/GOTCHAS.md`. The
installed Vite 5.4.21 also has a Windows `server.fs.deny` bypass that `host: true` makes
reachable; the fix needs a Vite major.
**Fix:** default the host to `127.0.0.1` (opt in via env), generate an API token when `web-api`
starts and have the proxy add it, upgrade Vite and `@vitejs/plugin-react`.

### 6. The web-api can be driven from any page open in the browser
Pinned CORS only stops pages from *reading* responses. `_read_json`
(`src/repower/web_api.py:425`) parses any body regardless of `Content-Type`, and `_check_auth`
(`:437-441`) passes when no token is set (the default), so a `mode: 'no-cors'` text/plain POST
to `/api/policy/job` runs a job. There is no `Host` check, so DNS rebinding also gets read access.
**Fix:** require `Content-Type: application/json` on POST, reject `Origin` values outside the
allowlist, and allowlist `Host` (`127.0.0.1:<port>`, `localhost:<port>`).

### 7. The Streamlit Space ships the admin UI and an open fetch proxy
The Space runs the same `app_main` as local development, so any visitor can enable, disable,
re-prioritise or delete committees (`src/repower/dashboard/app_main.py:970`). Add-by-URL calls
`probe_url` (`:1024`), which only checks for `^https?://` (`src/repower/policy/discover.py:244`),
so the Space fetches any URL — internal addresses included — and echoes the page title back.
Severity depends on whether the Space is public, which was not confirmed.
**Fix:** hide the committee manager when `SPACE_ID` is set (HF sets it in Spaces) and restrict
`probe_url` to the METI / OCCTO / EGC hosts, as `parse_meti_committee_url` already does.

### 8. The public Pages site publishes raw pipeline error text
`src/repower/dashboard/export_web.py:800` writes `last_error` into `policy/status.json`. Those
messages embed the full `notebooklm` command line (local temp paths, including the Windows user
name) and uncapped stderr (`src/repower/policy/notebook.py:81`).
**Fix:** export only the error kind / quality flag in static builds; keep the raw text for the
local API.

### 9. Dispatch inputs are spliced into shell
Known for `backfill.yml:47`, but `policy.yml:81` does the same, and that job holds
`NOTEBOOKLM_AUTH_JSON` (a Google session) and `HF_TOKEN`.
**Fix:** pass inputs through `env:` and reference them as shell variables.

## P1 — reliability

### 10. The web-api leaks a headless Chromium per catch-up job
`browser_clearance._context()` (`src/repower/scrapers/browser_clearance.py:207`) keeps the
browser in thread-local state; the only cleanup is `atexit.register(close)` (`:230`), which runs
on the main thread and closes only *its* browser. Each catch-up runs on a new thread
(`src/repower/web_api.py:255`), so each one that mints a METI token orphans a Chromium and a
Playwright driver for the life of the server. Profile directories are keyed by thread ident
(`:124`) and Python reuses idents, so a later thread can hit a profile still locked by an
orphan; clearance then quietly degrades to `{}`.
**Fix:** close the thread's browser in a `finally` at the end of each job (and in any request
handler that can fetch), or own Playwright on one dedicated worker thread.

### 11. The Space pulls the DB once per visitor, not once per process
`space/app.py:12` keys the "cold start" pull on `st.session_state`, so every new browser session
re-pulls three files and may swap the DB under live readers.
**Fix:** a process-wide `@st.cache_resource` with a TTL.

### 12. Fail-soft scrapers plus no freshness gate means silent outages
A systematic TSO or JEPX break shows up as "0 rows" in a green run. The web UI already computes
48-hour staleness; the cron does not.
**Fix:** a `repower check-freshness --max-age 48h` step in `daily.yml` that exits non-zero, so
the existing failure webhook fires.

### 13. Scheduling gaps
`daily.yml` has no `timeout-minutes` (a hung run holds the shared `hf-dataset` queue for the
360-minute default). `web-deploy.yml:30` runs at a fixed 21:30 UTC and ships yesterday's data
if the daily run is late (Sundays it queues behind the weekly backfill); a `workflow_run` trigger
on daily completion avoids that. It also builds with Node 20 (`:120`), end-of-life since April 2026.

## The uncommitted Deep Dive change (`feat/most-recent-view`)

Type-checks, and the pagination/reset logic is sound. Three issues:

- **D1 — "RECENTLY HELD" is not reliable.** Meetings without a known date sort by `date`, which
  the exporter fills from `updated_at` (`src/repower/dashboard/export_web.py:888`); that column
  changes on every materials backfill, retry and reset, so old meetings healed during a catch-up
  jump to the top. Sort `dateReal === false` rows after dated ones
  (`web/src/screens/PolicyDeepDive.tsx:536`), and have the exporter fall back to `detected_at`
  (what the 検出 / "detected" label claims), converted to JST before slicing.
- **D2** — `feedList.map(mapFeed)` (`:588`) builds every row and then slices; slice first.
- **D3** — the new sort pills are plain `<span onClick>` (`:1123`), unreachable by keyboard;
  use `Hoverable`.

## P2 — frontend

- **F1 — demo fixtures can pass for real data.** MarketData switches its KPIs to synthetic
  fixtures if *any* selected area fails (`web/src/screens/MarketData.tsx:340`); several live
  hooks end in `.catch(() => {})`; PolicyDeepDive falls back to a fabricated
  "Last run 2026-07-02 … Summarised 3" line (`web/src/screens/PolicyDeepDive.tsx:141`). Limit
  fixtures to `import.meta.env.DEV` and render an explicit "unavailable" state in production.
- **F2 — a stale `web/vite.config.js` shadows the `.ts`.** `tsc -b` emits it
  (`tsconfig.node.json` is `composite` without `noEmit`) and Vite resolves `.js` before `.ts`,
  so `npm run dev` runs the last compiled copy. It is gitignored, so easy to miss. Align
  `tsconfig.node.json` with the current create-vite template (`noEmit`, build info under
  `node_modules/.tmp`).
- **F3 — date parsing is scattered:** about eight hand-rolled parsers with three conventions
  (fake-UTC JST wall clock, naive-UTC DB timestamps, date-only). They have produced bugs
  repeatedly (H2, the `updated_at` local-parse bug, D1). Consolidate into `web/src/lib/time.ts`
  with unit tests.
- **F4 — size and render cost.** `MarketData.tsx` is ~2,000 lines with one `useMemo`;
  `PolicyDeepDive.tsx` has 19 `useState` and no `useMemo`; `s()` is called ~440 times in
  MarketData alone (~1,150 across the screens) and re-parses each CSS string on every render
  without caching. 66 raw `onClick` spans/divs bypass the keyboard-accessible `Hoverable`.
- **F5 — scraped links are barely checked.** Material URLs are only required to end in `.pdf`
  (`src/repower/policy/scraper.py:285`), so a `javascript:…//x.pdf` href would reach
  `window.open` (`web/src/screens/PolicyDeepDive.tsx:648`) and Streamlit markdown links. Allow
  only `http(s)` at ingest and at render.

## P2 — tooling, tests, docs

- **T1 — `docs/GOTCHAS.md` has about a dozen stale "open" entries:** the date sweep (`:14`),
  the `PolicyCommittee` duplicate (`:36`), the `hf_sync` filename (`:39`), wildcard CORS / no
  job timeout (`:316`), the notebook leak (`:412`), the unlocked feed cache (`:476`), dead legacy
  code (`:556`), the unaudited iframes (`:559`), the ruff rules (`:586`) and broken Docker
  (`:592`); the "linear probe" bullet (`:471`) contradicts the OCCTO JSON section. `CLAUDE.md`
  sends every contributor there first, so a stale entry sends people after fixed problems. Sweep
  it; keep GOTCHAS for invariants and move open debt to issues.
- **T2 — type checking.** Point mypy at Python 3.12 (`pyproject.toml:43`; the runtime floor can
  stay 3.11) or exclude numpy. 98 of the 133 errors are mechanical: 39 matplotlib axes typing
  in `pdf_export.py`, 30 from legacy `Column()` models (move to `Mapped[]` / `mapped_column`),
  29 from BeautifulSoup attribute typing. Then add mypy to CI one clean module at a time.
- **T3 — CI for `web/`:** `npm ci && npm run build` on pull requests, ESLint with
  `react-hooks/exhaustive-deps` (the code relies on the `useDataNonce` dependency rule), vitest
  for `web/src/lib/`.
- **T4 — tests:** `hf_sync` pull/push behaviour (items 1 and 4), web-api Origin / Host /
  Content-Type guards (item 6), a CliRunner smoke test of `run-all --dry-run` with scrapers
  stubbed; a `conftest.py` for the repeated `sync_committees` setup; replace the hardcoded
  committee count (`tests/test_policy.py:1593`).
- **T5 — brand check breadth.** CI greps only `src space` (`.github/workflows/ci.yml:18`) and the
  pytest gate only `src/repower/**/*.py`. Scan everything `git ls-files` returns, allowlist
  `CLAUDE.md`, and obfuscate the needle so the gate itself carries no trace.
- **T6 — supply chain.** No Python lockfile (CI, Docker and the Space all install floating
  versions); add a constraints or lock file, Dependabot for pip / npm / actions, SHA-pinned
  actions, and `permissions: contents: read` (only `web-deploy.yml` has a block).
- **T7 — Space sync keeps deleted files.** `upload_folder` in `.github/workflows/sync-space.yml:52`
  has no `delete_patterns`, so files removed from the repo live on in the Space.
- **T8 — minor.** D3 loads from a floating CDN tag without SRI
  (`src/repower/dashboard/components/price_chart.py:67`); no SQLite `busy_timeout`
  (`src/repower/db.py:342`); webhook errors log the full URL (`src/repower/notify/webhook.py:130`
  — masked in CI, not locally).

## Strategic

- **S1 —** the Streamlit Space and the React Pages site overlap heavily but have different
  security models: React is read-only in production by construction, Streamlit is not. Pick a
  primary UI; if Streamlit stays for the Space, make that deployment read-only.

## Checked and not a problem

Sub-review claims that did not hold up — do not "fix" these:

- The energy-board feed cache is locked (module-level `_feed_lock`), and `policy/store.py`
  already uses a `session_scope` context manager.
- `summarize_meeting` never passes a missing meeting id (the row is recorded first); the
  stale-notebook leak (M7) is fixed.
- SQLAlchemy 2.x already sets `check_same_thread=False` for file-based SQLite.
- `fuels_futures` using UTC `date.today()` is correct: yfinance's `end` is exclusive, and at
  20:30 UTC the JST date would pull in the unfinished US session.
- `queue: max` is valid GitHub Actions syntax (up to 100 pending runs, FIFO).
- `dayTs` in the Deep Dive diff cannot misparse offsets: the exporter always emits 10-character dates.
- web-api subprocess argv can never contain `None`; the OCCTO `_exists` probe stops the scan on
  the first indeterminate result, so it cannot run for hours.

## Tracker

Status: **Open** · **Fixed** (with the branch it landed on) · **Partial**.

| # | Item | Priority | Status |
|---|---|---|---|
| 1 | Pull skips a Parquet only when the repo lacks it | P0 | Open |
| 2 | Atomic EPRX Parquet write | P0 | Open |
| 3 | Explicit `bootstrap` input gates pull tolerance and push | P0 | Open |
| 4 | push-hf uploads a checked snapshot in one commit | P0 | Open |
| 5 | Vite dev server bound to localhost; token via proxy; Vite upgrade | P1 | Open |
| 6 | web-api Content-Type / Origin / Host guards | P1 | Open |
| 7 | Read-only Streamlit Space; host-restricted `probe_url` | P1 | Open |
| 8 | No raw error text in the public export | P1 | Open |
| 9 | Dispatch inputs through `env:` | P1 | Open |
| 10 | Close per-thread browsers in web-api jobs | P1 | Open |
| 11 | Process-wide Space DB pull | P1 | Open |
| 12 | Freshness gate in the daily cron | P1 | Open |
| 13 | Daily timeout, `workflow_run` deploy, Node LTS | P1 | Open |
| D1–D3 | Deep Dive feed-sort fixes (on `feat/most-recent-view`) | P1 | Open |
| F1–F5 | Frontend items | P2 | Open |
| T1–T8 | Tooling, tests, docs items | P2 | Open |
| S1 | Primary UI decision | — | Open |
