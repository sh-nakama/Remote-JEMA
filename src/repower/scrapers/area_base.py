"""Generic framework for Japanese TSO area supply/demand CSV scrapers.

All 9 mainland TSOs publish monthly 30-min (or hourly) CSVs with broadly the
same shape. Each region only needs to declare:

    AREA            slug used as DB key (e.g. "kansai")
    URL_TEMPLATE    string with {YYYY}{MM} placeholders
    ENCODING        "utf-8" | "utf-8-sig" | "shift_jis" | "cp932"
    SKIP_ROWS       rows to skip before the header row
    HEADER_ROW      header row index *after* skipping (usually 0)
    COLUMN_MAP      dict {csv_position: canonical_field} OR list of canonical
                    fields in CSV positional order ("skip" to ignore a column)
    GRANULARITY     "30min" | "hourly"
    EXTRA_URLS      optional list of fallback URL templates

Subclasses may override `transform(df)` for region-specific quirks
(sign flips, hourly→30min upsampling, missing fuel splits, etc.).
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date
from typing import ClassVar, Optional

import httpx
import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from repower.db import DemandSupply30m, get_session, init_db

logger = logging.getLogger(__name__)

# Canonical numeric fields written to demand_supply_30m
SUPPLY_FIELDS: list[str] = [
    "area_demand_mw",
    "nuclear", "lng", "coal", "oil", "thermal_other",
    "hydro", "geothermal", "biomass",
    "solar_actual", "solar_curtail",
    "wind_actual", "wind_curtail",
    "pumped", "battery", "interconnect", "other", "total_supply",
]


class BaseAreaScraper:
    AREA: ClassVar[str] = ""
    URL_TEMPLATES: ClassVar[list[str]] = []
    # Optional yearly ZIP archive (with {YYYY}) containing per-month CSVs named
    # like ``eria_jukyu_{YYYYMM}_*.csv``. Used by ``scrape()`` for historical
    # months when ``months_back > 1``. Falls back to URL_TEMPLATES if unset or
    # the archive does not contain a given month.
    ARCHIVE_URL_TEMPLATE: ClassVar[str] = ""
    # If a template contains {V}, the scraper probes _01.._09 (descending) at that slot.
    VERSION_RANGE: ClassVar[tuple[int, int]] = (1, 12)
    ENCODING: ClassVar[str] = "utf-8-sig"
    SKIP_ROWS: ClassVar[int] = 1
    HEADER_ROW: ClassVar[int] = 0
    # Column orders keyed by CSV column count. The framework picks the entry whose
    # key matches len(df.columns) at parse time. Fallback: COLUMN_ORDER (legacy single-format).
    COLUMN_ORDERS_BY_NCOLS: ClassVar[dict[int, list[str]]] = {}
    COLUMN_ORDER: ClassVar[list[str]] = []
    GRANULARITY: ClassVar[str] = "30min"

    def csv_urls(self, year: int, month: int) -> list[str]:
        ym = {"YYYY": str(year), "MM": f"{month:02d}"}
        urls: list[str] = []
        for tpl in self.URL_TEMPLATES:
            if "{V}" in tpl:
                lo, hi = self.VERSION_RANGE
                for v in range(hi, lo - 1, -1):
                    urls.append(tpl.format(V=f"{v:02d}", **ym))
            else:
                urls.append(tpl.format(**ym))
        return urls

    def fetch_csv(self, year: int, month: int) -> Optional[pd.DataFrame]:
        last_err: Exception | None = None
        # Some TSO sites (e.g. Kyuden) reject requests without a browser UA.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        }
        for url in self.csv_urls(year, month):
            try:
                raw = _http_get(url, headers=headers)
                if raw is None:  # 404 → try next URL
                    continue
                logger.info("[%s] fetched %s", self.AREA, url)
                df = self._bytes_to_df(raw)
                if df.empty:
                    raise ValueError("empty CSV")
                return df
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning("[%s] %s -> %s", self.AREA, url, e)
        if last_err:
            logger.error("[%s] all URLs failed for %04d-%02d: %s", self.AREA, year, month, last_err)
        return None

    def _bytes_to_df(self, raw: bytes) -> pd.DataFrame:
        """Decode raw CSV bytes (using ``ENCODING``) and parse to a DataFrame."""
        # Strip BOM if present even when encoding declared utf-8-sig
        if raw[:3] == b"\xef\xbb\xbf":
            raw = raw[3:]
        text_data = raw.decode(self.ENCODING, errors="replace")
        return pd.read_csv(
            io.StringIO(text_data),
            skiprows=self.SKIP_ROWS,
            header=self.HEADER_ROW,
        )

    def _archive_year_for(self, year: int, month: int) -> int:
        """Map a (year, month) target to the archive year that contains it.

        Default: calendar year. Override for fiscal-year archives (e.g. Chubu's
        yearly ZIP for fiscal 2024 spans Apr 2024 \u2192 Mar 2025).
        """
        return year

    def fetch_archive_year(self, year: int) -> dict[tuple[int, int], pd.DataFrame]:
        """Download the yearly ZIP archive and return ``{(year, month): df}``.

        Returns an empty dict if ``ARCHIVE_URL_TEMPLATE`` is unset or fetch fails.
        Member CSVs are matched against ``eria_jukyu_(YYYY)(MM)_*.csv``.
        """
        if not self.ARCHIVE_URL_TEMPLATE:
            return {}
        url = self.ARCHIVE_URL_TEMPLATE.format(YYYY=str(year))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        }
        try:
            raw = _http_get(url, headers=headers)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] archive %s -> %s", self.AREA, url, e)
            return {}
        if raw is None or raw[:2] != b"PK":
            logger.info("[%s] no archive at %s", self.AREA, url)
            return {}
        logger.info("[%s] fetched archive %s (%d bytes)", self.AREA, url, len(raw))
        out: dict[tuple[int, int], pd.DataFrame] = {}
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as e:
            logger.warning("[%s] bad zip from %s: %s", self.AREA, url, e)
            return {}
        pat = re.compile(r"eria_jukyu_(\d{4})(\d{2})", re.IGNORECASE)
        for name in zf.namelist():
            m = pat.search(name)
            if not m:
                continue
            y, mo = int(m.group(1)), int(m.group(2))
            try:
                with zf.open(name) as f:
                    df = self._bytes_to_df(f.read())
                if not df.empty:
                    out[(y, mo)] = df
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] archive member %s parse failed: %s", self.AREA, name, e)
        return out

    def parse(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply positional column mapping → canonical fields."""
        ncols = len(df.columns)
        order = self.COLUMN_ORDERS_BY_NCOLS.get(ncols) or self.COLUMN_ORDER
        if not order:
            raise ValueError(f"[{self.AREA}] no column order registered for {ncols} columns")
        if ncols < len(order):
            logger.warning("[%s] CSV has %d cols, expected >=%d; truncating mapping",
                           self.AREA, ncols, len(order))
            order = order[:ncols]
        # Rename positionally; ignore extra columns
        rename_map = {}
        for idx, name in enumerate(order):
            if name and name != "skip":
                rename_map[df.columns[idx]] = name
        df = df.rename(columns=rename_map)
        # Drop unmapped columns
        keep = [c for c in df.columns if c in {"date", "time", *SUPPLY_FIELDS}]
        df = df[keep].copy()

        # Parse date — accept YYYY/M/D, YYYY-MM-DD, YYYYMMDD (e.g. Kyuden), etc.
        date_str = df["date"].astype(str).str.strip()
        # If everything looks like 8-digit YYYYMMDD, parse with explicit format.
        if date_str.str.fullmatch(r"\d{8}").all():
            df["date"] = pd.to_datetime(date_str, format="%Y%m%d", errors="coerce").dt.date
        else:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

        # Normalize time strings to "HH:MM"
        df["time"] = df["time"].astype(str).str.strip()
        df["time"] = df["time"].apply(_normalize_hhmm)

        # Numeric coercion for present supply fields
        for col in SUPPLY_FIELDS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["date", "time"]).reset_index(drop=True)
        df = self.transform(df)
        return df

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Hook for region-specific post-processing."""
        return df

    def upsert(self, df: pd.DataFrame, db_path: str | None = None) -> int:
        if df.empty:
            return 0
        init_db(db_path)
        session = get_session(db_path)
        n = 0
        try:
            for _, row in df.iterrows():
                values = {"area": self.AREA, "date": row["date"], "time": row["time"]}
                for col in SUPPLY_FIELDS:
                    if col in df.columns:
                        v = row[col]
                        values[col] = None if pd.isna(v) else float(v)
                stmt = sqlite_upsert(DemandSupply30m).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["area", "date", "time"],
                    set_={k: stmt.excluded[k] for k in values if k not in {"area", "date", "time"}},
                )
                session.execute(stmt)
                n += 1
            session.commit()
        finally:
            session.close()
        return n

    def scrape(self, months_back: int = 1, db_path: str | None = None) -> int:
        today = date.today()
        targets: list[tuple[int, int]] = []
        for off in range(months_back + 1):
            m = today.month - off
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            targets.append((y, m))

        # If a yearly archive is configured and we need more than ~2 months,
        # bulk-pull from yearly ZIPs first (one HTTP request per year covers
        # 12 months), then overlay live monthly fetches for the most recent
        # 2 months so we always have the freshest data for the current month.
        archive_dfs: dict[tuple[int, int], pd.DataFrame] = {}
        if self.ARCHIVE_URL_TEMPLATE and months_back >= 2:
            years_needed = sorted({self._archive_year_for(y, m) for y, m in targets})
            for yr in years_needed:
                archive_dfs.update(self.fetch_archive_year(yr))

        # Live months override archive content for the trailing 2 months.
        live_months = set(targets[: min(2, len(targets))])

        total = 0
        for y, m in targets:
            df: pd.DataFrame | None = None
            if (y, m) in live_months:
                df = self.fetch_csv(y, m)
            if df is None and (y, m) in archive_dfs:
                df = archive_dfs[(y, m)]
                logger.info("[%s] %04d-%02d: using archive copy", self.AREA, y, m)
            if df is None:
                df = self.fetch_csv(y, m)
            if df is None:
                continue
            try:
                parsed = self.parse(df)
                n = self.upsert(parsed, db_path)
                logger.info("[%s] %04d-%02d: upserted %d rows", self.AREA, y, m, n)
                total += n
            except Exception as e:  # noqa: BLE001
                logger.error("[%s] %04d-%02d parse/upsert failed: %s", self.AREA, y, m, e)
        return total


# ─────────────────────────────────────────────────────────────────────────
# HTTP layer with anti-bot fallback
#
# Some TSO sites (notably Kyuden via Akamai) reject plain Python TLS
# fingerprints with HTTP 403. We try fast `httpx` first; on 403 we retry
# with `curl_cffi` which impersonates a real Chrome TLS+JA3 fingerprint.
# `curl_cffi` is an optional dependency — we degrade gracefully if absent.
# ─────────────────────────────────────────────────────────────────────────

def _http_get(url: str, headers: dict | None = None) -> Optional[bytes]:
    """Return response bytes, or None on 404. Raises on other errors."""
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True, headers=headers)
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            # Try anti-bot fallback
            blob = _http_get_curl_cffi(url, headers)
            if blob is not None:
                return blob
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPStatusError:
        raise
    except Exception:
        # Network glitch — try curl_cffi once before giving up
        blob = _http_get_curl_cffi(url, headers)
        if blob is not None:
            return blob
        raise


def _http_get_curl_cffi(url: str, headers: dict | None = None) -> Optional[bytes]:
    """Fetch via curl_cffi with Chrome impersonation. Returns None if unavailable."""
    try:
        from curl_cffi import requests as cr  # type: ignore
    except Exception:
        return None
    try:
        r = cr.get(url, impersonate="chrome", timeout=30, headers=headers or {})
        if r.status_code == 404:
            return None
        if 200 <= r.status_code < 300:
            logger.info("curl_cffi succeeded for %s", url)
            return r.content
    except Exception as e:  # noqa: BLE001
        logger.debug("curl_cffi fallback failed for %s: %s", url, e)
    return None


def _normalize_hhmm(s: str) -> str | None:
    if not s or s == "nan":
        return None
    s = s.strip()
    # Accept "9:00", "09:00", "9:0", etc.
    if ":" in s:
        try:
            h, mn = s.split(":", 1)
            return f"{int(h):02d}:{int(mn):02d}"
        except ValueError:
            return None
    # Accept "0900"
    if s.isdigit() and len(s) in (3, 4):
        s = s.zfill(4)
        return f"{s[:2]}:{s[2:]}"
    return None


def hourly_to_30min(df: pd.DataFrame) -> pd.DataFrame:
    """Duplicate each hourly row into two 30-min slots (HH:00 and HH:30)."""
    if df.empty:
        return df
    df_a = df.copy()
    df_b = df.copy()
    df_b["time"] = df_b["time"].str[:2] + ":30"
    out = pd.concat([df_a, df_b], ignore_index=True)
    return out.sort_values(["date", "time"]).reset_index(drop=True)
