# Gotchas — read before touching these areas

Running list of traps in this codebase. Each entry is a rule to follow or a sharp edge to
respect, distilled from the 2026-07 full review (`docs/review/2026-07-16-codebase-review.md`)
and subsequent fix work. **Add new entries as you find them; delete entries that stop being
true.** Items tagged `(open — P2/P3/P4)` are known debt from the review's action plan, not yet
fixed.

## Time & dates

- **Data is JST; CI runs in UTC.** The daily cron fires at 20:30 UTC = 05:30 JST *next day*, so
  `date.today()` is guaranteed to lag the JST calendar date during every run. Use
  `repower.timeutil.today_jst()/yesterday_jst()` for anything that decides "current"
  month/year/fiscal-year or filters future-vs-past. Known bypass sites `(open — P3)`:
  `scrapers/area_base.py:274`, `scrapers/eprx.py:51`, `scrapers/jepx_spot.py:183,204`,
  `cli.py:101`, `policy/schedule.py:211`, `dashboard/export_web.py:129`, `dashboard/app_main.py`
  ×3, `dashboard/legacy.py` ×2.
- **Japanese fiscal year starts in April** — EPRX files are per-JFY (`_current_jfy()`); a JFY
  boundary crossed near the UTC/JST gap delays picking up the new year's ZIP by one run.
- `NewsItem.published_at` (DateTime column) is compared against ISO **strings** in
  `analysis/features.py` — it only works because SQLite stores datetimes as ISO text. Don't
  change the stored datetime format without fixing that filter.

## Data model & queries

- **`demand_supply_30m` holds all 9 TSO areas.** Every query against it MUST filter
  `DemandSupply30m.area == …` (or aggregate across areas deliberately). This was missed once
  (`analysis/features.py`, fixed in `608901b`) and the daily digest silently mixed areas for
  weeks. `dashboard/read.py` shows the correct pattern.
- **EPRX data lives in Parquet, not SQLite** (`eprx_balancing.parquet` / `eprx_tieline.parquet`,
  merge-dedup last-write-wins). It syncs to HF alongside the DB — a workflow that pushes the DB
  but not the parquets desyncs them.
- `db.py::_migrate_add_area_column` rebuilds the table from a **hardcoded `old_cols` list** —
  adding a column to `DemandSupply30m` requires updating that list or pre-`area` DBs silently
  drop it on migration.
- `PolicyCommittee` in `db.py` defines 7 attributes **twice** (merge damage from `b353a94`;
  Python keeps the second block, `priority` default 100) `(open — P3)`. Edit the *second* block
  or, better, delete the duplicate first.
- `hf_sync.pull_db_from_hf` always downloads to `<dir>/repower.db` — a custom
  `REPOWER_DB_PATH` with a different **filename** uploads fine but never round-trips back
  `(open — P3)`.

## Scraping & HTTP

- **All fetches go through `scrapers/http_cache.conditional_get`** (ETag/Last-Modified persisted
  in the synced DB). If a cached 200 body turns out unparseable, you MUST call `invalidate()` —
  otherwise the bad body 304-skips forever. Existing scrapers do this; keep the pattern.
- **meti.go.jp is behind a WAF** (403/202 challenges for plain Python TLS). The
  httpx→curl_cffi Chrome-impersonation fallback is the workaround; it's duplicated in ~4 places
  (`http_cache`, `policy/pipeline._download_pdf`, `policy/scraper`, `policy/energy_board`,
  `policy/catalog`) — change all of them or centralize.
- Scrapers **fail soft by design**: per-URL/per-region errors are caught broadly and produce
  0 rows, not exceptions. A systematic outage looks like "0 rows upserted", not a red run —
  check row counts, not just exit codes. Kyushu/Chugoku URL patterns are reverse-engineered
  with hardcoded version suffixes and may silently go stale.
- Upserts are idempotent everywhere (`on_conflict_do_update/nothing` on the real unique
  constraints; Parquet merge-dedup for EPRX). Keep new writers idempotent — the crons re-run.

## The HF dataset sync (shared mutable state)

- The whole pipeline is **pull-HF → mutate → push-HF with last-write-wins and no locking**.
  The only guard is the shared GitHub Actions concurrency group — any new workflow that touches
  the dataset MUST declare `concurrency: {group: hf-dataset, cancel-in-progress: false, queue: max}`.
- **A failed pull + a successful push = dataset history clobbered with a fresh DB.** That's why
  scheduled runs use `continue-on-error: ${{ github.event_name != 'schedule' }}` on pull-hf
  (fail hard on cron; manual dispatch keeps the bootstrap fallback). Preserve this pattern, and
  never give push-hf an unconditional `if: always()` without also checking the pull outcome
  (see `policy.yml`'s push condition).

## GitHub Actions semantics (learned the hard way)

- `steps.<id>.outcome` = result **before** `continue-on-error` masking; `conclusion` = after.
  A skipped step reports `skipped` for both. `policy.yml`'s push condition relies on its pull
  step's `continue-on-error` using the *identical* `github.event_name != 'schedule'` expression
  — keep them in sync.
- A step `if:` that doesn't call a status function gets an **implicit `success()`** prepended.
  `if: failure()` fires only on real (unmasked) failures — and NOT on cancelled runs, so a
  concurrency eviction is invisible to the alert steps.
- Default concurrency keeps **one pending run per group** and silently cancels the rest;
  `queue: max` (up to 100, FIFO) fixes that but is invalid combined with
  `cancel-in-progress: true`.
- Failure alerting convention: last step, `if: failure()`, `::error::` + curl POST
  `{"content": …}` to `$WEBHOOK_URL` guarded by `[ -n "$WEBHOOK_URL" ]`. Every cron has one —
  new workflows should too.
- `workflow_dispatch` string inputs spliced directly into `run:` blocks are shell-injectable
  (`backfill.yml` still does this) `(open — P3)` — pass through `env:` instead.

## Exported JSON & the web frontend

- **Snapshot JSON must be strict JSON.** Browsers' `res.json()` rejects literal `NaN`/`Infinity`
  — pandas NaN leaked into the wholesale exports once and silently broke live mode for the
  affected area. `export_web._write_json` sanitizes NaN/Inf→null (`allow_nan=False` backstop);
  route any new export through it, never through a bare `json.dumps`.
- **Every screen falls back to fixtures, and a failed live fetch looks identical to "still
  loading"** (only PolicyDeepDive surfaces a `stale` banner) `(open — P3)`. If a screen shows
  suspiciously smooth data, suspect a broken snapshot before suspecting the market. The unused
  `useSnapshot`/`useManifest` hooks in `lib/data.ts` are the intended error-aware replacement.
- **The fixtures carry a frozen "today" (2026-07-02).** Live data must never be dated/counted
  against it: `PolicyDeepDive.dUntil` takes an anchor that flips with `pol.ready`, and
  MarketData's peak label reads the snapshot's own datetimes (`LiveArea.dDt`). Static caption
  strings hardcoding that date still exist in `MarketData.tsx` (~lines 927, 1047, 1110, 1227,
  1269) `(open — P3)` — don't copy them into new live-wired UI.
- ***.live.ts arrays are newest-first** (index 0 = latest, via `rev()`); `windowLive`/
  `windowSupply` flip back to oldest-first for plotting. Check direction before indexing.
- **The tail of a supply export is padded with all-null rows.** The datetime grid runs to the
  end of the export window, but the TSO feed lags, so the newest rows have `area_demand_mw` and
  every fuel `null`. Two traps followed from that (both fixed, don't reintroduce):
  *(a)* the ingest helper `g()` coerces missing values to `0`, which drew a demand line flat
  along the axis — i.e. "demand fell to 0 MW for five days". `supDemand` is therefore read with
  `nn()` (NaN-preserving) and `windowSupply` drops rows with a non-finite demand. *(b)* anchoring
  the plotted window on `supDt[0]` anchored it on padding, pushing the real series off the right
  edge; use `latestT`/`latestPriceT`/`latestSupplyT`, which walk to the newest row that actually
  carries a value.
- **Never derive a chart's x-domain from the union of the selected series' extents.** Per-area
  coverage differs by weeks in the real export (one TSO's supply can lag a month), so a single
  stale area stretched the shared domain and squeezed *every* chart's line into a ~16% sliver —
  the bug in #22, which looked like "the range chip is ignored". The domain is now
  `[anchor − effectiveRangeDays, anchor]`: a 7D chip always draws exactly 7 days, and a short
  series stops early leaving honest whitespace plus a `Nd behind` badge.
- **A range chip is not always plottable at the selected granularity.** `Native` is capped by
  `LEVEL_WINDOW_DAYS["Native"] = 90` in `export_web.py` (mirrored client-side as
  `NATIVE_EXPORT_DAYS`), and `Weekly`/`Monthly` need a floor (28/120 d) or a `7D` window holds
  ≤1 aggregated bucket and every chart renders blank. `effectiveRangeDays` applies both; keep
  `rangeClampNote` in sync so the UI says why the window differs from the chip.
- **Draw series as gap-aware segments, not one polyline.** A single `<polyline>`/`<polygon>`
  bridges a multi-week hole with a straight run that reads as genuine flat data. Use
  `gapSegments()` (splits at >2.5× the median cadence, so it adapts to downsampling) with
  `segPoints`/`bandPoints` from `lib/chart.tsx`.
- **Guard every chart divisor.** Price scales use `span = hi - lo || 1`; recomputing
  `(v - lo) / (hi - lo)` inline in JSX bypassed that guard and emitted `cy="NaN"` whenever a
  window held only identical prices (easy to hit now that drag-zoom exists — JEPX prints ¥0.00
  in high-solar periods). Expose the scale from the section object instead; `ChartFrame` also
  suppresses a non-finite `dotY` as a backstop.
- **`ChartFrame` charts use `preserveAspectRatio="none"` with `width:100%;height:auto`**, so the
  on-screen height is `viewBoxHeight / 480 × renderedWidth` — the 480×320 expanded chart came
  out ~812 px tall at full width. Pass `cssHeight` to constrain it; the geometry is unaffected.
- **MarketOverview and MarketData duplicate helpers that have already drifted** (`chip` vs
  `makeChip`: flat threshold 0.5% vs 0.05%; also `slotLabel`, `segBase`, Gaussian `mk()`)
  `(open — P3)`. Change both copies or extract to `lib/` first.
- **No CI gate for `web/`** `(open — P2)`: PRs run neither `tsc -b` nor a build; the three
  `eslint-disable` comments are inert (no linter installed); zero frontend tests. Run
  `npm --prefix web run build` yourself before considering a web change done.
- No keyboard/ARIA semantics anywhere (`Hoverable` renders divs; 167 onClick handlers)
  `(open — P3)`. The ⌘K palette and global Escape are the only keyboard paths — don't break
  them, and prefer real `<button>`s in new UI.
- `web_api.py` is a **localhost dev helper only**: wildcard CORS, zero auth, DB-mutating +
  subprocess-launching endpoints, no job timeout `(open — P3)`. Never bind it beyond 127.0.0.1
  or reuse it as a "real" backend.
- **Capacity-market figures are curated by hand from OCCTO PDFs** (`dashboard/capacity_data.py`)
  — there is no machine-readable feed, so a new auction means re-reading the press release.
  `pdfplumber` is broken in this venv (`cryptography` `_rust` DLL); use PyMuPDF (`fitz`).
  Two traps in those PDFs: (a) the auction clears **per OCCTO area** and splits wherever an
  interconnector binds, so the number of distinct prices changes every year (1 in FY2024, 6 in
  FY2027) — never model it as a fixed Hokkaido/Kyushu pair; (b) `natl` is the **総平均単価 =
  約定総額（経過措置控除後）÷ 約定総容量**, *not* a clearing price, so it always sits below the
  zonal prices. Sanity-check any new year by confirming the per-area 約定容量 sum equals the
  published 約定総容量.
- **`screens/*.html` are frozen pre-implementation design exports, not a spec and not data.**
  The four top-level files are hi-fi Claude Design frames (inlined `dc-runtime`, `DCLogic`
  fixture blocks) that the React screens were ported from — nothing imports or builds them.
  Their numbers are *illustrative placeholders* and several are simply wrong:
  `capacity-auctions.html` invents Hokkaido/Kyushu clearing prices, dates every auction "Jul",
  scrambles real figures across the wrong years (`¥5,242` is FY2025 Hokkaido, `¥9,555` is
  FY2027 Tokyo), and asserts "Hokkaido & Kyushu cleared as separate zones since FY2027" when
  FY2027 actually split six ways. Treat divergence between a shipped screen and its `.html`
  ancestor as **expected**; never resync a screen to match one, and never copy a figure out of
  one. (They're also generated artifacts — hand-editing means patching a minified bundle.)

## Policy observer

- `pipeline.summarize_meeting` **always creates a fresh NotebookLM notebook** — a
  timeout→resume cycle orphans the previous one (delete only happens on success/rate-limit
  paths) `(open — P3)`. Long stalls leak notebooks against the shared account quota.
- The per-committee synthesis notebook approaches `NOTEBOOKLM_SOURCE_CAP` with **no roll-up
  implemented** — long-lived committees will eventually fail to synthesize `(open — P4)`.
- OCCTO meeting discovery is a **linear probe** (one request per meeting number, 1s delay) — a
  committee with `max_meeting` ≈ 150 means ~150 sequential requests on a cold cache.
- NotebookLM auth is a browser cookie (`NOTEBOOKLM_AUTH_JSON` secret) that goes stale and only
  a human `notebooklm login` can refresh; `policy.yml` alerts on staleness and must never
  fabricate summaries.
- `energy_board.py`'s module-level feed cache (`_feed_cache`/`_feed_ts`) is unlocked — fine
  under today's single-flight usage, unsafe if you add threads.
- EGC index tables list **non-public meetings** (`※非公開開催` / `※書面開催`) with an *empty
  materials column* — the main-commission page (`index_emsc.html`) is full of them. `parse_egc_index`
  keeps a row when it has materials **or** a parseable date, so these still register and don't leave a
  hole in the meeting-number frontier (a dropped `第613回` would make `known_latest` stall at 612 and
  hide the next public meeting). Archive-navigation rows list meeting *ranges* (`第1回～第25回`) and are
  skipped by the `第\d+回\s*[〜～~]` guard — don't relax it or those become phantom "meeting 1" rows.
- METI index pages carry footer/nav links like `/main/31.html` that match the `NNN.html`
  meeting-subpage shape. `parse_meti_meeting_urls`/`parse_meti_meeting_dates` only keep links whose
  path is under `/shingikai/`, or a stray `/main/31.html` registers as phantom **meeting 31** and
  hijacks `known_latest` (all real committee pages, incl. cross-dir joint meetings under a sibling
  `/shingikai/.../` committee, stay under `/shingikai/`). Meeting numbers use the *URL* file number,
  so a joint `第15回` linking to `.../suiso_seisaku/014.html` is recorded as 14 — expected, not a bug.
- **A meeting with no `meeting_date` renders as `検出 YYYY-MM-DD`** (the detection timestamp), not
  as the date it was held — `build_policy_snapshot` falls back to `updated_at`/`detected_at` and
  sets `dateReal: false`, which `PolicyDeepDive.tsx` labels `検出` / `detected`. So a "wrong date"
  report is really a *missing date*, never a display bug: check
  `SELECT meeting_num, meeting_date FROM policy_meeting WHERE committee_key=…` first.
- Meeting dates are recorded by **`detect`**, off the same index body it parses for meeting URLs
  (`Discovery.dates`) — METI/EGC indexes print the date right next to the link, so it costs
  nothing. `backfill_dates` is only the *repair* pass (OCCTO subpages, plus METI/EGC indexes that
  304'd or were WAF-blocked during detection). It has to stay that way: meti.go.jp answers a
  **202 WAF challenge** whose retry backoff (5→15→30 s) can cost minutes *per committee*, so a
  second full crawl over ~85 committees frequently doesn't finish in one run — which is how
  原子力小委員会 and ~15 other committees sat with **zero** dated meetings for weeks
  (fixed 2026-08-05). For the same reason `backfill_dates(only_missing=True)` must **skip a
  committee whose meetings are all dated before fetching anything** — it used to fetch first and
  filter after, spending the WAF budget on settled committees and starving the ones that needed it.

## Streamlit dashboard

- The `_cache_buster` args are **underscore-prefixed, so Streamlit excludes them from cache
  keys** — the inline comments claiming they key the cache are wrong. Refresh works only
  because the sidebar button calls `st.cache_data.clear()`; don't remove that explicit clear.
- `legacy.py`'s `main()` + 4 helpers (~380 lines) and `components/product_price_chart.py` are
  **dead code**; ~⅔ of `i18n.py`'s string table is unreferenced `(open — P3)`. Don't pattern-match
  new work off them.
- Chart components load D3 + Google Fonts from CDNs inside iframes — offline/dev-container runs
  render empty charts. Nobody has audited how DB-derived strings are templated into that iframe
  HTML `(open — P4)` — escape anything user/scraper-derived you add there.
- `capacity_data.py` is hand-curated — new OCCTO auction results require a code edit; tests
  check shape, not freshness.

## Tests & CI

- **CI green ≠ safe**: `cli.py` (every cron's entrypoint), `hf_sync.py`, `web_api.py`'s HTTP
  layer, and `notify/webhook.py` have zero test coverage `(open — P2)` — regressions there
  surface only as 05:30-JST production failures.
- The brand-scrub gates cover only `src space` (CI grep) and `src/repower/**/*.py` (pytest) —
  NOT `web/`, `docs/`, or workflow YAML `(open — P2)`. A docs leak already happened once
  (2026-07-03, caught by a manual grep — see `.design-sync/NOTES.md`). Until widened, grep the
  whole tree yourself before pushing anything ported from `Reference/`.
- `tests/test_policy.py:480` hardcodes the committee count (`== 14`) — every registry change
  breaks it with a bare count mismatch `(open — P3)`.
- There is **no conftest.py**; DB-setup boilerplate is duplicated ~30× across the policy test
  files `(open — P3)`. Tests are hermetic by monkeypatching the lowest-level I/O boundary
  (`http_cache._do_get`, `subprocess.run`) — keep new tests network-free the same way.
- `ruff` runs near-default rules (E4/E7/E9 + F only) and there is no type checker `(open — P2)`
  — a clean lint proves little.
- Local dev: use `.venv` (Python 3.12) — the PATH `python` is 3.9 without deps.

## Docker & deployment

- **`docker compose build` has been broken since day one**: the root `Dockerfile` COPYs an
  `app.py` that only exists once `sync-space.yml` assembles its deploy dir (where `space/app.py`
  lands at the root) `(open — P3)`. The Space deploy works; local compose does not. Also: no
  `USER` (runs as root) and the layer order re-installs deps on every `src/` change.
- `web-deploy.yml` fingerprints the pulled DB to skip identical scheduled rebuilds; a missing
  DB gets a per-run-unique `nodb-*` fingerprint (only reachable via push/dispatch bootstrap now).
- Actions are pinned to mutable tags (`@v5`), not SHAs, in secret-bearing workflows
  `(open — P3)`; `huggingface-hub` is `==1.8.0` in `sync-space.yml` but `>=0.23` in
  `pyproject.toml` — version skew between the two install paths is unchecked `(open — P4)`.
