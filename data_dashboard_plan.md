# Data Dashboard Reengineering Plan

Restyle the Streamlit dashboard into a **9-area × 2-column grid** (supply/demand left, price right) for **both the wholesale (JEPX) and balancing (EPRX) markets**, modeled on the layout in `Reference/dashboard_hh/` — but with **zero brand trace** (see the CLAUDE.md hard rule: reuse color *values*, drop brand *names*).

## Confirmed decisions

1. **Balancing data → DB.** Port the EPRX balancing-market pipeline into this project: new SQLAlchemy tables + a new scraper + HF sync + daily cron, mirroring the existing area/JEPX scrapers. Persisted & backfillable, not live-download only.
2. **Port D3 components, de-branded.** Reuse the reference's D3 chart components; strip every brand name/string. Color hex values may be reused.
3. **Navigation.** 9-area grid is the primary view. Separate top-level tabs **Wholesale** and **Balancing**, each with grid + period comparison + Excel/PDF export.
4. **Aggregation.** Default = aggregated **trend** (Daily), with a user switch: **Native / Daily / Weekly / Monthly**.
5. **Wholesale grid:** left = area demand + generation mix (stacked by fuel); right = JEPX per-area spot price. **Balancing grid:** left = volume (procurement/contracted/unprocured); right = clearing price (max/avg/min), per EPRX product.
6. **Legacy analytics (Q10, approved):** fold Trends / Compare / Areas-Compare into the new grid + aggregation + period-comparison; **keep Drivers and Analyses** as two extra top-level tabs.

---

## A. Data model

> **Update (storage):** EPRX balancing/tieline **data** is stored as compressed
> **Parquet** (`data/eprx_balancing.parquet`, `data/eprx_tieline.parquet`), not
> SQLite — the long format is ~200× smaller as columnar Parquet (≈7 MB vs ≈1.4 GB),
> keeping the HF-synced artifacts small. Only the conditional-GET cache
> (`EprxHttpCache`) stays in SQLite. Paths live in `repower.config`; the scraper
> merge-writes Parquet (last write wins on the logical key) and the read layer
> reads filtered slices via pyarrow predicate pushdown. The schema below describes
> the columns (originally modeled as SQLite tables).

Long format (one row per metric → new metrics need no migration). Matches existing idiom: autoincrement PK + named `UniqueConstraint`, `Date` date, `String(5)` "HH:MM" time, lowercase area slugs, `東京 → tepco`. Append after `FuelDaily`, before `NewsItem`. Add `Boolean` to the sqlalchemy import.

```python
class EprxBalancing(Base):            # per product, per area, per block, per metric
    __tablename__ = "eprx_balancing"
    id (PK), product_code (String8), product (String32), area (String16),
    date (Date), time (String5), block_num (Int), blocks_per_day (Int: 8|48),
    metric (String24), value (Float), jfy (Int), source_file (String128),
    ingested_at (DateTime)
    UniqueConstraint("product_code","area","date","time","metric", name="uq_eprx_bal")

class EprxTieline(Base):              # per market (DCM/DAM), per interconnector pair
    __tablename__ = "eprx_tieline"
    id (PK), market (String8), pair (String48), date (Date), time (String5),
    block_num (Int), blocks_per_day (Int), metric (String24), value (Float),
    is_combined (Boolean), jfy (Int), source_file (String128), ingested_at (DateTime)
    UniqueConstraint("market","pair","date","time","metric", name="uq_eprx_tie")

class EprxHttpCache(Base):            # conditional-GET state, shared via HF-synced DB
    __tablename__ = "eprx_http_cache"
    url (String, PK), etag (String), last_modified (String),
    last_status (Int), last_checked (DateTime)
```

- New tables → `create_all` makes them fresh, no `_migrate_*` cycle.
- `time` derived at write: `(block_num-1) × 24/blocks_per_day`. 48-block → 30-min; 8-block → 3-hour. **Never interpolate** 8→48.
- `missing_mw` (unprocured) derived on read (`demand − contracted`), never stored → correct after aggregation.
- Mar-14-2026 combined-zone tieline merge applied on read (raw stays lossless).
- Indexes on `(product, area, date)` and `(market, pair, date)` for read performance.

## B. Aggregation

Shared `aggregate(df, level)` helper, default **Daily**. Levels: Native / Daily / Weekly (ISO week start) / Monthly. Per-column reducers:

| Data | Reducer |
|---|---|
| MW flows (demand, generation mix, contracted, bid volume) | mean |
| avg price (wholesale `price`, balancing `price_avg`) | mean |
| `price_max` / `price_min` | max / min |
| counts (`bids_count`, `contracted_count`) | mean |
| tieline limits / reserved | max / mean |

`missing_mw` computed after aggregation. UI: `st.radio(horizontal=True)` (compat with `streamlit>=1.36`). Charts use `curveStepAfter` + parse `datetime`, so aggregated buckets render through the same chart code unchanged.

## C. File / module layout

**New — scraper:**
- `src/repower/scrapers/eprx.py` — fetch/parse/upsert/scrape for balancing + tieline. **httpx + sqlite_upsert**. Ports the reference loader's URL/JFY logic, CP932 parse, block-id regex, 8/48 handling, split-file precedence, JP→EN maps. DB-backed conditional GET via `EprxHttpCache`. Funcs: `scrape_eprx()`, `scrape_eprx_tieline()`, `scrape_eprx_range(jfy_since)`.

**Modified:**
- `src/repower/db.py` — new tables + `Boolean` import.
- `src/repower/cli.py` — `scrape` (+`--skip-eprx`), `backfill` (+`--eprx-since`, default 2025), `run_all` (add EPRX after `scrape_news()` — the cron path).
- `src/repower/config.py` — optional `EPRX_BASE` override.
- `pyproject.toml` — add `openpyxl`, `matplotlib`.
- `Dockerfile` — add `fonts-noto-cjk` for Japanese PDF text on Linux.
- `.github/workflows/ci.yml` — grep gate: fail if the banned brand word appears in `src/`, `space/`, `dashboard/` (case-insensitive).

**New — UI package (`src/repower/dashboard/` — converted from the old `dashboard.py` module):**
- `dashboard/__init__.py` — exposes `main()`; builds the tabbed app.
- `dashboard/legacy.py` — preserved helpers + Drivers/Analyses tab logic salvaged from old `dashboard.py`.
- `dashboard/theme.py` — de-branded theme: `METRIC_COLORS`, `METRIC_LABELS`, `PRODUCT_COLORS`, metric lists, `BRAND_*` color constants, `GLOBAL_CSS`. Single source of truth for hex (PDF export imports from here too).
- `dashboard/i18n.py` — ported EN/JA translations, neutral strings.
- `dashboard/read.py` — `load_wholesale_grid/load_balancing_grid/load_tieline` (SELECT → pivot → `aggregate()`), `@st.cache_data` with a cache buster.
- `dashboard/components/{volume,price,product_price,tieline}_chart.py` — ported D3 components.
- `dashboard/components/pdf_export.py`, `dashboard/components/excel_export.py`.

Entry points `dashboard/app.py` and `space/app.py` keep `from repower.dashboard import main`.

## D. Dashboard structure

```
Sidebar: Language (EN/JA) · Date range (default last 30d) · Area subset (default all 9)
         · [Balancing] Product selector (Primary…Composite)
Top tabs: [Wholesale] [Balancing] [Drivers] [Analyses]

Wholesale: Aggregation [Native|Daily|Weekly|Monthly] (default Daily)
           9×2 grid: LEFT demand+generation mix · RIGHT JEPX spot price
           Sub-view: Grid | Period comparison · Export: Excel/PDF
Balancing: Product + Aggregation
           9×2 grid: LEFT procurement/contracted/unprocured · RIGHT clearing price max/avg/min
           + Interconnector panel (DCM/DAM, full-width tieline chart)
           Sub-view + Export (same)
Drivers / Analyses: salvaged from legacy dashboard.
```

## E. De-brand rename map

Ported into `src/repower/dashboard/` (Reference stays gitignored, untouched). Values reused; names removed.

| Reference | Ported | Change |
|---|---|---|
| the reference theme module (brand-named file) | `dashboard/theme.py` | rename file |
| brand-prefixed color consts (7) | `dashboard/theme.py` | rename prefix → `BRAND_` (+ all `GLOBAL_CSS` refs) |
| brand docstrings / "⚡ … Japan" title / PDF footer "Source: EPRX \| …" | all | neutral text ("Source: EPRX") |
| chart literals `#1B2A4A`, `rgba(27,42,74,*)`, price band fill | `dashboard/components/*` | values via neutral constant |

CI grep gate enforces zero trace permanently. Never copy `Reference/__pycache__/*.pyc`.

## F. CLI + cron + HF + Docker

- `cli.py` 3 edits as above; `run_all` change makes the daily cron ingest EPRX → `daily.yml` needs no change.
- `backfill.yml` optional `eprx_since` input.
- `hf_sync`, `sync-space.yml`, Docker copy logic: no change (whole `src/` + whole DB ride along).

## G. Build order (each milestone independently testable)

1. DB models → `init_db` creates tables.
2. Parser (offline) → CP932 fixture test: 8-vs-48, `東京→tepco`, metric coverage, split precedence.
3. Upsert idempotency → upsert twice, count stable.
4. Fetch + scrape (network) → live pull; re-run hits 304, no dup growth.
5. CLI wiring → `scrape --skip-…`, `backfill`, `run-all` include EPRX.
6. Theme + D3 components (de-brand) → render standalone; grep gate green.
7. Read/aggregation layer → reducer + bucketing unit tests.
8. Dashboard restructure → two market tabs + grid + aggregation + product + language; keep Drivers/Analyses.
9. Comparison + export → Excel/PDF values match grid.
10. End-to-end → `run-all`, HF round-trip, Docker/Space reads EPRX tables.

## H. Top risks & mitigations

- **EPRX URL/format drift** → log + alert if `run-all` upserts 0 EPRX rows; don't swallow errors silently.
- **CP932 parse fragility** (P-line field index, 4-line header, T-line metric detection) → fixture tests for products + tieline; fail loudly on 0 metrics.
- **8↔48 & Mar-14 zone transition** → store `blocks_per_day`, never interpolate; merge zones on read; test no duplicate `(pair,datetime,metric)`.
- **Tokyo slug** → map `東京→tepco` at parse; assert area set ⊆ {hokkaido…kyushu, tepco}.
- **DB growth** → indexes, date-bounded reads, periodic VACUUM, watch HF push size.
- **Aggregation correctness** → enforce reducer table + unit tests.
- **Brand trace in git history** → CI grep gate; never copy `__pycache__`; review de-brand diff before first commit; keep `Reference/` gitignored.
- **CJK PDF fonts on Linux** → bundle Noto CJK in Docker; test PDF render in container.
- **`@st.cache_data` staleness after cron** → cache key on data date range + a refresh button.
