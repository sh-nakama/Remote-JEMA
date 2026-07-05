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
import re
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
SLOT_INDEX: dict[str, int] = {s: i for i, s in enumerate(SLOTS)}

# Balancing products to export: (url-safe code, `product` value in the parquet).
# 5 of 7 — skips "1-1" (Primary offline) and "4-0" (Composite).
BALANCING_PRODUCTS: list[tuple[str, str]] = [
    ("1-0", "Primary"),
    ("2-1", "Secondary 1"),
    ("2-2", "Secondary 2"),
    ("3-1", "Tertiary 1"),
    ("3-2", "Tertiary 2"),
]

# Fuel/FX drivers: (frontend key, fuels_daily ticker). NG=F (Henry Hub gas) and
# BZ=F (Brent crude) are PROXIES for JKM LNG / Newcastle coal (data-quality caveat).
DRIVERS: list[tuple[str, str]] = [("jkm", "NG=F"), ("ncl", "BZ=F"), ("fx", "JPY=X")]

# EPRX tieline markets and pair->interconnector-key mapping. Pair strings use " → ".
# 7 of 10 pairs map cleanly to the frontend `icDefs`; the 3 Chubu/Hokuriku/Kansai
# combined-zone pairs have no 1:1 line and fall back to the fixture (key=None).
TIELINE_MARKETS: list[str] = ["DAM", "DCM"]
PAIR_TO_IC: dict[str, str] = {
    "Hokkaido->Tohoku": "hh",
    "Tohoku->Tokyo": "st",
    "Tokyo->Chubu": "fc",
    "Kansai->Chugoku": "ck",
    "Kansai->Shikoku": "sk",
    "Chugoku->Shikoku": "cs",
    "Chugoku->Kyushu": "kq",
}


def _norm_pair(pair: str) -> str:
    return pair.replace(" ", "").replace("→", "->")


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


def export_balancing(out: Path, anchor: date) -> dict:
    """Write ``balancing/{code}/{area}/{level}.json`` + ``balancing_stats/{code}/{area}.json``
    for the 5 exported adjustment-power products (需給調整市場 / EPRX)."""
    files = 0
    total_bytes = 0
    for code, name in BALANCING_PRODUCTS:
        for area in AREAS:
            for level in LEVELS:
                start = anchor - timedelta(days=LEVEL_WINDOW_DAYS[level])
                grid = read.load_balancing_grid(name, area, start, anchor, level)
                payload = {
                    "schema": SCHEMA_VERSION,
                    "product_code": code,
                    "product": name,
                    "area": area,
                    "level": level,
                    "start": start.isoformat(),
                    "end": anchor.isoformat(),
                    "volume": grid["volume"],
                    "price": grid["price"],
                }
                total_bytes += _write_json(out / "balancing" / code / area / f"{level}.json", payload)
                files += 1
            s_start = anchor - timedelta(days=STATS_WINDOW_DAYS)
            stats = read.balancing_period_stats(name, area, s_start, anchor)
            total_bytes += _write_json(
                out / "balancing_stats" / code / f"{area}.json",
                {
                    "schema": SCHEMA_VERSION,
                    "product_code": code,
                    "product": name,
                    "area": area,
                    "window_days": STATS_WINDOW_DAYS,
                    "start": s_start.isoformat(),
                    "end": anchor.isoformat(),
                    **stats,
                },
            )
            files += 1
    return {"files": files, "bytes": total_bytes}


def export_drivers(out: Path, anchor: date, db_path: str | None = None) -> dict:
    """Write ``drivers.json``: daily fuel/FX series (JKM/Newcastle proxies + USD/JPY)
    aligned with the daily-mean JEPX system price + their Pearson correlation.

    Series are chronological (oldest→newest); the frontend adapter reverses them.
    """
    eng = get_engine(db_path)
    with eng.connect() as con:
        fuels = pd.read_sql_query(
            text("SELECT date, ticker, close FROM fuels_daily WHERE date <= :a ORDER BY date"),
            con,
            params={"a": anchor.isoformat()},
        )
        spot = pd.read_sql_query(
            text(
                "SELECT date, AVG(system_price) AS spot FROM jepx_spot_30m "
                "WHERE date <= :a GROUP BY date ORDER BY date"
            ),
            con,
            params={"a": anchor.isoformat()},
        )
    payload: dict = {
        "schema": SCHEMA_VERSION,
        "start": None,
        "end": None,
        "dates": [],
        "spot": [],
        "jkm": [],
        "ncl": [],
        "fx": [],
        "corr": {"jkm": None, "ncl": None, "fx": None},
        "units": {"jkm": "$/MMBtu", "ncl": "$/bbl", "fx": ""},
        "sources": {key: ticker for key, ticker in DRIVERS},
    }
    if not fuels.empty:
        fuels["date"] = fuels["date"].astype(str)
        wide = fuels.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
        wide = wide.rename(columns={ticker: key for key, ticker in DRIVERS}).sort_index()
        if not spot.empty:
            spot["date"] = spot["date"].astype(str)
            wide = wide.join(spot.set_index("date")["spot"], how="left")
        dates = list(wide.index)

        def col(name: str) -> list[float | None]:
            if name not in wide.columns:
                return [None] * len(dates)
            return [None if pd.isna(v) else round(float(v), 4) for v in wide[name]]

        def corr(name: str) -> float | None:
            if name not in wide.columns or "spot" not in wide.columns:
                return None
            sub = wide[[name, "spot"]].dropna()
            if len(sub) < 3:
                return None
            c = sub[name].corr(sub["spot"])
            return None if pd.isna(c) else round(float(c), 3)

        payload.update(
            {
                "start": dates[0] if dates else None,
                "end": dates[-1] if dates else None,
                "dates": dates,
                "spot": col("spot"),
                "jkm": col("jkm"),
                "ncl": col("ncl"),
                "fx": col("fx"),
                "corr": {"jkm": corr("jkm"), "ncl": corr("ncl"), "fx": corr("fx")},
            }
        )
    n = _write_json(out / "drivers.json", payload)
    return {"files": 1, "bytes": n}


def export_tieline(out: Path, anchor: date) -> dict:
    """Write ``tieline/{market}.json``: per interconnector pair, the latest day's
    48-slot reserved/TTC utilisation + TTC, mapped to frontend `icDefs` keys.

    Uses the real EPRX reserved (fwd) vs upper-limit (TTC); reserved is typically a
    small fraction of TTC, i.e. these lines are mostly uncongested in the DA market.
    """
    files = 0
    total_bytes = 0
    # Wide lookback: the global anchor follows supply (which has forecast rows past
    # the tieline data's end), so a narrow window can miss the latest tieline day.
    start = anchor - timedelta(days=60)
    for market in TIELINE_MARKETS:
        recs = read.load_tieline(market, start, anchor, "Native")
        by_pair: dict[str, list] = {}
        for r in recs:
            by_pair.setdefault(r["pair"], []).append(r)
        lines = []
        for pair, rows in sorted(by_pair.items()):
            rows.sort(key=lambda r: r["datetime"])
            last_date = rows[-1]["datetime"][:10]
            util: list[float | None] = [None] * 48
            ttc: float | None = None
            for r in rows:
                if r["datetime"][:10] != last_date:
                    continue
                t = r["datetime"][11:16]
                idx = SLOT_INDEX.get(t)
                if idx is None:
                    continue
                ul = r.get("upper_limit_fwd")
                rv = r.get("reserved_fwd")
                if ul not in (None, 0) and rv is not None:
                    util[idx] = round(min(1.0, max(0.0, rv / ul)), 4)
                if ul is not None and (ttc is None or ul > ttc):
                    ttc = ul
            util_now = next((x for x in reversed(util) if x is not None), None)
            lines.append(
                {
                    "key": PAIR_TO_IC.get(_norm_pair(pair)),
                    "pair": pair,
                    "date": last_date,
                    "ttc": None if ttc is None else round(float(ttc), 1),
                    "util": util,
                    "util_now": util_now,
                }
            )
        payload = {"schema": SCHEMA_VERSION, "market": market, "slots": SLOTS, "lines": lines}
        total_bytes += _write_json(out / "tieline" / f"{market}.json", payload)
        files += 1
    return {"files": files, "bytes": total_bytes}


# ── Policy (committees / meetings / materials) ──────────────────────────────

ORG_RANK = {"METI": 0, "OCCTO": 1, "EGC": 2}


def _md_clean(t: str) -> str:
    """Strip the bits of Markdown/LaTeX that shouldn't render as plain text."""
    t = re.sub(r"\$\\?geq\$", "≥", t)
    t = re.sub(r"\$\\?leq\$", "≤", t)
    t = re.sub(r"\$\\?Delta\$", "Δ", t)
    t = re.sub(r"\$[^$]*\$", "", t)
    return t.replace("**", "").replace("`", "").strip()


def parse_digest_answer(answer: str | None) -> tuple[list[dict], str]:
    """Split the English digest Markdown into ``[{h, items[]}]`` + a lead preview.

    The answer is a lead paragraph followed by ``### Section`` headers with
    ``* bullet`` items (see policy_meeting.digest_en_json.answer).
    """
    sections: list[dict] = []
    cur: dict = {"h": "Summary", "items": []}
    lead = ""
    for raw in (answer or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if cur["items"]:
                sections.append(cur)
            cur = {"h": _md_clean(line.lstrip("#").strip()), "items": []}
        elif line[0] in "*-•":
            item = _md_clean(line.lstrip("*-• ").strip())
            if item:
                cur["items"].append(item)
        else:
            item = _md_clean(line)
            if item:
                lead = lead or item
                cur["items"].append(item)
    if cur["items"]:
        sections.append(cur)
    return sections, lead


def parse_briefing(md: str | None) -> tuple[list[dict], str, str]:
    """Split the Japanese briefing Markdown into ``[{h, t}]`` + (title, lead).

    Keeps the leading intro/basic-info as an 概要 section, one section per ``##``
    header, drops Markdown tables, and flattens bullets/sub-headers into text.
    """
    sections: list[dict] = []
    cur: dict = {"h": "概要 · Overview", "t": ""}
    title = ""
    lead = ""
    for raw in (md or "").split("\n"):
        st = raw.strip()
        if not st:
            cur["t"] += "\n"
            continue
        if st.startswith("## "):
            if cur["t"].strip():
                sections.append(cur)
            cur = {"h": _md_clean(st.lstrip("#").strip()), "t": ""}
        elif st.startswith("# "):
            title = _md_clean(st.lstrip("#").strip())
        elif st.startswith("---") or st.startswith("|"):
            continue
        elif st.startswith("###"):
            cur["t"] += "\n【" + _md_clean(st.lstrip("#").strip()) + "】\n"
        elif st[0] in "*-•⚫":
            body = _md_clean(st.lstrip("*-•⚫ ").strip())
            cur["t"] += "・" + body + "\n"
            lead = lead or body
        else:
            body = _md_clean(st)
            cur["t"] += body + "\n"
            if body and not body.startswith("【"):
                lead = lead or body
    if cur["t"].strip():
        sections.append(cur)
    for s in sections:
        s["t"] = s["t"].strip()[:1800]
    return [s for s in sections if s["t"]], title, lead


def _doc_size(title: str) -> str:
    m = re.search(r"([\d,]+)\s*KB", title or "")
    if not m:
        return "—"
    kb = int(m.group(1).replace(",", ""))
    return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb} KB"


def _doc_name(title: str) -> str:
    return re.sub(r"（PDF形式[:：][^）]*）", "", title or "").strip() or "資料"


def _committee_tier(c: dict) -> str:
    p = c["priority"]
    if isinstance(p, int) and p <= 1:
        return "Tier 1"
    return "Tier 1" if (c["source_count"] or 0) >= 8 else "Tier 2"


def export_policy(out: Path, db_path: str | None = None) -> dict:
    """Write ``policy/committees.json`` + ``policy/meetings.json`` from the policy
    tables (committees, meetings with parsed EN digest + JP briefing, materials).

    Uses raw SQL (the ORM models don't map every DB column). Meetings are the
    summarised (``done``) ones plus any with detected materials (``pending``);
    meeting_date is not populated upstream, so the updated/detected date is used.
    """
    eng = get_engine(db_path)
    with eng.connect() as con:
        committees = con.execute(
            text(
                "SELECT committee_key, name_ja, name_en, url, source, latest_meeting, "
                "source_count, enabled, priority FROM policy_committee"
            )
        ).mappings().all()
        meetings = con.execute(
            text(
                "SELECT id, committee_key, meeting_num, briefing_md, digest_en_json, has_minutes, "
                "has_torimatome, state, updated_at, detected_at FROM policy_meeting"
            )
        ).mappings().all()
        materials = con.execute(
            text("SELECT committee_key, meeting_num, kind, url, title FROM policy_material")
        ).mappings().all()

    mats_by_mtg: dict[tuple, list] = {}
    for x in materials:
        mats_by_mtg.setdefault((x["committee_key"], x["meeting_num"]), []).append(x)
    com_by_key = {c["committee_key"]: c for c in committees}

    committees_data = [
        {
            "key": c["committee_key"],
            "org": c["source"] or "METI",
            "en": c["name_en"] or c["committee_key"],
            "ja": c["name_ja"] or "",
            "tier": _committee_tier(c),
            "followed": bool(c["enabled"]),
            "last": ("第" + str(c["latest_meeting"]) + "回") if c["latest_meeting"] else "—",
            "url": c["url"] or "",
            "latest_meeting": c["latest_meeting"],
            "source_count": c["source_count"] or 0,
        }
        for c in committees
    ]
    committees_data.sort(key=lambda x: (ORG_RANK.get(x["org"], 3), -(x["source_count"] or 0)))

    def build_meeting(m: dict) -> dict:
        c = com_by_key.get(m["committee_key"])
        org = (c["source"] if c else None) or "METI"
        name_en = (c["name_en"] if c else None) or m["committee_key"]
        name_ja = (c["name_ja"] if c else None) or m["committee_key"]
        num = m["meeting_num"]
        upd = (str(m["updated_at"] or m["detected_at"] or ""))[:10]
        mats = mats_by_mtg.get((m["committee_key"], m["meeting_num"]), [])
        docs = [{"name": _doc_name(x["title"]), "size": _doc_size(x["title"]), "url": x["url"] or ""} for x in mats]
        has_digest = m["state"] == "done" and bool(m["digest_en_json"])
        out_m: dict = {
            "key": "m" + str(m["id"]),
            "com": m["committee_key"],
            "num": num,
            "org": org,
            "en": name_en + " · No. " + str(num),
            "ja": name_ja + " · 第" + str(num) + "回",
            "date": upd,
            "status": "done" if has_digest else "pending",
            "tori": bool(m["has_torimatome"]),
            "title": name_en + " — No. " + str(num),
            "titleJa": name_ja + " 第" + str(num) + "回",
            "sub": name_ja + " · 第" + str(num) + "回 · " + org
            + (" · とりまとめ" if m["has_torimatome"] else "")
            + (" · 議事録" if m["has_minutes"] else "")
            + (" · " + upd if upd else ""),
            "docs": docs,
        }
        if has_digest:
            try:
                digest = json.loads(m["digest_en_json"])
            except (ValueError, TypeError):
                digest = {}
            secs, lead_en = parse_digest_answer(digest.get("answer"))
            jp_secs, _title, lead_ja = parse_briefing(m["briefing_md"])
            refs = []
            for r in (digest.get("references") or [])[:16]:
                n = r.get("citation_number")
                ct = (r.get("cited_text") or "").strip()
                refs.append(f"[{n}] {ct[:22]}" if ct else f"[{n}]")
            out_m["digest"] = secs
            out_m["jp"] = jp_secs
            out_m["refs"] = refs
            out_m["prevEn"] = lead_en[:180]
            out_m["prevJa"] = lead_ja[:110]
        else:
            out_m["emptyTitle"] = "Summary pending · 要約待ち"
            out_m["emptySub"] = (
                f"{len(docs)} materials detected · queued for the next catch-up run · 資料取得済み・要約待ち"
            )
        return out_m

    kept = [
        m
        for m in meetings
        if (m["state"] == "done" and m["digest_en_json"]) or mats_by_mtg.get((m["committee_key"], m["meeting_num"]))
    ]
    kept.sort(key=lambda m: (0 if (m["state"] == "done" and m["digest_en_json"]) else 1, -(m["meeting_num"] or 0)))
    meetings_data = [build_meeting(m) for m in kept]

    files = 0
    total = 0
    total += _write_json(out / "policy" / "committees.json", {"schema": SCHEMA_VERSION, "committees": committees_data})
    files += 1
    total += _write_json(out / "policy" / "meetings.json", {"schema": SCHEMA_VERSION, "meetings": meetings_data})
    files += 1
    return {
        "files": files,
        "bytes": total,
        "committees": len(committees_data),
        "meetings": len(meetings_data),
        "summarised": sum(1 for m in meetings_data if m["status"] == "done"),
    }


def export_capacity(out: Path) -> dict:
    """Export curated capacity-market snapshots (main auction + LTDA).

    OCCTO publishes the summary only as PDF/Excel, so these come from the
    curated, source-cited ``capacity_data`` module (see its docstring). Shapes
    match ``web/src/screens/CapacityAuctions.data.ts`` exactly.
    """
    from repower.dashboard.read import load_capacity_ltda, load_capacity_ma

    total = 0
    total += _write_json(
        out / "capacity" / "main_auction.json",
        {"schema": SCHEMA_VERSION, "results": load_capacity_ma()},
    )
    total += _write_json(
        out / "capacity" / "ltda.json",
        {"schema": SCHEMA_VERSION, "rows": load_capacity_ltda()},
    )
    return {"files": 2, "bytes": total}


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
    manifest["datasets"]["balancing"] = export_balancing(out, anchor)
    manifest["datasets"]["tieline"] = export_tieline(out, anchor)
    manifest["datasets"]["drivers"] = export_drivers(out, anchor, db_path)
    manifest["datasets"]["policy"] = export_policy(out, db_path)
    manifest["datasets"]["capacity"] = export_capacity(out)
    _write_json(out / "manifest.json", manifest)
    return manifest
