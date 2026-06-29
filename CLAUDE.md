# CLAUDE.md

Guidance for working in this repository (RePower — Japanese power-market scraper + Streamlit dashboard).

## Project rules

- **No "Aurora" anywhere.** This project must contain **no hint or trace of "Aurora"** — not in code, comments, file or module names, variable or constant names (including color-constant names), branding, UI strings, docs, or commit messages. When porting anything from `Reference/dashboard_hh/` (which is Aurora-branded), strip all Aurora branding and rename brand-named modules/constants to neutral names. Color **hex values** may be reused; Aurora-derived **names** must not. Examples of forbidden→neutral renames: `aurora_theme.py`→`theme.py`, `AURORA_NAVY`→a neutral name, "Aurora Energy Research" → remove.
- **`Reference/` is local-only.** The `Reference/` directory is read-only scaffolding for porting work. It is Aurora-branded, so it must **not** be committed to git (keep it gitignored). Use it as a source to adapt from, never as something shipped.

## Orientation

- `src/repower/` — package: `db.py` (SQLAlchemy models + engine), `scrapers/` (per-TSO area scrapers via `BaseAreaScraper`, plus JEPX spot, fuels), `cli.py` (console entry `repower`), `dashboard.py` (Streamlit app), `hf_sync.py` (Hugging Face dataset push/pull), `config.py` (`DB_PATH`).
- `dashboard/app.py` — local dev Streamlit entry. `space/app.py` — Hugging Face Space entry (Docker SDK, port 7860).
- Data: SQLite, synced to a private HF Dataset; refreshed by a daily GitHub Actions cron.
- Markets covered: **wholesale** (JEPX day-ahead spot, per area) and **balancing** (EPRX 需給調整市場). Supply/demand (per-TSO 30-min generation mix) underlies the wholesale view.

## Conventions

- Python ≥ 3.11. Install dev deps with `pip install -e ".[dev]"`.
- Run the dashboard: `streamlit run dashboard/app.py`.
- Tests live in `tests/`; CI runs lint + tests (see `.github/workflows/ci.yml`).
