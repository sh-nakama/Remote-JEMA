"""Scrape EPRX balancing-market data (per product) and tieline (interconnector) data.

EPRX publishes one ZIP per Japanese fiscal year (April-March), one ZIP per
product (and per tieline market). Each ZIP holds CP932-encoded CSVs with a
4-line structure:

    line 0  H line  -- title / header
    line 1  P line  -- comma-separated; field [4] = blocks/day for products,
                       field [3] = blocks/day for tieline
    line 2  T line  -- column headers (used for tieline metric detection)
    line 3+ data    -- ``block_id, metric_jp, region1..region9, total``

``block_id`` looks like ``YYYYMMDDBNN`` (e.g. ``20260314B01``). ``blocks_per_day``
is 8 or 48; ``time`` is derived as ``(block_num-1) * 24/blocks_per_day`` and we
NEVER interpolate 8-block data up to 48.

This module ports ``Reference/dashboard_hh/data_loader.py`` to the project idiom:
httpx + ``sqlite_upsert`` + ``get_session``/``init_db`` + logging, with a
DB-backed conditional GET cache (``EprxHttpCache``) instead of the in-process
dict the reference used. Parse functions are pure (no network).
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date as _date, datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

from repower.config import EPRX_BALANCING_PARQUET, EPRX_TIELINE_PARQUET
from repower.db import EprxHttpCache, get_session, init_db

logger = logging.getLogger(__name__)

# ── EPRX source config ───────────────────────────────────────────────────────
_EPRX_BASE_DEFAULT = "https://www.eprx.or.jp/information/files"
try:  # optional override in config.py
    from repower.config import EPRX_BASE as _EPRX_BASE  # type: ignore
except Exception:  # noqa: BLE001
    _EPRX_BASE = _EPRX_BASE_DEFAULT

_FIRST_JFY = 2025  # earliest fiscal year with data


def _current_jfy() -> int:
    """Return the current Japanese fiscal year (starts April)."""
    today = _date.today()
    return today.year if today.month >= 4 else today.year - 1


# product name -> {code, folder} (folder kept for provenance/source_file naming)
PRODUCTS: dict[str, dict[str, str]] = {
    "Primary":           {"code": "1-0", "folder": "1-0_prompt"},
    "Primary (offline)": {"code": "1-1", "folder": "1-1_prompt"},
    "Secondary 1":       {"code": "2-1", "folder": "2-1_prompt"},
    "Secondary 2":       {"code": "2-2", "folder": "2-2_prompt"},
    "Tertiary 1":        {"code": "3-1", "folder": "3-1_prompt"},
    "Tertiary 2":        {"code": "3-2", "folder": "3-2_prompt"},
    "Composite":         {"code": "4-0", "folder": "4-0_prompt"},
}


def _build_urls(code: str, jfy_since: int | None = None) -> list[tuple[int, str]]:
    """EPRX product ZIP URLs for each JFY from *jfy_since* to current. -> [(jfy, url)]."""
    start = jfy_since if jfy_since is not None else _FIRST_JFY
    start = max(start, _FIRST_JFY)
    return [
        (jfy, f"{_EPRX_BASE}/{jfy}_{code}_prompt.zip")
        for jfy in range(start, _current_jfy() + 1)
    ]


# ── Region (TSO) columns in CSV order ────────────────────────────────────────
REGION_COLUMNS_JP = [
    "北海道", "東北", "東京", "中部", "北陸", "関西", "中国", "四国", "九州", "合計",
]

# JP region -> lowercase project area slug. 東京 -> tepco; 合計 (Total) is dropped.
REGION_JP_TO_EN: dict[str, str] = {
    "北海道": "hokkaido",
    "東北":   "tohoku",
    "東京":   "tepco",
    "中部":   "chubu",
    "北陸":   "hokuriku",
    "関西":   "kansai",
    "中国":   "chugoku",
    "四国":   "shikoku",
    "九州":   "kyushu",
    "合計":   "Total",  # dropped during parse
}

VALID_AREAS = {
    "hokkaido", "tohoku", "tepco", "chubu", "hokuriku",
    "kansai", "chugoku", "shikoku", "kyushu",
}

# ── Metric mapping (Japanese -> English key) ─────────────────────────────────
METRIC_MAP: dict[str, str] = {
    "募集量（TSO別）[MW]":               "demand_mw",
    "応札量合計（電源属地別）[MW]":       "bid_volume_mw",
    "落札量合計（TSO別）[MW]":           "contracted_mw",
    "応札件数（電源属地別）[件]":         "bids_count",
    "落札件数（電源属地別）[件]":         "contracted_count",
    "最高落札価格（TSO別）[円/kW・30分]": "price_max",
    "最低落札価格（TSO別）[円/kW・30分]": "price_min",
    "平均落札価格（TSO別）[円/kW・30分]": "price_avg",
}

# ── Tieline (interconnector) config ──────────────────────────────────────────
TIELINE_MARKETS: dict[str, dict[str, str]] = {
    "DCM": {
        "label": "DCM (Balancing Market)",
        "folder": "tieline_DCM_prompt",
        "code_new": "tieline_DCM",     # FY2026+
        "code_old": "tieline_weekly",  # FY2025
    },
    "DAM": {
        "label": "DAM (Tertiary 2)",
        "folder": "tieline_DAM_prompt",
        "code_new": "tieline_DAM",     # FY2026+
        "code_old": "tieline_daily",   # FY2025
    },
}

# FY2025 uses old naming; FY2026+ uses new naming.
_TIELINE_TRANSITION_JFY = 2026


def _build_tieline_urls(market_key: str, jfy_since: int | None = None) -> list[tuple[int, str]]:
    """EPRX tieline ZIP URLs per JFY. -> [(jfy, url)]."""
    info = TIELINE_MARKETS[market_key]
    start = jfy_since if jfy_since is not None else _FIRST_JFY
    start = max(start, _FIRST_JFY)
    urls: list[tuple[int, str]] = []
    for jfy in range(start, _current_jfy() + 1):
        code = info["code_new"] if jfy >= _TIELINE_TRANSITION_JFY else info["code_old"]
        urls.append((jfy, f"{_EPRX_BASE}/{jfy}_{code}_prompt.zip"))
    return urls


# Sub-route pairs to exclude (duplicates of main pair values).
_TIELINE_SUBROUTE_REGIONS = {
    "関西_関西-中国間(東)", "中国_関西-中国間(東)",
    "関西_関西-中国間(西)", "中国_関西-中国間(西)",
}

# Interconnector pair name mapping (Japanese (from, to) -> English pair label).
INTERCONNECTOR_JP_TO_EN: dict[tuple[str, str], str] = {
    ("北海道", "東北"):   "Hokkaido → Tohoku",
    ("東北", "東京"):     "Tohoku → Tokyo",
    ("東京", "中部"):     "Tokyo → Chubu",
    # Pre-March-14 pairs (FY2025 weekly/daily)
    ("中部", "関西"):     "Chubu → Kansai",
    ("中部", "北陸"):     "Chubu → Hokuriku",
    ("北陸", "関西"):     "Hokuriku → Kansai",
    # Post-March-14 pairs (FY2026 DCM/DAM)
    ("中部関西", "北陸"): "Chubu-Kansai → Hokuriku",
    ("中部", "北陸関西"): "Chubu → Hokuriku-Kansai",
    ("中部北陸", "関西"): "Chubu-Hokuriku → Kansai",
    # Common pairs
    ("関西", "中国"):     "Kansai → Chugoku",
    ("関西", "四国"):     "Kansai → Shikoku",
    ("中国", "四国"):     "Chugoku → Shikoku",
    ("中国", "九州"):     "Chugoku → Kyushu",
}

# Combined-zone (post-Mar-14) pair labels — flagged is_combined=True on write.
_COMBINED_ZONE_PAIRS = {
    "Chubu-Kansai → Hokuriku",
    "Chubu → Hokuriku-Kansai",
    "Chubu-Hokuriku → Kansai",
}

# Tieline metric column patterns (header substring -> english metric key).
_TIELINE_METRIC_PATTERNS: dict[str, list[str]] = {
    "upper_limit_fwd": ["連系線確保量上限値（順方向）"],
    "upper_limit_rev": ["連系線確保量上限値（逆方向）"],
    "reserved_fwd":    ["連系線確保量（順方向）"],
    "reserved_rev":    ["連系線確保量（逆方向）"],
}

_BLOCK_ID_RE = re.compile(r"(\d{8})B(\d+)")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _decode(text: str | bytes) -> list[str]:
    """Decode CP932 bytes (or pass through str) and split into stripped lines."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("cp932", errors="replace")
    return text.splitlines()


def _block_time(block_num: int, blocks_per_day: int) -> str:
    """Derive 'HH:MM' for the start of a block. 48->30min, 8->3h. No interpolation."""
    if not blocks_per_day:
        blocks_per_day = 48
    minutes = int(round((block_num - 1) * (24.0 * 60.0) / blocks_per_day))
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _to_float(raw: str) -> float:
    """Parse a numeric cell. Blank / unparseable -> 0.0 (matches reference)."""
    raw = (raw or "").strip()
    if raw == "":
        return 0.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def _date_from_str(date_str: str) -> _date:
    return _date(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8]))


# ── Pure parse: product CSV ──────────────────────────────────────────────────
def parse_product_csv(
    text: str | bytes,
    product_code: str,
    product: str,
    source_file: str,
) -> list[dict]:
    """Parse one EPRX product CSV into long-format row dicts (pure, no network).

    Each row dict has keys:
        product_code, product, area, date, time, block_num, blocks_per_day,
        metric, value, jfy, source_file

    ``東京`` maps to ``tepco``; ``合計`` (Total) is dropped. Unknown metrics and
    malformed block ids are skipped. Blank cells become ``0.0``.
    """
    lines = _decode(text)
    if len(lines) < 4:
        return []

    p_parts = lines[1].strip().split(",")
    try:
        blocks_per_day = int(p_parts[4]) if len(p_parts) > 4 and p_parts[4].strip() else 48
    except (ValueError, IndexError):
        blocks_per_day = 48

    rows: list[dict] = []
    for line in lines[3:]:
        if not line.strip():
            continue
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue

        block_id = parts[0].strip()
        metric_jp = parts[1].strip()
        metric_en = METRIC_MAP.get(metric_jp)
        if metric_en is None:
            continue

        m = _BLOCK_ID_RE.match(block_id)
        if not m:
            continue
        date_str = m.group(1)
        block_num = int(m.group(2))
        d = _date_from_str(date_str)
        jfy = d.year if d.month >= 4 else d.year - 1
        time_str = _block_time(block_num, blocks_per_day)

        for i, region_jp in enumerate(REGION_COLUMNS_JP):
            area = REGION_JP_TO_EN[region_jp]
            if area == "Total":  # drop 合計
                continue
            col_idx = 2 + i  # 0=block_id, 1=metric, 2=first region
            val = _to_float(parts[col_idx]) if col_idx < len(parts) else 0.0
            rows.append({
                "product_code": product_code,
                "product": product,
                "area": area,
                "date": d,
                "time": time_str,
                "block_num": block_num,
                "blocks_per_day": blocks_per_day,
                "metric": metric_en,
                "value": val,
                "jfy": jfy,
                "source_file": source_file,
            })

    return rows


# ── Pure parse: tieline CSV ──────────────────────────────────────────────────
def parse_tieline_csv(
    text: str | bytes,
    market: str,
    source_file: str,
) -> list[dict]:
    """Parse one EPRX tieline CSV into long-format row dicts (pure, no network).

    Each row dict has keys:
        market, pair, date, time, block_num, blocks_per_day, metric, value,
        is_combined, jfy, source_file

    Sub-route duplicate regions and unknown pairs are dropped. Metric columns are
    detected from the T line (line index 2). Blank cells become ``0.0``.
    """
    lines = _decode(text)
    if len(lines) < 4:
        return []

    p_parts = lines[1].strip().split(",")
    try:
        blocks_per_day = int(p_parts[3]) if len(p_parts) > 3 and p_parts[3].strip() else 48
    except (ValueError, IndexError):
        blocks_per_day = 48

    # T line: detect which columns carry which metric.
    t_parts = lines[2].strip().split(",")
    col_metrics: dict[int, str] = {}
    for col_idx in range(3, len(t_parts)):
        header = t_parts[col_idx].strip()
        for metric_en, patterns in _TIELINE_METRIC_PATTERNS.items():
            if any(pat in header for pat in patterns):
                col_metrics[col_idx] = metric_en
                break

    rows: list[dict] = []
    for line in lines[3:]:
        if not line.strip():
            continue
        parts = line.strip().split(",")
        if len(parts) < 5:
            continue

        block_id = parts[0].strip()
        from_area = parts[1].strip()
        to_area = parts[2].strip()

        if from_area in _TIELINE_SUBROUTE_REGIONS or to_area in _TIELINE_SUBROUTE_REGIONS:
            continue

        pair_en = INTERCONNECTOR_JP_TO_EN.get((from_area, to_area))
        if pair_en is None:
            continue

        m = _BLOCK_ID_RE.match(block_id)
        if not m:
            continue
        date_str = m.group(1)
        block_num = int(m.group(2))
        d = _date_from_str(date_str)
        jfy = d.year if d.month >= 4 else d.year - 1
        time_str = _block_time(block_num, blocks_per_day)
        is_combined = pair_en in _COMBINED_ZONE_PAIRS

        for col_idx, metric_en in col_metrics.items():
            val = _to_float(parts[col_idx]) if col_idx < len(parts) else 0.0
            rows.append({
                "market": market,
                "pair": pair_en,
                "date": d,
                "time": time_str,
                "block_num": block_num,
                "blocks_per_day": blocks_per_day,
                "metric": metric_en,
                "value": val,
                "is_combined": is_combined,
                "jfy": jfy,
                "source_file": source_file,
            })

    return rows


# ── Parquet merge (EPRX data lives in compressed Parquet, not SQLite) ─────────
# The long format compresses ~200x better as columnar Parquet than as SQLite
# rows+indexes, so balancing/tieline data is merged into Parquet files keyed on
# the same logical unique columns (last write wins).
_BAL_KEYS = ["product_code", "area", "date", "time", "metric"]
_TIE_KEYS = ["market", "pair", "date", "time", "metric"]


def _merge_parquet(path, rows: list[dict], keys: list[str]) -> int:
    """Merge *rows* into the Parquet at *path*, de-duplicating on *keys* (last
    write wins). ``date`` is stored as an ISO ``YYYY-MM-DD`` string so date-range
    filters and the downstream datetime construction work uniformly. Returns the
    number of rows processed."""
    if not rows:
        return 0
    new = pd.DataFrame(rows)
    new["date"] = new["date"].astype(str)
    path = Path(path)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new], ignore_index=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        combined = new
    combined = combined.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)
    combined.to_parquet(path, compression="zstd", index=False)
    return len(new)


def upsert_eprx(rows: list[dict], path=None) -> int:
    """Merge balancing rows into the balancing Parquet. Returns rows processed."""
    return _merge_parquet(path or EPRX_BALANCING_PARQUET, rows, _BAL_KEYS)


def upsert_eprx_tieline(rows: list[dict], path=None) -> int:
    """Merge tieline rows into the tieline Parquet. Returns rows processed."""
    return _merge_parquet(path or EPRX_TIELINE_PARQUET, rows, _TIE_KEYS)


# ── Fetch (network) with DB-backed conditional GET ───────────────────────────
def _read_cache(session, url: str) -> EprxHttpCache | None:
    return session.get(EprxHttpCache, url)


def _write_cache(session, url: str, etag, last_modified, status: int) -> None:
    entry = session.get(EprxHttpCache, url)
    now = datetime.now(timezone.utc)
    if entry is None:
        entry = EprxHttpCache(url=url)
        session.add(entry)
    entry.etag = etag
    entry.last_modified = last_modified
    entry.last_status = status
    entry.last_checked = now
    session.commit()


def _fetch_zip_csvs(
    url: str,
    db_path: str | None = None,
    force: bool = False,
) -> list[tuple[str, bytes]] | None:
    """Conditional GET *url*, extract CSVs from the ZIP.

    Returns ``[(filename, raw_bytes), ...]`` on a fresh 200, ``None`` on 304 / no
    change / failure (caller treats None as "nothing to do, no error").
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        headers: dict[str, str] = {}
        if not force:
            cached = _read_cache(session, url)
            if cached is not None:
                if cached.etag:
                    headers["If-None-Match"] = cached.etag
                if cached.last_modified:
                    headers["If-Modified-Since"] = cached.last_modified

        try:
            resp = httpx.get(url, headers=headers, timeout=60, follow_redirects=True)
        except httpx.HTTPError as e:
            logger.warning("EPRX fetch %s: %s", url, e)
            return None

        if resp.status_code == 304:
            logger.info("EPRX %s: 304 not modified", url)
            _write_cache(session, url, resp.headers.get("ETag"),
                         resp.headers.get("Last-Modified"), 304)
            return None
        if resp.status_code != 200:
            logger.warning("EPRX %s: HTTP %s", url, resp.status_code)
            _write_cache(session, url, None, None, resp.status_code)
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csvs = [
                    (name, zf.read(name))
                    for name in zf.namelist()
                    if name.lower().endswith(".csv")
                ]
        except zipfile.BadZipFile:
            logger.warning("EPRX %s: bad zip", url)
            return None

        _write_cache(session, url, resp.headers.get("ETag"),
                     resp.headers.get("Last-Modified"), 200)
        return csvs
    finally:
        session.close()


def _select_csvs(csvs: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Apply split-file precedence: when split files (``_MMDD-MMDD_``) exist for a
    YYYYMM, drop that month's full-month file in favour of the split files."""
    if not csvs:
        return []

    by_month: dict[str, list[tuple[str, bytes]]] = {}
    other: list[tuple[str, bytes]] = []
    for name, data in csvs:
        m = re.match(r"(\d{6})_", name)
        if m:
            by_month.setdefault(m.group(1), []).append((name, data))
        else:
            other.append((name, data))

    result: list[tuple[str, bytes]] = []
    for _ym, files in sorted(by_month.items()):
        splits = [(n, d) for n, d in files if re.search(r"_\d{4}-\d{4}_", n)]
        result.extend(sorted(splits) if splits else sorted(files))
    result.extend(sorted(other))
    return result


# ── Scrape orchestration ─────────────────────────────────────────────────────
def _scrape_products(
    jfy_since: int | None = None,
    db_path: str | None = None,
    force: bool = False,
) -> int:
    total = 0
    for product, info in PRODUCTS.items():
        for jfy, url in _build_urls(info["code"], jfy_since):
            try:
                csvs = _fetch_zip_csvs(url, db_path=db_path, force=force)
                if not csvs:
                    continue
                for name, data in _select_csvs(csvs):
                    try:
                        rows = parse_product_csv(data, info["code"], product, name)
                        if not rows:
                            logger.warning("EPRX %s %s: 0 rows parsed from %s",
                                           product, jfy, name)
                            continue
                        total += upsert_eprx(rows)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("EPRX parse %s (%s): %s", name, product, e)
            except Exception as e:  # noqa: BLE001
                logger.warning("EPRX fetch %s (%s): %s", url, product, e)
    return total


def _scrape_tieline(
    jfy_since: int | None = None,
    db_path: str | None = None,
    force: bool = False,
) -> int:
    total = 0
    for market in TIELINE_MARKETS:
        for jfy, url in _build_tieline_urls(market, jfy_since):
            try:
                csvs = _fetch_zip_csvs(url, db_path=db_path, force=force)
                if not csvs:
                    continue
                for name, data in _select_csvs(csvs):
                    try:
                        rows = parse_tieline_csv(data, market, name)
                        if not rows:
                            logger.warning("EPRX tieline %s %s: 0 rows parsed from %s",
                                           market, jfy, name)
                            continue
                        total += upsert_eprx_tieline(rows)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("EPRX tieline parse %s (%s): %s", name, market, e)
            except Exception as e:  # noqa: BLE001
                logger.warning("EPRX tieline fetch %s (%s): %s", url, market, e)
    return total


def scrape_eprx(db_path: str | None = None, force: bool = False) -> int:
    """Scrape all EPRX products for the current JFY range. Returns rows upserted."""
    n = _scrape_products(jfy_since=None, db_path=db_path, force=force)
    logger.info("EPRX balancing: upserted %d rows", n)
    return n


def scrape_eprx_tieline(db_path: str | None = None, force: bool = False) -> int:
    """Scrape EPRX tieline (DCM + DAM) for the current JFY range. Returns rows upserted."""
    n = _scrape_tieline(jfy_since=None, db_path=db_path, force=force)
    logger.info("EPRX tieline: upserted %d rows", n)
    return n


def scrape_eprx_range(jfy_since: int, db_path: str | None = None, force: bool = False) -> int:
    """Backfill EPRX products + tieline from *jfy_since* to current JFY.

    Returns total rows upserted across both balancing and tieline data.
    """
    n_prod = _scrape_products(jfy_since=jfy_since, db_path=db_path, force=force)
    n_tie = _scrape_tieline(jfy_since=jfy_since, db_path=db_path, force=force)
    total = n_prod + n_tie
    logger.info("EPRX backfill (JFY>=%d): %d balancing + %d tieline = %d rows",
                jfy_since, n_prod, n_tie, total)
    return total
