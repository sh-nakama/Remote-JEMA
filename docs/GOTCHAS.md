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
- **`allow_curl_fallback` now defaults to `True`.** It is a no-op unless the plain request
  returns 403/202 or raises, so leaving it on is free; leaving it *off* is how JEPX and EPRX
  ended up with no fallback at all. Opt out explicitly (with a comment) only if you genuinely
  want fast, unambiguous failure.
- **Cache-layer failures are typed** — `HttpCacheError` and its subclasses (`BlockedError`,
  `ChallengeNotClearedError`, `CircuitOpenError`, `UnexpectedStatusError`,
  `DeadlineExceededError`). Classify with `except`, never by string-matching a message.
  Genuine server faults (5xx surviving retry) still raise `httpx.HTTPStatusError`, which
  `jepx_spot` relies on — don't "unify" that away without checking its callers.
- **A host that blocks us repeatedly trips a per-host circuit breaker** (3 strikes, 5-minute
  cooldown). Subsequent calls raise `CircuitOpenError` *without* issuing a request. If a scrape
  reports far fewer requests than expected, check for an open circuit before suspecting the
  parser. One success closes it immediately.
- **METI's WAF is stateful, not rate-based — going slower makes it worse.** This is the single
  most counter-intuitive thing in the codebase, and it was measured, twice: at 1s spacing 4 of 43
  committees got through; after a 5-minute cooldown at 6s spacing, 1 of 12 did. Once the edge
  flags the client, waiting does not un-flag it; it clears on its own schedule. So:
  - `_MIN_HOST_INTERVAL` (2.0s) is a **politeness** choice only. Do not "tune" it hoping to
    appease a WAF, and do not lower it below 1s (there is a test pinning that).
  - The right response to a hostile host is to **stop asking**, not to ask more gently. Hence
    `_challenge_exhausted`: the 2+50s challenge ladder is walked at most once per host per
    healthy period, not once per URL. A sweep used to burn ~165s on three committees to learn
    one fact; it now spends ~55s once and every later URL on that host gets a single
    unbacked-off attempt (which still succeeds the moment the WAF relents).
  - Any success — including a plain 200 that never touched the fallback — clears the flag via
    `_circuit_record_success`.
- **`ChallengeNotClearedError.attempts` must reflect the ladder actually walked**, not
  `len(_CHALLENGE_RETRY_DELAYS) + 1`. It is snapshotted *before* the fallback runs, because the
  fallback marks the host exhausted on its way out — asking afterwards reports 1 for everyone.
  This number is surfaced in `last_error_detail` and `policy doctor`, so a constant here makes
  the diagnostics lie.
- **`circuit_open` is collateral, not a diagnosis.** One hostile host produces one root failure
  plus ~35 short-circuited committees. `policy doctor` groups those per host and excludes them
  from the "needs attention" count (`_COLLATERAL_KINDS`) — otherwise the two committees that are
  genuinely broken are invisible among the fallout. Keep that distinction when adding kinds.
- **Detection sweeps committees in rotation** (`tracked_committees(order="rotate")`), least
  recently *succeeded* first. Fixed registry order meant the small pre-WAF budget was always
  spent on the same alphabetically-early committees, permanently starving the rest. The
  tiebreak on `last_fetch_at` matters: every committee is stamped on every pass (including
  circuit_open collateral), so without it a permanently-failing committee would hold first place
  forever and merely relocate the starvation.
- **`_pace_host` claims its slot at the *intended send time* (`now + wait`), not `now`.** That
  is what makes concurrent callers queue rather than all read the same stale timestamp and fire
  together. Preserve this if you touch the pacer — the bug it prevents is invisible in
  single-threaded tests, and `web_api` runs catch-up on a background thread.
- **Anything issuing its own requests outside `conditional_get` must still call `pace_host`.**
  The OCCTO `_exists` probes do; they run in tight loops against the most bot-sensitive hosts.
- **Fetching a *file* by hand loses the WAF clearance the index fetch just earned.** The
  curl_cffi session is cached per host precisely so a cookie bought once is replayed; a
  hand-rolled `httpx`/`curl_cffi` call opens a fresh connection and re-earns it from zero — and
  gets no challenge ladder, no pacing and no circuit breaker either. Policy PDF downloads used
  to do this, so a 202 on a PDF was a one-shot give-up while the index page beside it patiently
  retried (~half of a catch-up round's meetings lost on a bad METI day). `_download_pdf` now
  goes through `conditional_get` with `force=True` — forced because we keep no persistent copy
  of the bytes, so a 304 would leave nothing to ingest.
- **A faked `time.sleep` in tests must also advance `time.monotonic`.** Otherwise the pacer sees
  no time pass between retries and piles up waits that don't exist in production — an artefact
  of the fake, not a real regression. `_fake_curl_cffi` installs a coherent clock; reuse it.
- **The `http_cache` table is pruned by the daily run** (`repower cache prune --days 90`), since
  it is synced to HF and otherwise grows forever. Eviction is safe — a missing entry costs one
  unconditional re-fetch — and anything still being requested is re-touched every run.
  `repower cache status` reports per-host entries/last-success/failures.
- **METI's block is an AWS WAF *challenge*, and no HTTP client can ever clear it.** Measured
  against the live host: a 202 carries `x-amzn-waf-action: challenge` and a page whose
  `challenge.js` runs a JavaScript proof-of-work to mint an `aws-waf-token` cookie. curl_cffi
  impersonates Chrome's TLS/HTTP2 fingerprint — which beats *fingerprint* rules — but has no JS
  engine, and once the edge has flagged the caller it is challenged exactly as often as plain
  httpx. So waiting is not a strategy: `_curl_get(js_challenge=True)` makes one attempt and
  stops instead of walking the 5s+15s+30s ladder for a cookie that will never arrive.
  `browser_clearance.fetch` (headless Chromium, optional `[browser]` extra) is the last resort
  and the only one that works; it runs `fetch()` *inside* the page so the request inherits the
  browser's TLS stack, cookies and referer, and returns base64 (PDFs are the common case).
- **The 202 body is empty unless you ask for HTML.** AWS WAF only serves the challenge
  interstitial to a request whose `Accept` admits `text/html`; with httpx's default `*/*` you
  get a 0-byte 202 and cannot see what you are being asked to do. `_BROWSER_HEADERS` fixes this
  — don't trim it back to a lone User-Agent.
- **The WAF escalates, and escalation outlives the burst.** Normal → challenge (202) → block
  (403), keyed on the client rather than the URL: at the 403 stage even real Chrome is refused.
  A tight burst of cache-busting requests reaches 403 in seconds and takes ~15 minutes to decay.
  Diagnose with single spaced requests, never a loop.
- **At the 403 stage the block is IP-wide, and no client shape escapes it.** Measured on one URL
  seconds apart: browser navigation, in-page `fetch()` and Playwright's request context all
  returned the same 403 block page. So the browser transport only helps at the *challenge*
  stage; once METI has escalated, the only remedy is time. Budget observed on a real backfill:
  ~5 requests get through, then 403 for ~5 minutes — which is why healing is incremental by
  nature and the fix is scheduling (small spaced runs, rotation order), not a better client.
- **Every plain request used to open a fresh client.** `_do_get` called module-level
  `httpx.get`, so each request paid a new TLS handshake and — worse — dropped its cookie jar,
  making any clearance cookie unusable by design. `_http_client(url)` now memoises one client
  per host; keep it that way.

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
- **A second `repower web-api` on the same port starts "successfully" and serves nothing.**
  `ThreadingHTTPServer` inherits `allow_reuse_address = 1`, and on Windows SO_REUSEADDR lets a
  second process bind a port that is already bound — it logs `listening on http://127.0.0.1:8787`
  while the *first* process keeps taking every connection. The symptom is a backend edit that
  appears to have no effect (a new route 404s, a new field is missing from `/api/policy/catalog`)
  even though the code is right there. Before debugging the code, check who actually owns the
  port — `Get-NetTCPConnection -LocalPort 8787 -State Listen` — and kill *all* the stale
  `repower web-api` processes, not just the newest.
- **Policy exports are three files, not two.** `policy/status.json` (per-meeting pipeline state
  for the Manage → Status table) is written alongside `committees.json` / `meetings.json`. It is
  the only one of the three that carries the raw lifecycle state (`downloading`/`ingesting`/
  `generating`) and the per-meeting failure message; `meetings.json` collapses those into
  `pending`. A read-only deployment shows stale meeting status until `repower export-web` reruns.
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

- **A meeting's PDFs are paced wider than a detection sweep's pages.** The 2s
  `_MIN_HOST_INTERVAL` floor is sized for one-page-per-host sweeps. A meeting is a dozen
  files from the *same* host, and METI's edge treats that as a burst: measured
  2026-08-18, it served six PDFs at 2s spacing and challenged the seventh ~12s in.
  `pipeline._batch_interval(n)` widens the gap with the batch size (≤4 files → 2s, 6 → 4s,
  12 → 10s, capped at 12s) via the `http_cache.host_pace()` context manager, which is
  thread-local and can only ever *slow* requests down. Note this is about **avoidance**
  (staying under the burst allowance); it does not contradict the recovery finding above —
  once flagged, waiting still does not un-flag you.
- **Every path that hands a meeting back to a later run must keep its staged PDFs.**
  There are three: `blocked` (host refused), `generating` (left for `resume`), and the
  `_HALTING` reset (rate limit / auth lapse / NotebookLM timeout, which sets the row back
  to `detected`). The halting one bit hardest — the downloads had all *succeeded*, and
  wiping them meant the retry re-ran the full burst against a WAF that tolerates a handful
  of requests, to re-fetch bytes already on disk. If you add another "come back to this
  later" return, set `keep_scratch = True` with it.
- **`downloaded` is a claim about disk, and the resume check reads the disk.** When staging
  is discarded, `store.forget_staged_materials` resets those rows to `detected` so the
  status table stops reporting documents that are gone. `ingested` rows are left — that
  did happen, and it stays true after the ephemeral notebook is deleted.
- **The ingested denominator is `docsPlanned`, not `docs`.** `docs` counts every PDF on the
  page; only `pipeline.INGESTABLE_KINDS` are ever ingested, so a complete meeting that also
  lists a 委員名簿 (`kind='other'`) would read as `12/13` and look broken. Report against
  what the pipeline *meant* to ingest.
- **Downloaded PDFs survive a blocked meeting; don't "clean up" that scratch dir.**
  `summarize_meeting` keeps `_scratch()/<key>/<num>/` when it returns `blocked`, and skips
  any file already on disk on the next attempt. Without it, all-or-nothing staging made a
  large meeting *unable to ever complete*: each attempt re-requested all 12 files, burned
  the same ~6-request allowance on bytes it already had, and failed at the same place. The
  dir is removed on `done` and on the permanent-error path. A meeting that stays blocked
  forever keeps its partial set (bounded by pending meetings × ~12 PDFs, in the OS temp dir).
- **Stop requesting at the first hostile response.** `_HOSTILE_FETCH_KINDS`
  (`challenge_unresolved` / `blocked_403` / `circuit_open`) abandons the rest of the batch.
  Those requests cannot succeed *and* each one is a strike towards the 3-strike breaker —
  in the observed failure, running the batch to the end took three strikes and opened the
  breaker for 300s, taking every other committee on that host down with it. Abandoning at
  the first takes one.
- **Source staging is all-or-nothing, deliberately.** It used to proceed whenever *at
  least one* document downloaded, and the observed result was a meeting where 11 of 12
  PDFs were blocked mid-download, the one that landed was `配布資料一覧` (the *list* of
  documents), and NotebookLM produced a fluent summary of a table of contents that was
  then marked `done` and folded into the committee synthesis. A partial briefing is
  worse than none because it reads complete. Any download or `add_source` shortfall now
  aborts the meeting: transient kinds → `blocked` (no retry burned, stays pending),
  anything else → `error` + a retry, so a permanently-404 handout still leaves the
  worklist after `MAX_RETRIES` instead of blocking its meeting forever.
- **`policy_material.status` / `nblm_source_id` are the record of what the briefing
  actually saw.** They were declared from the start and never written, so every document
  read `detected` forever and "did this summary see all the papers?" was unanswerable
  except by reading the summary's own prose. The pipeline writes
  `downloaded`/`error`/`ingested` per document; the Manage status table shows the
  `ingested/total` ratio. A `done` meeting showing `0/13` is a briefing to re-run.
- **The circuit breaker is per-process and in-memory** (`http_cache._circuit_open_until`).
  `policy run` is a subprocess, so every run starts with a closed breaker — the skip in
  `run()` only prevents *within-run* thrash, which is the case that hurt: the breaker
  opened on the third meeting and the rest of the backlog then failed instantly, one
  meeting per ~15 ms, marking everything blocked. Use the read-only `circuit_cooldown()`
  for checks; `_circuit_retry_after()` consumes the one probe allowed after a cooldown.
- `pipeline.summarize_meeting` **always creates a fresh NotebookLM notebook** — a
  timeout→resume cycle orphans the previous one (delete only happens on success/rate-limit
  paths) `(open — P3)`. Long stalls leak notebooks against the shared account quota.
- **A `create_notebook` timeout does not mean no notebook was created.** NotebookLM answers
  the RPC and makes one while the client gives up waiting, so a bare `raise` leaks an
  untracked notebook — the 2026-08-16 crash took the account from 13 to 14 notebooks with
  nothing in the DB pointing at the extra one, and `policy resume` found nothing to
  reconcile because the row was never written. `notebook.create_notebook` now looks the
  notebook up by title on timeout and adopts it. It adopts **only an empty match**: a create
  can only time out *before* any source is added, so a populated same-titled notebook belongs
  to some earlier attempt (typically one whose own `delete_notebook` also timed out) and
  reusing it would duplicate its sources. Any lookup failure — including the expired session
  that probably caused the timeout — means don't adopt, so the timeout stands.
  - Adoption only reclaims a notebook the *same* create retries into. Anything already leaked
    stays leaked, so `repower policy notebooks` diffs the account against the DB. It is
    **read-only by design**: an untracked notebook is usually a leak, but the shared account
    also holds notebooks a human made by hand, so nothing here may auto-delete.
  - **A rollover archive is untracked on purpose and must not be deleted.** The rollover keeps
    the full notebook and stores only `archive_watermark_meeting` — the archive's *id* is
    written nowhere, so it is indistinguishable from a leak by id alone. `policy notebooks`
    flags `<key> synthesis…` for any committee with a watermark set; those hold meetings below
    the watermark that the synthesis narrative no longer covers. (`chousei_jukyu` rolled over
    at 第120回 on 2026-08-17 and its 07-03 notebook is exactly this case.)
- **`require_auth` gates only the *start* of a run.** The browser cookie can lapse an hour in,
  and the CLI reports that as an ordinary exit-1 failure, not as an auth error — so
  `notebook._AUTH_MARKERS` sniffs stderr and raises `NotebookLMAuthError`. Without it every
  remaining meeting is charged a `retry_count` for what is really one dead session.
- **Rate limit, lapsed session and timeout are one category (`pipeline._HALTING`), not three.**
  All are properties of the *account*, so the next meeting would fail identically; `run` stops
  the round and names the cause in the summary's `stopped_early`
  (`rate_limited` | `auth_expired` | `timed_out`), and `summarize_meeting` resets the row to
  `detected` without burning a retry. Before this, a mid-run `NotebookLMTimeout` out of
  `_rollover_synthesis`'s `create_notebook` was uncaught and killed the process with a
  traceback (exit 1), losing the round's summary. `rate_limited` is kept in the summary dict
  purely for callers that predate `stopped_early` — new code should read `stopped_early`, and
  **any new NotebookLM error class that is account-wide belongs in `_HALTING`**, or it will
  quietly burn the whole worklist's retry budget one meeting at a time.
- **A full synthesis notebook rolls over to a new one, it does not compact.** At
  `NOTEBOOKLM_SOURCE_CAP` the committee's synthesis continues in a fresh notebook titled
  `<key> synthesis (第N回〜)`; the full one is left intact and `archive_watermark_meeting` records
  the last meeting it covers. So the NotebookLM-generated *synthesis narrative* only spans
  meetings above the watermark — the running document is regenerated from the DB's briefings and
  stays complete, so don't "fix" a narrower narrative by re-adding old sources.
- **The live notebook's size is derived from `synth_done` meetings above the watermark**, not
  from `source_count` — that column is a cached mirror an interrupted run can leave NULL or
  stale, and after a rollover the raw `synth_done` set spans every notebook the committee ever
  used.
- **Only *permanent* download failures burn a meeting's retry budget.** When no source PDF can
  be staged, `summarize_meeting` splits the verdict by `FETCH_KINDS`: a host-hostility kind
  (`_TRANSIENT_FETCH_KINDS` — circuit_open, challenge_unresolved, blocked_403, …) sets
  `quality_flag='download_blocked'` and leaves `retry_count` alone, so the meeting is retried on
  a calm day; anything else sets `'download_failed'` and bumps `retry_count`, so a genuinely
  dead meeting leaves the worklist after `MAX_RETRIES`. A *mixed* outcome counts as blocked —
  one transient kind is enough to make "these documents are gone" the wrong conclusion.
- **`--max-per-run` counts NotebookLM attempts, not meetings tried.** `summarize_meeting`
  returns `'blocked'` (DB state still `error`) when the host stopped it before anything reached
  NotebookLM, and `run` doesn't charge those against the budget — otherwise a bad METI day
  silently halves the round. A round still stops after `_MAX_BLOCKED_ATTEMPTS` blocked meetings
  so a host-wide outage can't walk the whole backlog; that bound is logged when hit.
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
- **A 304 index used to make dateless committees permanently un-repairable.** Dates live in the
  index body, so once an index settles and reliably 304s, `detect` never sees a body again.
  `detect` now re-requests the index with `force=True` when — and only when — that committee still
  has dateless meetings, so the cost is bounded by the shrinking set that actually needs repair
  rather than by the committee count. Don't "optimise" that forced re-fetch away.
- **`enabled` (tracked) does not gate detection — only summarisation.** Untracking a committee
  leaves it in the detect/backfill crawl by design, so a newly-discovered committee's meetings get
  recorded before anyone tracks it (`_select_committees` passes `include_disabled=True`). To stop
  *fetching* a concluded committee, mark it **`archived`** (`repower policy archive <key>`, or the
  archive-box toggle in the Manage modal). Archived committees are skipped by all three passes —
  detect, `backfill_dates`, `backfill_materials` — which is the only way to stop a dead committee
  burning the daily WAF budget on every run. `denryoku_jukyu` / `denryoku_kaikaku` are the
  motivating cases: closed, all-dateless, and re-crawled forever for nothing.
  - `archived` is deliberately **orthogonal to `enabled`**: a committee can stay tracked (so its
    already-detected meetings still summarise) while archived (so nothing new is fetched). Don't
    collapse the two flags, and don't infer archiving from meeting dates — the motivating
    committees have *no* dates, and `emsc_system` is dormant yet legitimately enabled.
  - Naming a committee explicitly (`--committee <key>`) **overrides the skip**, so a one-off
    re-crawl works without un-archiving.
  - Archiving only stops *fetching*: rows, meetings and materials are kept and still render in the
    Deep Dive. It is also a **DB-only change**, so it reaches CI via the HF dataset push, not git.
- **A failed fetch used to leave no trace anywhere** — `http_cache._store()` is only reached on
  200/304, so 403 / uncleared-202 / circuit-open / deadline all raise past it and never write a
  row. The only evidence was the console, and `web-api`'s in-process catch-up narrates straight
  to a terminal nobody keeps. Every failure path now records: `http_cache` gets
  `last_error_kind/at/detail`, `policy_committee` gets `last_fetch_*` + `consecutive_failures` +
  `last_ok_at`, and `policy_fetch_event` keeps the last 20 attempts per committee.
  `repower policy doctor` groups them by cause and prints the remedy.
  - `_store_error()` must **never** touch `etag`/`last_modified` (writing NULL on a 403 forces a
    full re-download of every PDF on the next success) or `last_checked` (`prune_cache` keys on
    it, so error writes would keep permanently dead URLs alive forever in an HF-synced table).
  - `set_committee_fetch_result` is called on **every** path including failures. Previously
    `set_committee_checked` was skipped on error, so a blocked committee's `last_checked` merely
    went stale — indistinguishable from "never scheduled".
- **`_exists()` is tri-state (`True`/`False`/`None`) and must stay that way.** It used to
  `return r.status_code == 200`, so a blocked probe was indistinguishable from a real 404.
  `probe_occto_latest` counted that toward `PROBE_GAP_TOLERANCE`, stopped early, and returned a
  **silently truncated** meeting list that `detect()` recorded as `status="ok"`. That is data
  loss, not just lost observability: a reported error gets retried, a missing meeting never does.
  An indeterminate probe now aborts the scan and returns `(None, "blocked_403")`.
- Committee `fetchStatus` in the web payload is **not** the same as the `error` rollup next to it:
  `error` counts meetings whose *summarisation* failed, `fetchStatus` says whether the
  committee's own pages could be reached. Both `build_policy_catalog` and `build_policy_snapshot`
  have their own SELECTs — adding a column to one silently omits it from the other.

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
- **Patch the lowest primitive, not a convenience wrapper.** `scraper._fetch` is now a thin
  wrapper over `_fetch_ex`; a test still monkeypatching `_fetch` silently does **real network
  I/O** and passes on a live 304 instead of failing loudly. Patch `_fetch_ex` — it covers both
  seams. The same hazard appears whenever a patched hot path grows a new inner function.
- The CLI reconfigures `stdout`/`stderr` to UTF-8 at import (`cli.py`). Without it the `═`
  banners, Japanese committee names and em dashes raise `UnicodeEncodeError` on a Japanese
  Windows console (cp932) *mid-command*, which reads as a crash in the scrape rather than in
  the printing.
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
