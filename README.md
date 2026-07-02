# RePower

A bot that scrapes Japanese power-market data and serves an interactive
[Streamlit](https://streamlit.io/) dashboard. It collects supply/demand from
all nine mainland transmission system operators (TSOs), JEPX day-ahead spot
prices (**wholesale market**), EPRX balancing-market bid results (**balancing
market**), fuel/FX futures, and energy news, stores everything in SQLite, and
visualizes both markets as a 9-area × 2-column grid (supply/demand left, price
right) with switchable aggregation, per-area period comparison, and exports.

## Data sources

- **TSO area supply/demand** — 30-minute CSVs from all nine mainland TSOs:
  Tokyo (TEPCO), Hokkaido (HEPCO), Tohoku, Chubu (Chuden), Hokuriku (Rikuden),
  Kansai, Chugoku (Energia), Shikoku (Yonden), and Kyushu (Kyuden). Both the
  20-column legacy and 22-column 2024+ standard layouts are handled.
- **JEPX day-ahead spot prices** (wholesale) — system price plus per-area prices
  for every region, parsed from the yearly `spot_YYYY.csv` files.
- **EPRX balancing-market bid results** (balancing) — per-product, per-area
  block-level procurement, contracted volume, bid/clearing counts, and clearing
  prices (max/avg/min), plus interconnector (tieline) capacity for the DCM and
  DAM markets. Downloaded from EPRX as per-fiscal-year ZIPs (CP932 CSVs),
  handling the 8-block→48-block and March-2026 combined-zone transitions.
- **Fuel / FX futures** — daily closes via [yfinance](https://github.com/ranaroussi/yfinance):
  Brent crude (`BZ=F`), Henry Hub natural gas (`NG=F`), and USD/JPY (`JPY=X`).
- **Energy news RSS** — METI, OCCTO, and a Google News JP query, keyword-filtered
  for power-market relevance.

## Architecture

```
Scrapers (BaseAreaScraper framework + JEPX/EPRX/fuels/news)
        │
        ▼
   SQLite (SQLAlchemy)
        │
        ├──► synced to a private Hugging Face Dataset (push-hf / pull-hf)
        │
        ▼
   Streamlit dashboard ──► Hugging Face Space (Docker SDK)
```

Per-region scrapers share a common `BaseAreaScraper` framework that auto-selects
the column layout from the CSV shape. All sources upsert into a SQLite database
via SQLAlchemy. The database is synced to a private Hugging Face Dataset, and the
Streamlit dashboard is deployed to a Hugging Face Space using the Docker SDK
(port 7860). A daily GitHub Actions cron runs the full pipeline.

> Note: an LLM/narrative analysis layer is scaffolded in the schema but is
> deferred and not yet wired up.

## Setup

Requires Python >= 3.11.

```bash
pip install -e ".[dev]"
cp .env.example .env
# then fill in:
#   WEBHOOK_URL        notification webhook (e.g. Discord)
#   HF_TOKEN           Hugging Face access token
#   HF_DATASET_REPO    e.g. your-username/repower-data
```

## CLI usage

Installed as the `repower` console script (equivalently `python -m repower.cli`).

| Command | Description |
| --- | --- |
| `scrape` | Scrape recent TSO area data plus market sources. Options: `--months-back`, `--area`, `--skip-jepx`, `--skip-fuels`, `--skip-news`, `--skip-eprx`, `--jepx-year`, `--fuel-days`. |
| `backfill` | One-shot idempotent historical backfill from `--since` to today. Options: `--since YYYY-MM` (default `2024-04`), `--area`, `--jepx-since` (default `2024`, `0` to skip), `--eprx-since` (earliest JFY for EPRX balancing, default `2025`, `0` to skip). |
| `analyze` | Compute analysis features for a date. Option: `--target YYYY-MM-DD` (default: yesterday). |
| `notify` | Post the analysis digest to the webhook. Options: `--target`, `--dry-run`. |
| `run-all` | Full pipeline: scrape → analyze → notify. Options: `--months-back` (default `2`), `--dry-run`. |
| `push-hf` | Push the local database to the Hugging Face Dataset. |
| `pull-hf` | Pull the database from the Hugging Face Dataset. |
| `init-db-cmd` | Initialize the database (create tables). |
| `policy detect` | Detect new committee meetings (**no NotebookLM auth**). Options: `--committee` (key or `all`), `--window` (enumerate materials for the newest N), `--dry-run`. |
| `policy run` | Summarise pending meetings via NotebookLM (**requires auth**). Options: `--committee`, `--max-per-run`. |
| `policy backfill` | Throttled historical backfill for one committee, newest-first (**requires auth**). Options: `--committee` (required), `--since-meeting N` (required), `--max-per-run`. |
| `policy resume` | Finish meetings left mid-flight after a partial failure (**requires auth**). |
| `policy status` | Per-committee state: enabled flag, priority, latest summarised meeting + pending counts (no auth). User-added committees are marked `*`. |
| `policy add` | Add/update a tracked committee. Options: `--key`, `--name-ja`, `--url`, `--source` (METI/OCCTO/EGC), `--name-en`, `--priority`. |
| `policy enable` / `policy disable` | Start/stop tracking a committee (kept in the DB; disabled committees are skipped by detect/run). |
| `policy digest` | Assemble + post a digest of recently summarised meetings. Options: `--since-days`, `--dry-run`. |

Examples:

```bash
repower run-all
repower backfill --since 2024-04 --area all
repower policy detect --committee all      # no auth — safe to run daily
repower policy run --committee emissions_trading --max-per-run 5   # needs `notebooklm login`
```

## Running the dashboard locally

```bash
streamlit run dashboard/app.py
```

The dashboard has five top-level tabs:

- **Wholesale** — a 9-area grid; per area, the left column shows demand + a
  stacked generation mix and the right column shows the JEPX spot price.
- **Balancing** — a 9-area grid per selected EPRX product; left column shows
  procurement / contracted / unprocured volume, right column shows the clearing
  price (max/avg/min), plus a full-width interconnector (DCM/DAM) panel.
- **Drivers** — fuel/commodity prices and JEPX-vs-Brent correlation.
- **Analyses** — daily analysis history.
- **Policy** — per-committee running documents + per-meeting briefings, plus a
  **Manage tracked committees** panel (see below).

Both market tabs support switchable aggregation (Native / Daily / Weekly /
Monthly, default Daily), a Period-comparison view (Period A vs B, per-area
deltas), and Excel/PDF export.

## Policy observer

Alongside the market data, the bot tracks Japanese energy-policy committees
(METI / OCCTO / EGC) — **14 out of the box, and extensible from the dashboard** —
detects new meetings, and uses Google **NotebookLM** to produce a detailed
Japanese briefing + a compact English digest per meeting, maintaining a
per-committee running document (`data/policy/<key>.md`, regenerated from the DB
and surfaced in the dashboard's **Policy** tab).

### Managing tracked committees (dashboard)

The Policy tab's **Manage tracked committees** panel is a DB-backed registry
(columns on `policy_committee`) that overlays the code config, so it can be
edited without a code change and rides the Hugging Face sync:

- **Enable / disable** any committee and set its summarisation **priority** — a
  disabled committee is skipped by `policy detect` / `policy run`.
- **Discover new committees** — search energy committees across the METI / OCCTO
  / EGC index roots (Japanese name or English keyword, with an EN→JA keyword
  bridge) and add one in a click, or **add by URL** (the URL is probed to guess
  source/name and preview how many meetings would be tracked).
- **Summarise on command** — "Summarise latest meeting" (or a per-meeting
  button) runs the NotebookLM pipeline **in-process when `notebooklm login` is
  fresh**, otherwise it **queues** the meeting (`gen_requested`), which the next
  `repower policy run` / `/policy-catchup` drains first. Summaries are generated
  on the machine running the dashboard (the hosted Space uses the queue).

The same registry is manageable from the CLI (`policy add` / `enable` / `disable`
/ `status`).

The work is split by whether it needs NotebookLM authentication:

- **Detection is auth-free** and cheap (one conditional-GET per index, or a bounded
  OCCTO probe). It folds into the daily `run-all` pipeline, so the worklist of
  unsummarised meetings stays current with no cookies required.
- **Summarisation needs a live NotebookLM session.** Google rotates NotebookLM
  cookies and only an interactive browser login can mint a fresh session — no CI or
  HF compute can do it. So summarisation runs **weekly** (`policy.yml`), gated on a
  network-validated auth check; if auth is stale the job alerts and exits cleanly
  **without fabricating summaries**.

### Operator runbook — keeping summarisation alive

Summaries are produced only while the `NOTEBOOKLM_AUTH_JSON` secret holds a valid
session. Refresh it whenever the weekly job reports stale auth (roughly weekly):

```bash
# 1. Re-authenticate locally (opens a browser for Google OAuth).
notebooklm login
notebooklm auth check --test          # confirm status: ok AND token_fetch: true

# 2. Push the fresh session to the repo secret the weekly workflow reads.
#    bash / Git Bash:
gh secret set NOTEBOOKLM_AUTH_JSON < ~/.notebooklm/profiles/default/storage_state.json
#    PowerShell:
#    Get-Content -Raw "$env:USERPROFILE\.notebooklm\profiles\default\storage_state.json" | gh secret set NOTEBOOKLM_AUTH_JSON
```

`auth refresh` (server-side cookie keepalive) is tried automatically, but once Google
has hard-expired the session it cannot recover it — only `notebooklm login` can.

If the NotebookLM account is on a paid plan, set the source-cap tier so ingestion
and synthesis are sized correctly (default `standard` = 50 sources/notebook):

```bash
gh variable set NOTEBOOKLM_TIER --body plus   # standard | plus | pro | ultra
```

### Backfilling history (throttled)

`policy detect` records that every historical meeting exists, but summarisation is
deliberately throttled (cost + NotebookLM rate limits). To summarise a committee's
back-catalogue, backfill one committee at a time, newest-first, capping each pass:

```bash
# Summarise emissions_trading back to meeting #N, ~10 meetings per invocation.
repower policy backfill --committee emissions_trading --since-meeting 30 --max-per-run 10
```

Re-run until `policy status` shows the desired `LATEST`. The same effect happens
gradually through the weekly `policy run` (it drains the worklist newest-first at
`--max-per-run` per week). Each pass needs valid auth.

When a `policy run` spans multiple committees (e.g. `--committee all`), the worklist
is ordered by each committee's **priority** (set in `committees.py`) before newest-first,
so the day's NotebookLM quota is spent on the highest-priority committees first.
Current priority order: `system_review` → `emissions_trading` → `chousei_jukyu`, then
everything else.

## CI workflows

- **`daily.yml`** — scheduled run of the full pipeline (scrape → analyze →
  notify) at 05:30 JST (20:30 UTC). Pulls the DB from Hugging Face, runs
  `run-all --months-back 1` (current + previous month only), then pushes back.
- **`weekly-backfill.yml`** — scheduled deep re-validation (Mondays 04:30 JST)
  over a wider window (last ~6 months of TSO, ~2 years of JEPX, all EPRX years)
  to pick up late upstream revisions the daily window misses.
- **`backfill.yml`** — manual (`workflow_dispatch`) historical backfill with
  `since` and `area` inputs.
- **`policy.yml`** — weekly (Mondays 06:30 JST) + `workflow_dispatch` authenticated
  NotebookLM summarisation: pull DB, detect, gate on `auth check --test`, summarise
  pending meetings (`--committee`, `--max-per-run` inputs), post a digest, push DB.
  Skips cleanly with a webhook alert when `NOTEBOOKLM_AUTH_JSON` is stale (see the
  operator runbook above).
- **`sync-space.yml`** — on push to `main` (code/config paths), uploads the
  Space deployment (`space/`, `src/`, `Dockerfile`, `pyproject.toml`) to the
  Hugging Face Space.

### Incremental scraping & caching

Sources publish whole files (TSO: monthly CSVs; JEPX: a yearly CSV; EPRX:
fiscal-year ZIPs), so the smallest fetchable unit is a file, not a day. All
scrapers share a persistent **conditional-GET cache** (`http_cache` table,
synced to Hugging Face): ETag / Last-Modified validators are stored per URL, so
re-runs send `If-None-Match` / `If-Modified-Since` and the server returns **304
Not Modified** for unchanged files — which are then skipped (no download, no
re-parse). The result is that the daily job effectively re-fetches only the
files that actually changed (the current month/year). All writes are idempotent
upserts, so any overlap is deduplicated. The daily EPRX scrape covers only the
current fiscal year; the weekly job re-validates earlier years.
