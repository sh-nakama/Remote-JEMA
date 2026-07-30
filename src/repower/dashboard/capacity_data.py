"""Curated OCCTO capacity-market results (source-cited).

Unlike the wholesale / balancing / policy datasets, the capacity-market summary
is **not** published in a machine-readable feed. OCCTO releases MAIN AUCTION
results (per-area clearing prices, procured capacity and contract totals) as PDF
press releases plus Excel "verification" workbooks; the only bulk CSV downloads
hold per-bidder detail (電源単位), a different granularity that would have to be
re-aggregated to reconstruct the headline figures. The Long-Term Decarbonization
Auction (LTDA, 長期脱炭素電源オークション) per-round technology split is likewise
not published in structured form.

So — as the build plan anticipated for LTDA — the figures below are **curated**
from OCCTO's published results, each carrying a source URL, and are exported to
the web snapshots by ``export_capacity``. This module is the single source of
truth: update it when OCCTO publishes a new auction. Downstream code
(``read.load_capacity_ma`` / ``export_web``) only ever reads these builders, so
if an automated OCCTO reader is added later it can populate the same shapes.

Row shapes match the web fixtures exactly (``web/src/screens/CapacityAuctions.data.ts``)
so the screen renders live data with no geometry change.
"""

from __future__ import annotations

# ── OCCTO areas, in the order every OCCTO results table lists them ────────────
# Keys match the rest of the app's area vocabulary (``export_web.AREAS`` /
# ``web/src/lib/types.ts``), where Tokyo is keyed ``tepco``. Okinawa sits outside
# the interconnected grid the capacity market clears over, so it has no clearing
# price and is absent here.
AREAS: list[dict[str, str]] = [
    {"key": "hokkaido", "en": "Hokkaido", "ja": "北海道"},
    {"key": "tohoku", "en": "Tohoku", "ja": "東北"},
    {"key": "tepco", "en": "Tokyo", "ja": "東京"},
    {"key": "chubu", "en": "Chubu", "ja": "中部"},
    {"key": "hokuriku", "en": "Hokuriku", "ja": "北陸"},
    {"key": "kansai", "en": "Kansai", "ja": "関西"},
    {"key": "chugoku", "en": "Chugoku", "ja": "中国"},
    {"key": "shikoku", "en": "Shikoku", "ja": "四国"},
    {"key": "kyushu", "en": "Kyushu", "ja": "九州"},
]
AREA_KEYS: list[str] = [a["key"] for a in AREAS]


def _by_area(*values: int) -> dict[str, int]:
    """Zip nine OCCTO-ordered figures onto :data:`AREA_KEYS`."""
    if len(values) != len(AREA_KEYS):
        raise ValueError(f"expected {len(AREA_KEYS)} area values, got {len(values)}")
    return dict(zip(AREA_KEYS, values, strict=True))


# ── Main auction: one record per delivery fiscal year (対象実需給年度) ──────────
# The capacity market clears **per area** (エリア毎の約定価格): 約定処理 splits the
# national market wherever an interconnector constraint binds, so one auction can
# settle at several different prices. Only the first auction (FY2024) cleared
# uniformly — FY2027 settled at six distinct prices. `prices` therefore carries
# every area's clearing price in yen/kW·year (円/kW), read from the エリア毎の
# 約定価格 table of the OCCTO press release for that year (see SOURCES).
#
# `capacity_kw` is the matching エリア毎の約定容量 and `net_total_yen` the published
# 約定総額（経過措置控除後）; the procured total and OCCTO's national average unit
# price (総平均単価 = 約定総額 ÷ 約定総容量) are derived from them, so no aggregate
# is hand-typed and every figure stays traceable to a published table. `ach` is
# OCCTO's published 目標調達量比 (procured-vs-target) in whole percent.
#
# 経過措置: a discount on the contract value of plants built before FY2011, which
# is why the national average unit price sits below the clearing prices.
MAIN_AUCTION: list[dict] = [
    {
        "fy": 2024,
        "held": "Sep 2020",
        "prices": _by_area(14137, 14137, 14137, 14137, 14137, 14137, 14137, 14137, 14137),
        "capacity_kw": _by_area(
            5_931_674, 17_652_765, 52_980_791, 25_276_498, 5_472_871,
            28_343_041, 7_657_972, 7_018_482, 17_357_554,
        ),
        "net_total_yen": 1_598_741_200_454,
        "ach": 97,
    },
    {
        "fy": 2025,
        "held": "Dec 2021",
        "prices": _by_area(5242, 3495, 3495, 3495, 3495, 3495, 3495, 3495, 5242),
        "capacity_kw": _by_area(
            5_414_104, 16_106_883, 55_617_210, 23_759_952, 5_494_312,
            26_172_806, 7_808_417, 7_465_778, 17_502_686,
        ),
        "net_total_yen": 514_010_589_965,
        "ach": 93,
    },
    {
        "fy": 2026,
        "held": "Jan 2023",
        "prices": _by_area(8749, 5833, 5834, 5832, 5832, 5832, 5832, 5832, 8748),
        "capacity_kw": _by_area(
            5_231_090, 16_609_897, 53_536_700, 23_432_491, 4_757_408,
            26_123_850, 8_162_119, 7_952_551, 16_904_773,
        ),
        "net_total_yen": 850_396_238_334,
        "ach": 92,
    },
    {
        "fy": 2027,
        "held": "Jan 2024",
        "prices": _by_area(13287, 9044, 9555, 7823, 7638, 7638, 7638, 7638, 11457),
        "capacity_kw": _by_area(
            5_191_979, 17_733_376, 55_417_081, 23_234_464, 4_569_798,
            28_860_919, 8_377_605, 7_864_566, 16_197_677,
        ),
        "net_total_yen": 1_313_960_531_206,
        "ach": 98,
    },
    {
        "fy": 2028,
        "held": "Jan 2025",
        "prices": _by_area(14812, 14812, 14812, 10280, 8785, 8785, 8785, 8785, 13177),
        "capacity_kw": _by_area(
            5_293_409, 16_526_974, 54_048_583, 23_597_868, 4_557_129,
            27_502_806, 9_727_561, 7_504_988, 17_454_424,
        ),
        "net_total_yen": 1_850_597_827_276,
        "ach": 97,
    },
    {
        "fy": 2029,
        "held": "Jan 2026",
        "prices": _by_area(14972, 15111, 15111, 12388, 12388, 12388, 12388, 12388, 15112),
        "capacity_kw": _by_area(
            5_461_594, 16_812_309, 52_376_601, 23_902_096, 4_388_972,
            27_409_123, 9_845_137, 7_520_510, 18_363_521,
        ),
        "net_total_yen": 2_209_359_548_463,
        "ach": 96,
    },
]

# Per-year source URLs — the OCCTO press-release PDF for that delivery year.
SOURCES: dict[int, str] = {
    2024: "https://www.occto.or.jp/assets/market-board/market/files/200914_mainauction_youryouyakujokekka_kouhyou_jitsujuky024.pdf",
    2025: "https://www.occto.or.jp/assets/market-board/market/oshirase/2021/files/220119_mainauction_keiyakukekka_saikouhyou_jitsujukyu2025.pdf",
    2026: "https://www.occto.or.jp/assets/market-board/market/oshirase/2022/files/230222_mainauction_youryouyakujokekka_saikouhyou_jitsujukyu2026.pdf",
    2027: "https://www.occto.or.jp/assets/market-board/market/oshirase/2023/files/240124_mainauction_youryouyakujokekka_kouhyou_jitsujukyu2027.pdf",
    2028: "https://www.occto.or.jp/assets/market-board/market/oshirase/2024/files/250129_mainauction_youryouyakujokekka_kouhyou_jitsujukyu2028.pdf",
    2029: "https://www.occto.or.jp/assets/various/capacity-market/jitsujukyukanren/2029_jitsujukyu_kanren/260123_mainauction_youryouyakujokekka_kouhyou_jitsujukyu2029.pdf",
}

# ── LTDA (Long-Term Decarbonization Auction) — curated tech breakdown ─────────
# Contracted capacity (GW) by technology across the auction rounds run to date,
# plus each technology's share of the cumulative total. Colours are the design
# tokens the screen paints the stacked bar / legend with (light, dark).
LTDA: list[dict] = [
    {"en": "Battery storage", "ja": "蓄電池", "r1": "1.10", "r2": "1.64", "r3": "1.68",
     "cum": "4.42", "share": 31, "c": "#00A5CF", "cd": "#1FB6DC"},
    {"en": "Pumped hydro", "ja": "揚水", "r1": "0.57", "r2": "0.30", "r3": "0.42",
     "cum": "1.29", "share": 9, "c": "#4A6FA5", "cd": "#7C9CD1"},
    {"en": "LNG (decarb-ready)", "ja": "LNG（脱炭素化前提）", "r1": "2.20", "r2": "2.55", "r3": "2.30",
     "cum": "7.05", "share": 50, "c": "#E9C46A", "cd": "#E9C46A"},
    {"en": "Hydrogen · Ammonia", "ja": "水素・アンモニア", "r1": "0.14", "r2": "0.36", "r3": "0.62",
     "cum": "1.12", "share": 8, "c": "#2A9D8F", "cd": "#2A9D8F"},
    {"en": "Other (biomass etc.)", "ja": "その他", "r1": "—", "r2": "—", "r3": "0.22",
     "cum": "0.22", "share": 2, "c": "#B4BCC9", "cd": "#5D6B85"},
]


# ── Derived aggregates ───────────────────────────────────────────────────────
def procured_kw(entry: dict) -> int:
    """約定総容量 for *entry* — the sum of its per-area cleared capacity."""
    return sum(entry["capacity_kw"].values())


def national_unit_price(entry: dict) -> int:
    """OCCTO's 総平均単価 in yen/kW: 約定総額（経過措置控除後）÷ 約定総容量.

    A value-weighted **average paid**, not a clearing price — the 経過措置
    discount pulls it below the per-area clearing prices in ``prices``.
    """
    return round(entry["net_total_yen"] / procured_kw(entry))


# ── Display formatting → the web MaRow shape ─────────────────────────────────
def _fmt_price(v: float | int | None) -> str:
    """A yen/kW clearing price as ``¥12,345`` (thousands-separated), or ``—``."""
    if v is None:
        return "—"
    return f"¥{int(round(v)):,}"


def _fmt_gw(v: float | int | None) -> str:
    """Procured capacity as ``166.1 GW`` (one decimal), or ``—``."""
    if v is None:
        return "—"
    return f"{v:.1f} GW"


def main_auction_rows() -> list[dict]:
    """Curated main-auction results in the screen's ``MaRow`` shape.

    ``areas`` carries the raw per-area clearing price (yen/kW·year) so the
    frontend can group the areas that cleared at the same price itself: which
    areas share a price changes with every auction, so it cannot be baked into
    fixed Hokkaido/Kyushu columns.
    """
    rows: list[dict] = []
    for e in MAIN_AUCTION:
        rows.append({
            "fy": f"FY{e['fy']}",
            "held": e["held"],
            "natl": _fmt_price(national_unit_price(e)),
            "proc": _fmt_gw(procured_kw(e) / 1_000_000),
            "ach": int(e["ach"]),
            "areas": dict(e["prices"]),
            "source": SOURCES.get(e["fy"], ""),
        })
    return rows


def ltda_rows() -> list[dict]:
    """Curated LTDA technology breakdown in the screen's ``LtdaRow`` shape."""
    return [dict(r) for r in LTDA]
