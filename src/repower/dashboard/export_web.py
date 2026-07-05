"""Static JSON snapshot exporter for the JEMA web frontend.

Generates ``data/web/**`` from the :mod:`repower.dashboard.read` loaders so the
React app under ``web/`` can render live data as plain static files — no running
server. Intended to run at data-refresh time (the daily cron, after ``run-all``)
with the output synced to Hugging Face alongside the DB/Parquet.

Design notes:
- The read-layer loaders already return JSON-serializable dicts and already
  aggregate to Native/Daily/Weekly/Monthly, so this module is a thin driver over
  the closed parameter space (9 areas x 4 levels for wholesale in Phase 0/1).
- Bilingual labels are baked into ``meta/*`` (added in later phases); numeric
  snapshots stay language-neutral.
- ``load_*`` loaders are decorated with ``@st.cache_data``; called outside
  ``streamlit run`` they emit "no runtime" warnings, which we silence below.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

# Silence Streamlit's "No runtime found" cache warnings when the cached loaders
# run inside this CLI/CI process (correctness is unaffected).
logging.getLogger("streamlit").setLevel(logging.ERROR)

import pandas as pd  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from repower.dashboard import read  # noqa: E402
from repower.db import (  # noqa: E402
    DemandSupply30m,
    JepxAreaPrice30m,
    JepxSpot30m,
    get_engine,
    get_session,
)

# Geographic ordering, matching the frontend area keys (``tepco`` == Tokyo).
AREAS: list[str] = [
    "hokkaido", "tohoku", "tepco", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu",
]
LEVELS: list[str] = ["Native", "Daily", "Weekly", "Monthly"]

# Trailing window (days) per level: Native keeps recent 30-min detail compact;
# aggregated levels span the full history cheaply (buckets collapse the volume).
LEVEL_WINDOW_DAYS: dict[str, int] = {
    "Native": 90, "Daily": 800, "Weekly": 800, "Monthly": 800,
}
STATS_WINDOW_DAYS = 30
SCHEMA_VERSION = 1

# 48 half-hour slot labels "00:00" .. "23:30" (JEPX 30-min grid).
SLOTS: list[str] = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


def _write_json(path: Path, obj: object) -> int:
    """Write *obj* as compact UTF-8 JSON; return byte length written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def source_max_dates(db_path: str | None = None) -> dict[str, str | None]:
    """Latest available date per wholesale source (for the freshness rail)."""
    session = get_session(db_path)
    try:
        ds_max = session.execute(select(func.max(DemandSupply30m.date))).scalar()
        px_max = session.execute(select(func.max(JepxAreaPrice30m.date))).scalar()
        sys_max = session.execute(select(func.max(JepxSpot30m.date))).scalar()
    finally:
        session.close()

    def _iso(v: object) -> str | None:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return {
        "supply": _iso(ds_max),
        "area_price": _iso(px_max),
        "system_price": _iso(sys_max),
    }


def _anchor_date(maxes: dict[str, str | None]) -> date:
    vals = [date.fromisoformat(v) for v in maxes.values() if v]
    return max(vals) if vals else date.today()


def export_wholesale(out: Path, anchor: date) -> dict:
    """Write ``wholesale/{area}/{level}.json`` + ``wholesale_stats/{area}.json``."""
    files = 0
    total_bytes = 0
    for area in AREAS:
        for level in LEVELS:
            start = anchor - timedelta(days=LEVEL_WINDOW_DAYS[level])
            grid = read.load_wholesale_grid(area, start, anchor, level)
            payload = {
                "schema": SCHEMA_VERSION,
                "area": area,
                "level": level,
                "start": start.isoformat(),
                "end": anchor.isoformat(),
                "supply": grid["supply"],
                "price": grid["price"],
            }
            total_bytes += _write_json(out / "wholesale" / area / f"{level}.json", payload)
            files += 1
        s_start = anchor - timedelta(days=STATS_WINDOW_DAYS)
        stats = read.wholesale_period_stats(area, s_start, anchor)
        total_bytes += _write_json(
            out / "wholesale_stats" / f"{area}.json",
            {
                "schema": SCHEMA_VERSION,
                "area": area,
                "window_days": STATS_WINDOW_DAYS,
                "start": s_start.isoformat(),
                "end": anchor.isoformat(),
                **stats,
            },
        )
        files += 1
    return {"files": files, "bytes": total_bytes}


def _slot_col(piv: pd.DataFrame, day: str | None) -> list[float | None]:
    """Reindex a time-indexed pivot column onto the full 48-slot grid, rounded."""
    if day is None or day not in piv.columns:
        return [None] * 48
    s = piv[day].reindex(SLOTS)
    return [None if pd.isna(x) else round(float(x), 3) for x in s]


def export_system(out: Path, anchor: date, db_path: str | None = None) -> dict:
    """Write ``system.json``: JEPX **system-price** intraday (today / yesterday /
    7-day average, by 30-min slot) + Tokyo intraday + latest per-area price.

    Feeds the Market Overview intraday chart, the System/Tokyo "now" tiles and
    the 9-area spot grid. Prices are language-neutral floats.
    """
    eng = get_engine(db_path)
    payload: dict = {
        "schema": SCHEMA_VERSION,
        "slots": SLOTS,
        "date_today": None,
        "date_yday": None,
        "system_today": [None] * 48,
        "system_yday": [None] * 48,
        "system_avg7": [None] * 48,
        "tokyo_today": [None] * 48,
        "now": {"system": None, "tokyo": None, "slot": None},
        "areas_now": {},
    }
    with eng.connect() as con:
        spot = pd.read_sql_query(
            text(
                "SELECT date, time, system_price, tokyo_area_price FROM jepx_spot_30m "
                "WHERE date <= :a ORDER BY date, time"
            ),
            con,
            params={"a": anchor.isoformat()},
        )
        if not spot.empty:
            spot = spot.dropna(subset=["system_price"])
            spot["date"] = spot["date"].astype(str)
            days = sorted(spot["date"].unique())
            last = days[-1]
            prev = days[-2] if len(days) > 1 else None
            recent = days[-7:]
            sys_piv = spot.pivot_table(index="time", columns="date", values="system_price", aggfunc="last")
            tok_piv = spot.pivot_table(index="time", columns="date", values="tokyo_area_price", aggfunc="last")
            avg7 = sys_piv[recent].mean(axis=1).reindex(SLOTS)
            last_rows = spot[spot["date"] == last]
            now_slot = str(last_rows["time"].max()) if not last_rows.empty else None
            now_row = last_rows[last_rows["time"] == now_slot] if now_slot else last_rows.iloc[0:0]
            now_sys = float(now_row["system_price"].iloc[0]) if not now_row.empty else None
            tok_val = now_row["tokyo_area_price"].iloc[0] if not now_row.empty else None
            now_tok = float(tok_val) if tok_val is not None and pd.notna(tok_val) else None
            payload.update(
                {
                    "date_today": last,
                    "date_yday": prev,
                    "system_today": _slot_col(sys_piv, last),
                    "system_yday": _slot_col(sys_piv, prev),
                    "system_avg7": [None if pd.isna(x) else round(float(x), 3) for x in avg7],
                    "tokyo_today": _slot_col(tok_piv, last),
                    "now": {
                        "system": None if now_sys is None else round(now_sys, 3),
                        "tokyo": None if now_tok is None else round(now_tok, 3),
                        "slot": now_slot,
                    },
                }
            )

        area_df = pd.read_sql_query(
            text(
                "SELECT area, time, price FROM jepx_area_price_30m "
                "WHERE date = (SELECT MAX(date) FROM jepx_area_price_30m WHERE date <= :a)"
            ),
            con,
            params={"a": anchor.isoformat()},
        )
    if not area_df.empty:
        latest = area_df.dropna(subset=["price"]).sort_values("time").groupby("area")["price"].last()
        payload["areas_now"] = {a: round(float(p), 3) for a, p in latest.items()}

    n = _write_json(out / "system.json", payload)
    return {"files": 1, "bytes": n}


def export_web(out_dir: str | Path = "web/public/data/web", db_path: str | None = None) -> dict:
    """Export all web snapshots to *out_dir*; write ``manifest.json``; return it.

    Default target is ``web/public/data/web`` so the Vite dev server and
    ``vite build`` serve the snapshots at ``/data/web/**`` with zero config.
    The daily cron / HF-sync path can override ``--out`` (reconciled in the
    deploy phase).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    maxes = source_max_dates(db_path)
    anchor = _anchor_date(maxes)

    manifest: dict = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "anchor": anchor.isoformat(),
        "areas": AREAS,
        "levels": LEVELS,
        "sources": maxes,
        "datasets": {},
    }
    manifest["datasets"]["wholesale"] = export_wholesale(out, anchor)
    manifest["datasets"]["system"] = export_system(out, anchor, db_path)
    _write_json(out / "manifest.json", manifest)
    return manifest
