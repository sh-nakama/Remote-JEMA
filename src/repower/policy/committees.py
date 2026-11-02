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
    # OCCTO: cap the meeting-number probe. ``prefix`` (the URL slug) is currently
    # unused config — material ids are derived from meeting number + URL stem
    # (see ``scraper.material_id``) — retained so the DB registry round-trips it.
    max_meeting: int | None = None
    prefix: str | None = None
    # EGC: historical log pages (newest first) + earliest meeting to consider.
    log_pages: tuple[str, ...] = field(default_factory=tuple)
    min_meeting: int | None = None
    # Curated topic tags (keys of ``repower.policy.tags``): the committee's *standing
    # mandate*. ``None`` = no curated opinion, so tags come from the name and from what
    # its meetings turn out to discuss; ``()`` would assert "none". Only set where the
    # mandate is unambiguous — an over-broad curated list defeats the filter.
    tags: tuple[str, ...] | None = None

    @property
    def is_meti(self) -> bool:
        return self.source == "METI"

    @property
    def is_occto(self) -> bool:
        return self.source == "OCCTO"

    @property
    def is_egc(self) -> bool:
        return self.source == "EGC"


# Curated topic-tag sets shared by more than one committee (keys of ``repower.policy.tags``).
# Renewable generation + the schemes that pay for it (FIT/FIP price-setting bodies).
_RENEWABLE_SUPPORT_TAGS = (
    "solar_utility", "solar_rooftop", "wind_onshore", "wind_offshore",
    "hydro_geothermal", "biomass", "support_fit_fip",
)
# Mass-introduction of renewables: the generation that matters most for the grid, and
# the grid questions it raises.
_RENEWABLE_GRID_TAGS = (
    "solar_utility", "solar_rooftop", "wind_offshore",
    "grid_planning", "grid_connection", "grid_curtailment", "grid_cost", "support_fit_fip",
)

COMMITTEES: list[Committee] = [
    # ── METI (経済産業省) — static HTML indexes ──────────────────────────────
    Committee(
        key="system_review",
        name_ja="制度検討作業部会",
        name_en="System Review Working Group",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/system_review/",
        source="METI",
        priority=1,  # top priority for the backfill/catch-up
    ),
    Committee(
        key="emissions_trading",
        name_ja="排出量取引制度小委員会",
        name_en="Emissions Trading System Subcommittee",
        url="https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/emissions_trading/",
        source="METI",
        priority=2,
    ),
    Committee(
        key="emissions_trading_power",
        name_ja="発電ベンチマーク検討ワーキンググループ",
        name_en="ETS Power Generation Benchmark Working Group",
        url="https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/emissions_trading/power_generation_benchmark/",
        source="METI",
    ),
    Committee(
        key="emissions_trading_industry",
        name_ja="製造業ベンチマーク検討ワーキンググループ",
        name_en="ETS Manufacturing Benchmark Working Group",
        url="https://www.meti.go.jp/shingikai/sankoshin/sangyo_gijutsu/emissions_trading/benchmark_wg/",
        source="METI",
    ),
    Committee(
        key="saisei_kano",
        name_ja="再生可能エネルギー大量導入・次世代電力ネットワーク小委員会",
        name_en="Subcommittee on Mass Introduction of Renewables and Next-Generation Power Networks",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saisei_kano/",
        source="METI",
        tags=_RENEWABLE_GRID_TAGS,
    ),
    Committee(
        key="jisedai_kiban",
        name_ja="次世代電力・ガス事業基盤構築小委員会",
        name_en="Next-Generation Electricity and Gas Business Foundation Subcommittee",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/",
        source="METI",
    ),
    Committee(
        key="yojo_fuuryoku",
        name_ja="洋上風力促進ワーキンググループ",
        name_en="Offshore Wind Promotion Working Group",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saisei_kano/yojo_furyoku/index.html",
        source="METI",
        tags=("wind_offshore",),
    ),
    Committee(
        key="santeii",
        name_ja="調達価格等算定委員会",
        name_en="Procurement Price Calculation Committee (FIT/FIP)",
        url="https://www.meti.go.jp/shingikai/santeii/",
        source="METI",
        tags=_RENEWABLE_SUPPORT_TAGS,
    ),
    Committee(
        key="doji_shijo",
        name_ja="同時市場の在り方等に関する検討会",
        name_en="Study Group on a Simultaneous Market",
        url="https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/",
        source="METI",
    ),
    Committee(
        key="saiene_shuryoku",
        name_ja="再生可能エネルギー主力電源化小委員会",
        name_en="Subcommittee on Making Renewables a Main Power Source",
        url="https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saiene_shuryoku/",
        source="METI",
        tags=_RENEWABLE_SUPPORT_TAGS,
    ),
    # ── OCCTO (電力広域的運営推進機関) — JS-rendered indexes, probe by number ──
    Committee(
        key="youryou_kentoukai",
        name_ja="容量市場の在り方等に関する検討会",
        name_en="Study Group on the Capacity Market",
        url="https://www.occto.or.jp/iinkai/youryou_kentoukai/",
        source="OCCTO",
        max_meeting=100,
        prefix="youryou_kentoukai",
    ),
    Committee(
        key="chousei_jukyu",
        name_ja="調整力及び需給バランス評価等に関する委員会",
        name_en="Committee on Balancing Capacity and Supply-Demand Evaluation",
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
        name_en="System Design Expert Panel",
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
        name_en="Expert Panel on System Design and Surveillance",
        url="https://www.egc.meti.go.jp/activity/index_systemsurveillance.html",
        source="EGC",
    ),
]

_BY_KEY: dict[str, Committee] = {c.key: c for c in COMMITTEES}

# English names for the committees the catalog discovers (``repower.policy.catalog``),
# which arrive with only a Japanese name. Keyed by committee key, translated from the
# Japanese name. Conventions, shared with ``COMMITTEES`` above: the parent-council
# chain (総合資源エネルギー調査会 …) is dropped and only the committee itself named;
# 小委員会 Subcommittee · 委員会 Committee · 分科会 Committee (METI's own usage) ·
# 作業部会/WG Working Group · 専門会合 Expert Panel · 検討会/研究会 Study Group ·
# 勉強会 Study Session · 作業会 Task Force · 会議/協議会 Council.
CATALOG_NAMES_EN: dict[str, str] = {
    # ── EGC ──
    "emsc_decarbonization": "Study Group on Monitoring Other-Market Revenue in the Long-Term Decarbonisation Auction",
    "emsc_electricity": "Tariff System Expert Panel",
    "emsc_electricityreview": "Tariff Review Expert Panel",
    "emsc_emsc": "Electricity and Gas Market Surveillance Commission",
    "emsc_emscverification": "Review of the Electricity and Gas Market Surveillance Commission",
    "emsc_feesystemwg": "Tariff System Working Group",
    "emsc_imbalance": "Study Group on Overseas Imbalance Pricing and Network Regulation",
    "emsc_keika": "Expert Panel on Transitional Regulated Electricity Tariffs",
    "emsc_kensho": "Expert Panel on Reviewing the Market Surveillance Commission",
    "emsc_localdemand": "Study Group on Localised Demand Growth and the Power Network",
    "emsc_network": "Working Group on Allocating Network Maintenance and Operating Costs",
    "emsc_optimize": "Network Efficiency and Plan Progress Review Working Group",
    "emsc_studygroup": "Study Group on Competitive Electricity and Gas Markets",
    "emsc_tender": "Thermal Power Tender Expert Panel",
    # ── METI ──
    "biomass_sus_wg": "Biomass Sustainability Working Group",
    "carbon_dioxide": "Study Group on Evaluating CO2 Geological Storage",
    "carbon_dioxide_2": "CO2 Storage Business Safety Subcommittee",
    "ccs_business_system": "CCS Business Framework Working Group",
    "choki_energy": "Long-Term Energy Supply and Demand Outlook Subcommittee",
    "chuchoki_torihiki": "Mid- to Long-Term Trading Market Working Group",
    "datsu_tansoka": "Subcommittee on Power Resilience for a Decarbonised Society",
    "denki_ryokin": "Electricity Tariff Review Subcommittee",
    "denki_setsubi": "Working Group on Natural Disaster Measures for Electrical Facilities",
    "denryoku_anzen": "Electrical Safety Subcommittee",
    "denryoku_gas": "Electricity and Gas Industry Committee",
    "denryoku_gas_2": "Electricity and Gas Basic Policy Subcommittee",
    "denryoku_jukyu": "Electricity Supply-Demand Verification Subcommittee",
    "denryoku_kaikaku": "Policy Subcommittee on Completing Electricity System Reform",
    "denryoku_kihon": "Electricity Basic Policy Subcommittee",
    "denryoku_system": "Electricity System Reform Subcommittee",
    "distributed_energy_wg": "Distributed Energy Promotion Strategy Working Group",
    "dr_ready": "DR Ready Study Session",
    "ekika_sekiyu": "LPG Distribution Working Group",
    "ekika_sekiyu_2": "LPG Subcommittee",
    "electric_power_wg": "Electricity Business Environment Working Group",
    "energy_structure": "Energy Structure Transformation Working Group (Green Innovation)",
    "fukui_kyosokaigi": "Co-Creation Council on the Future of Fukui's Nuclear Host Communities",
    "fukushima_shinene": "Council for the Fukushima New Energy Society Vision",
    "gas_business_wg": "Gas Business Environment Working Group",
    "gas_system": "Gas System Reform Subcommittee",
    "genshiryoku": "Nuclear Energy Subcommittee",
    "industrial_restructuring": "Industrial Structure Transformation Working Group (Green Innovation)",
    "kosokuro_kaihatsu_wg": "Fast Reactor Development Council Strategy Working Group",
    "mining": "Mining Subcommittee",
    "nenryo_seisaku": "Decarbonised Fuels Policy Subcommittee",
    "next_generation_gas": "Public-Private Council for Next-Generation Gas",
    "ninushi_wg": "Working Group on Energy-Efficiency Standards for Shippers",
    "occto": "OCCTO Review Working Group",
    "plastic_wg": "Plastic Resource Circulation Strategy Working Group",
    "radioactive_waste": "Specified Radioactive Waste Subcommittee",
    "saisei_kano_2": "Subcommittee on Reforming Renewable Energy Promotion Schemes",
    "sekiyu_gas": "Resource Development and Fuel Supply Subcommittee",
    "shigen_nenryo": "Natural Resources and Fuel Committee",
    "shin_energy": "New Energy Subcommittee",
    "sho_energy": "Energy Efficiency Subcommittee",
    "shoene_shinene": "Energy Efficiency and Renewable Energy Committee",
    "smart_power_grid_wg": "Next-Generation Power Grid Working Group",
    "sokai": "Industrial Structure Council General Assembly",
    "solar_cells_reinforcement": "Liaison Council on Deploying Next-Generation Solar Cells",
    "solar_panel_waste": "Study Group on Regulations under the Solar Panel Recycling Act",
    "solar_power_generation": "Solar Equipment Recycling Working Group",
    "stable_power_supply_wg": "Stable Power Supply Working Group",
    "supply_structure": "Working Group on Strengthening Oil Supply Resilience",
    "transition_finance": "Study Group on the Transition Finance Environment",
    "wg_denryoku": "Cybersecurity Study Group: Electricity Sub-Working Group",
    # ── OCCTO ──
    "chiikikan_rule": "Study Group on Interconnector Usage Rules",
    "chinai_rule": "Study Group on Interconnector and Intra-Area Grid Usage Rules",
    "chousei_sagyoukai": "Task Force on Balancing Product Segmentation and Cross-Regional Procurement",
    "chouseiryoku": "Balancing Capacity Committee",
    "chouseiryoku_jizoku": "Study Session on Sustained Demand Fluctuation",
    "gridcode": "Grid Code Study Group",
    "hokkaido_kensho": "Review Committee on the 2018 Hokkaido Eastern Iburi Earthquake Blackout",
    "jukyuchousei": "Balancing Market Subcommittee",
    "koikisys_chuchoki": "Study Group on the OCCTO System Mid- to Long-Term Plan",
    "koikisys_daisansha": "Third-Party Evaluation Committee on OCCTO System Development",
    "konzatsu": "Study Session on Intra-Area Grid Congestion Management",
    "kouikikeitouseibi": "Cross-Regional Grid Development Committee",
    "kouikikeitouseibi_access": "Task Force on Efficient Grid Access Procedures",
    "kouikikeitouseibi_cost": "Cost Verification Subcommittee",
    "kouikikeitouseibi_hyouka": "Plan Evaluation and Verification Subcommittee",
    "kouikikeitouseibi_resilience": "Power Resilience Subcommittee",
    "margin_kentoukai": "Interconnector Margin Study Group",
    "masutapuran": "Committee on the Cross-Regional Grid Master Plan and Usage Rules",
    "negawatt_jitsumusha": "Practitioners' Meeting on Negawatt Trading",
    "shorai_jukyu": "Study Group on Future Electricity Supply-Demand Scenarios",
    "sw_shien_jitsumusha": "Practitioners' Meeting on Supplier Switching Support",
    "unei": "OCCTO Steering Committee",
    "unyouyouryou": "Transfer Capability Study Group",
    "unyouyouryou_sagyoukai": "Task Force on Future Transfer Capability",
    "youryou_benkyoukai": "Study Session on the Capacity Market",
}


# Japanese names of discovered committees that were stored wrong, checked against the
# committee page's own <h1>. The energy-board backup used to name a committee after its
# feed's council label, which can be a parent body or a truncated name.
# ``store.sync_committees`` writes these over the stored value.
CATALOG_NAMES_JA: dict[str, str] = {
    "distributed_energy_wg": "分散型エネルギー推進戦略ワーキンググループ",  # was 省エネルギー小委員会
    "plastic_wg": "プラスチック資源循環戦略ワーキンググループ",  # was 戦略ワーキンググループ
}


def english_name(key: str, stored: str | None = None) -> str:
    """The committee's English name, or ``""`` when there is none.

    Curated names win (``COMMITTEES``, then ``CATALOG_NAMES_EN``), so a corrected
    translation reaches every reader without a DB write; a name stored on the row
    (typed when a committee was added by hand) comes next. A stored value equal to
    the key is the old "no name" placeholder, not a name.
    """
    c = _BY_KEY.get(key)
    if c is not None:
        return c.name_en
    if key in CATALOG_NAMES_EN:
        return CATALOG_NAMES_EN[key]
    return stored if stored and stored != key else ""

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
