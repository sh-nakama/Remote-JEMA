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
    AREA = "chubu"
    URL_TEMPLATES = [
        "https://powergrid.chuden.co.jp/denki_yoho_content_data/eria_jukyu_{YYYY}{MM}_{V}.csv",
    ]
    ENCODING = "utf-8-sig"
    COLUMN_ORDERS_BY_NCOLS = DUAL_FORMAT


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
