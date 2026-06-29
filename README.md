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

Examples:

```bash
repower run-all
repower backfill --since 2024-04 --area all
```

## Running the dashboard locally

```bash
streamlit run dashboard/app.py
```

The dashboard has four top-level tabs:

- **Wholesale** — a 9-area grid; per area, the left column shows demand + a
  stacked generation mix and the right column shows the JEPX spot price.
- **Balancing** — a 9-area grid per selected EPRX product; left column shows
  procurement / contracted / unprocured volume, right column shows the clearing
  price (max/avg/min), plus a full-width interconnector (DCM/DAM) panel.
- **Drivers** — fuel/commodity prices and JEPX-vs-Brent correlation.
- **Analyses** — daily analysis history.

Both market tabs support switchable aggregation (Native / Daily / Weekly /
Monthly, default Daily), a Period-comparison view (Period A vs B, per-area
deltas), and Excel/PDF export.

## CI workflows

- **`daily.yml`** — scheduled run of the full pipeline (scrape → analyze →
  notify) at 05:30 JST (20:30 UTC). Pulls the DB from Hugging Face, runs
  `run-all`, then pushes the updated DB back.
- **`backfill.yml`** — manual (`workflow_dispatch`) historical backfill with
  `since` and `area` inputs.
- **`sync-space.yml`** — on push to `main` (code/config paths), uploads the
  Space deployment (`space/`, `src/`, `Dockerfile`, `pyproject.toml`) to the
  Hugging Face Space.
