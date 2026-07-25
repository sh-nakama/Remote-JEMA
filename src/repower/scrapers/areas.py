"""Per-region area supply/demand scrapers built on BaseAreaScraper.

URL patterns and column orders verified empirically against published CSVs
during framework bring-up. Two canonical formats are observed across mainland
TSOs:

* **20-col legacy**: TEPCO, Kansai, Shikoku
* **22-col 2024+ standard**: Hokkaido, Tohoku, Chubu, Hokuriku
  (adds 火力出力制御量 and バイオマス出力制御量 columns)

Both layouts are registered per scraper via ``COLUMN_ORDERS_BY_NCOLS`` so the
framework auto-selects based on the actual file shape.

Kyushu (Kyuden) and Chugoku (Energia) URL patterns are still under
investigation; placeholder URL templates are present and will fail-soft until
verified.
"""

from __future__ import annotations

from repower.scrapers.area_base import BaseAreaScraper

LEGACY_20: list[str] = [
    "date", "time", "area_demand_mw",
    "nuclear", "lng", "coal", "oil", "thermal_other",
    "hydro", "geothermal", "biomass",
    "solar_actual", "solar_curtail",
    "wind_actual", "wind_curtail",
    "pumped", "battery", "interconnect", "other", "total_supply",
]

NEW_22: list[str] = [
    "date", "time", "area_demand_mw",
    "nuclear", "lng", "coal", "oil", "thermal_other",
    "skip",  # 火力出力制御量
    "hydro", "geothermal", "biomass",
    "skip",  # バイオマス出力制御量
    "solar_actual", "solar_curtail",
    "wind_actual", "wind_curtail",
    "pumped", "battery", "interconnect", "other", "total_supply",
]

DUAL_FORMAT = {20: LEGACY_20, 22: NEW_22}


class TepcoScraper(BaseAreaScraper):
    AREA = "tepco"
    URL_TEMPLATES = [
        "https://www.tepco.co.jp/forecast/html/images/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ENCODING = "utf-8"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


class HokkaidoScraper(BaseAreaScraper):
    AREA = "hokkaido"
    URL_TEMPLATES = [
        "https://www.hepco.co.jp/network/con_service/public_document/supply_demand_results/csv/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ENCODING = "utf-8-sig"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


class TohokuScraper(BaseAreaScraper):
    AREA = "tohoku"
    URL_TEMPLATES = [
        "https://setsuden.nw.tohoku-epco.co.jp/common/demand/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ENCODING = "utf-8-sig"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


class ChubuScraper(BaseAreaScraper):
    """Chuden (Chubu TSO).

    Live monthly URL serves only the current and previous month at the
    standard ``denki_yoho_content_data/eria_jukyu_{YYYYMM}_{V}.csv`` path.
    Historical months are bundled into yearly ZIPs at
    ``denki_yoho_content_data/eria_jukyu_{YYYY}.zip`` (one CSV per month
    inside, fiscal-year layout: e.g. the 2024 ZIP covers Apr 2024 \u2192 Mar 2025).
    The framework auto-uses the archive for ``months_back >= 2``.
    """
    AREA = "chubu"
    URL_TEMPLATES = [
        "https://powergrid.chuden.co.jp/denki_yoho_content_data/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ARCHIVE_URL_TEMPLATE = "https://powergrid.chuden.co.jp/denki_yoho_content_data/eria_jukyu_{YYYY}.zip"
    ENCODING = "shift_jis"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT

    def _archive_year_for(self, year: int, month: int) -> int:
        # Chubu's yearly ZIPs use Japanese fiscal year (Apr\u2013Mar).
        # e.g. eria_jukyu_2024.zip covers Apr 2024 \u2192 Mar 2025.
        return year if month >= 4 else year - 1


class HokurikuScraper(BaseAreaScraper):
    AREA = "hokuriku"
    URL_TEMPLATES = [
        "https://www.rikuden.co.jp/nw/denki-yoho/csv/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ENCODING = "utf-8-sig"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


class KansaiScraper(BaseAreaScraper):
    AREA = "kansai"
    URL_TEMPLATES = [
        "https://www.kansai-td.co.jp/interchange/denkiyoho/area-performance/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ENCODING = "utf-8-sig"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


class ChugokuScraper(BaseAreaScraper):
    """Energia (Chugoku TSO). Fixed URL: ``sys/eria_jukyu_{YYYYMM}_07.csv``.

    Pattern reverse-engineered from ``js/script_eriajukyu_1.js`` on the public
    eria_jukyu page; ``_07`` is hard-coded in the JS and confirmed available
    monthly from 2024-04 onward.
    """
    AREA = "chugoku"
    URL_TEMPLATES = [
        "https://www.energia.co.jp/nw/jukyuu/sys/eria_jukyu_{YYYY}{MM}_07.csv",
    ]
    ENCODING = "utf-8-sig"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


class ShikokuScraper(BaseAreaScraper):
    AREA = "shikoku"
    URL_TEMPLATES = [
        "https://www.yonden.co.jp/nw/supply_demand/csv/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ENCODING = "utf-8-sig"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


class KyushuScraper(BaseAreaScraper):
    """Kyuden (Kyushu TSO). Fixed URL: ``csv/eria_jukyu_{YYYYMM}_09.csv``.

    Pattern observed via the public download page; ``_09`` is the active
    suffix and confirmed available monthly from 2024-04 onward. The current
    month's file is updated continuously and contains rows up to the latest
    half-hour.
    """
    AREA = "kyushu"
    URL_TEMPLATES = [
        "https://www.kyuden.co.jp/td_area_jukyu/csv/eria_jukyu_{YYYY}{MM}_09.csv",
    ]
    ENCODING = "shift_jis"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


ALL_SCRAPERS: list[type[BaseAreaScraper]] = [
    TepcoScraper, HokkaidoScraper, TohokuScraper, ChubuScraper,
    HokurikuScraper, KansaiScraper, ChugokuScraper, ShikokuScraper, KyushuScraper,
]

AREA_NAMES: dict[str, str] = {
    "tepco": "Tokyo (TEPCO)",
    "hokkaido": "Hokkaido (HEPCO)",
    "tohoku": "Tohoku",
    "chubu": "Chubu (Chuden)",
    "hokuriku": "Hokuriku (Rikuden)",
    "kansai": "Kansai",
    "chugoku": "Chugoku (Energia)",
    "shikoku": "Shikoku (Yonden)",
    "kyushu": "Kyushu (Kyuden)",
}


def scrape_all_areas(months_back: int = 1, db_path: str | None = None) -> dict[str, int]:
    """Scrape every TSO sequentially. Returns {area: rows_upserted}."""
    results: dict[str, int] = {}
    for cls in ALL_SCRAPERS:
        scraper = cls()
        try:
            results[scraper.AREA] = scraper.scrape(months_back=months_back, db_path=db_path)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).error("[%s] scraper crashed: %s", scraper.AREA, e)
            results[scraper.AREA] = 0
    return results


def scrape_area(area: str, months_back: int = 1, db_path: str | None = None) -> int:
    for cls in ALL_SCRAPERS:
        if cls.AREA == area:
            return cls().scrape(months_back=months_back, db_path=db_path)
    raise ValueError(f"Unknown area: {area}. Valid: {list(AREA_NAMES)}")


def recover_missing_months(lookback: int = 6, db_path: str | None = None) -> list[dict]:
    """Re-ingest completed months that are entirely absent from the DB.

    A parse failure or a stale ``304`` cache entry can leave a month with zero
    rows in ``demand_supply_30m`` even though the upstream CSV is fine — and the
    normal incremental scrape then 304-skips that month forever. For each area,
    scan the last ``lookback`` *completed* months (the current, partial month is
    skipped); when a month has no rows, drop its cache validators so the fetch
    re-downloads (200), then parse/upsert it. Months still unpublished upstream
    (404) or already present are left untouched. Returns one dict per recovered
    month: ``{"area", "month", "rows"}``.
    """
    import logging
    from datetime import date as _date

    from sqlalchemy import func, select

    from repower.db import DemandSupply30m, get_session, init_db
    from repower.scrapers.area_base import _UNCHANGED
    from repower.scrapers.http_cache import invalidate
    from repower.timeutil import today_jst

    log = logging.getLogger(__name__)
    today = today_jst()
    targets: list[tuple[int, int]] = []
    for off in range(1, lookback + 1):  # offset 0 = current (partial) month — skip
        m, y = today.month - off, today.year
        while m <= 0:
            m += 12
            y -= 1
        targets.append((y, m))

    init_db(db_path)
    recovered: list[dict] = []
    for cls in ALL_SCRAPERS:
        scraper = cls()
        for y, m in targets:
            ym = f"{y:04d}-{m:02d}"
            start = _date(y, m, 1)
            end = _date(y + 1, 1, 1) if m == 12 else _date(y, m + 1, 1)
            session = get_session(db_path)
            try:
                n_rows = session.execute(
                    select(func.count()).select_from(DemandSupply30m).where(
                        DemandSupply30m.area == scraper.AREA,
                        DemandSupply30m.date >= start,
                        DemandSupply30m.date < end,
                    )
                ).scalar_one()
            finally:
                session.close()
            if n_rows:
                continue  # month present — nothing to recover
            for url in scraper.csv_urls(y, m):  # drop stale validators so the fetch re-downloads
                invalidate(url, db_path=db_path)
            try:
                df = scraper.fetch_csv(y, m, db_path=db_path)
            except Exception as e:  # noqa: BLE001 — one bad month must not abort the sweep
                log.warning("[%s] recover %s: fetch error %s", scraper.AREA, ym, e)
                continue
            if df is None or df is _UNCHANGED:
                continue  # not published upstream (404) or nothing to do
            try:
                n = scraper.upsert(scraper.parse(df), db_path)
            except Exception as e:  # noqa: BLE001
                log.error("[%s] recover %s: parse/upsert failed %s", scraper.AREA, ym, e)
                continue
            if n:
                log.info("[%s] recovered %s: %d rows", scraper.AREA, ym, n)
                recovered.append({"area": scraper.AREA, "month": ym, "rows": n})
    return recovered
