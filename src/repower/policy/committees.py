"""The tracked policy committees, as clean typed config.

Ported from the reference ``committee_tracker.csv`` (which is mojibake) and the
``OCCTO_COMMITTEES`` / ``EGC_COMMITTEES`` dicts in the reference scraper, with all
prior branding removed. URLs are taken verbatim from the tracker (authoritative);
Japanese names are re-typed as clean UTF-8.

Three site families, each with a different index structure (see ``scraper``):
- **METI** (``meti.go.jp``) — static HTML index linking ``NNN.html`` meeting subpages.
- **OCCTO** (``occto.or.jp``) — JS-rendered index; meetings probed at ``{base}/{N}.html``.
- **EGC** (``egc.meti.go.jp``) — HTML tables with direct PDF links + 配布資料 subpages.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Committee:
    """One tracked committee.

    ``max_meeting``/``prefix`` are OCCTO-only; ``log_pages``/``min_meeting`` are
    EGC-only. They default to empty/None for METI committees.
    """

    key: str
    name_ja: str
    name_en: str
    url: str
    source: str  # "METI" | "OCCTO" | "EGC"
    # Summarisation priority (lower = summarised first when the daily NotebookLM
    # quota is the binding constraint). Untagged committees share the default and
    # sort after the prioritised ones. See ``pending_meetings`` for how it's applied.
    priority: int = 100
    # OCCTO: cap the meeting-number probe; prefix for stable material ids.
    max_meeting: int | None = None
    prefix: str | None = None
    # EGC: historical log pages (newest first) + earliest meeting to consider.
    log_pages: tuple[str, ...] = field(default_factory=tuple)
    min_meeting: int | None = None

    @property
    def is_meti(self) -> bool:
        return self.source == "METI"

    @property
    def is_occto(self) -> bool:
        return self.source == "OCCTO"

    @property
    def is_egc(self) -> bool:
        return self.source == "EGC"


COMMITTEES: list[Committee] = [
    # ── METI (経済産業省) — static HTML indexes ──────────────────────────────
    Committee(
        key="system_review",
        name_ja="制度検討作業部会",
        name_en="System Review Working Group (balancing market design)",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/system_review/",
        source="METI",
        priority=1,  # top priority for the backfill/catch-up
    ),
    Committee(
        key="emissions_trading",
        name_ja="排出量取引制度小委員会",
        name_en="Emissions Trading Scheme Subcommittee",
        url="https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/emissions_trading/",
        source="METI",
        priority=2,
    ),
    Committee(
        key="emissions_trading_power",
        name_ja="排出量取引制度 発電部門ベンチマークワーキンググループ",
        name_en="ETS Power Generation Benchmark WG",
        url="https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/emissions_trading/power_generation_benchmark/",
        source="METI",
    ),
    Committee(
        key="emissions_trading_industry",
        name_ja="排出量取引制度 産業部門ベンチマークワーキンググループ",
        name_en="ETS Industrial Benchmark WG",
        url="https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/emissions_trading/benchmark_wg/",
        source="METI",
    ),
    Committee(
        key="saisei_kano",
        name_ja="再生可能エネルギー大量導入・次世代電力ネットワーク小委員会",
        name_en="Renewable Energy Mass Introduction Subcommittee",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saisei_kano/",
        source="METI",
    ),
    Committee(
        key="jisedai_kiban",
        name_ja="次世代電力基盤小委員会",
        name_en="Next-Generation Power Infrastructure Subcommittee",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/",
        source="METI",
    ),
    Committee(
        key="yojo_fuuryoku",
        name_ja="洋上風力促進ワーキンググループ",
        name_en="Offshore Wind Promotion WG",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saisei_kano/yojo_furyoku/index.html",
        source="METI",
    ),
    Committee(
        key="santeii",
        name_ja="調達価格等算定委員会",
        name_en="Procurement Price Calculation Committee (FIT/FIP)",
        url="https://www.meti.go.jp/shingikai/santeii/",
        source="METI",
    ),
    Committee(
        key="doji_shijo",
        name_ja="同時市場の在り方等に関する検討会",
        name_en="Simultaneous Market Study Group (co-optimised energy + reserves)",
        url="https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/",
        source="METI",
    ),
    Committee(
        key="saiene_shuryoku",
        name_ja="再生可能エネルギー主力電源化小委員会",
        name_en="Renewable Energy Main Power Source Subcommittee",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saiene_shuryoku/",
        source="METI",
    ),
    # ── OCCTO (電力広域的運営推進機関) — JS-rendered indexes, probe by number ──
    Committee(
        key="youryou_kentoukai",
        name_ja="容量市場の在り方等に関する検討会",
        name_en="Capacity Market Review Meeting",
        url="https://www.occto.or.jp/iinkai/youryou_kentoukai/",
        source="OCCTO",
        max_meeting=100,
        prefix="youryou_kentoukai",
    ),
    Committee(
        key="chousei_jukyu",
        name_ja="調整力及び需給バランス評価等に関する委員会",
        name_en="Balancing Capacity & Supply-Demand Evaluation Committee",
        url="https://www.occto.or.jp/iinkai/chousei_jukyu/",
        source="OCCTO",
        max_meeting=150,
        prefix="chousei_jukyu",
        priority=3,
    ),
    # ── EGC (電力・ガス取引監視等委員会) — HTML tables + 配布資料 subpages ──────
    Committee(
        key="emsc_system",
        name_ja="制度設計専門会合",
        name_en="Institutional Design Working Group",
        url="https://www.egc.meti.go.jp/activity/index_system.html",
        source="EGC",
        log_pages=(
            "index_systemlog9.html",  # meetings 84-95
            "index_systemlog8.html",  # meetings 72-83
            "index_systemlog7.html",  # meetings 59-71
            "index_systemlog6.html",  # meetings 47-58
            "index_systemlog5.html",  # meetings 37-46
            "index_systemlog4.html",  # meetings 29-36
        ),
        min_meeting=30,
    ),
    Committee(
        key="emsc_systemsurveillance",
        name_ja="制度設計・監視についての専門会合",
        name_en="Institutional Design & Surveillance Working Group",
        url="https://www.egc.meti.go.jp/activity/index_systemsurveillance.html",
        source="EGC",
    ),
]

_BY_KEY: dict[str, Committee] = {c.key: c for c in COMMITTEES}

# Base for resolving EGC historical log-page URLs (all EGC pages live here).
EGC_ACTIVITY_BASE = "https://www.egc.meti.go.jp/activity/"


def committee_by_key(key: str) -> Committee:
    """Return the committee with *key*, or raise ``KeyError`` if unknown."""
    return _BY_KEY[key]


def committee_keys() -> list[str]:
    return [c.key for c in COMMITTEES]


def committee_priority(key: str) -> int:
    """Summarisation priority for *key* (lower = summarised first).

    Unknown keys fall back to the default so they sort after prioritised ones.
    """
    c = _BY_KEY.get(key)
    return c.priority if c else 100
