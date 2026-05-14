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

# ── TEPCO ──────────────────────────────────────────────────────────────────
TEPCO_BASE_URL = os.getenv(
    "TEPCO_BASE_URL",
    "https://www.tepco.co.jp/forecast/html/images",
)

# ── JEPX ───────────────────────────────────────────────────────────────────
JEPX_BASE_URL = os.getenv(
    "JEPX_BASE_URL",
    "http://www.jepx.org/market/excel",
)

# ── Hugging Face ───────────────────────────────────────────────────────────
HF_TOKEN: str | None = os.getenv("HF_TOKEN")
HF_DATASET_REPO: str = os.getenv("HF_DATASET_REPO", "")

# ── Webhooks ───────────────────────────────────────────────────────────────
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")

# ── LLM (deferred) ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MONTHLY_CAP_USD: float = float(os.getenv("ANTHROPIC_MONTHLY_CAP_USD", "5.0"))
