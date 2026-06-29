"""Application configuration — reads .env and exposes typed settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
# DB_PATH: env var wins; otherwise data/repower.db relative to cwd
# (works for local dev, CI, and HF Spaces where cwd = /home/user/app)
_raw_db = os.getenv("REPOWER_DB_PATH", "data/repower.db")
DB_PATH = Path(_raw_db) if Path(_raw_db).is_absolute() else Path.cwd() / _raw_db
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# EPRX balancing-market data is stored as compressed Parquet (not SQLite) — the
# long format is ~200x smaller as columnar Parquet, keeping the HF-synced
# artifacts small. Both files live alongside the DB and are synced to HF.
EPRX_BALANCING_PARQUET = DB_PATH.parent / "eprx_balancing.parquet"
EPRX_TIELINE_PARQUET = DB_PATH.parent / "eprx_tieline.parquet"

# ── Hugging Face ───────────────────────────────────────────────────────────
HF_TOKEN: str | None = os.getenv("HF_TOKEN")
HF_DATASET_REPO: str = os.getenv("HF_DATASET_REPO", "")

# ── Webhooks ───────────────────────────────────────────────────────────────
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")

# ── LLM (deferred) ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MONTHLY_CAP_USD: float = float(os.getenv("ANTHROPIC_MONTHLY_CAP_USD", "5.0"))
