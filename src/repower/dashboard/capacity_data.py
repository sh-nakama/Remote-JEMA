"""Curated OCCTO capacity-market results (source-cited).

Unlike the wholesale / balancing / policy datasets, the capacity-market summary
is **not** published in a machine-readable feed. OCCTO releases MAIN AUCTION
results (national + zonal clearing prices and procured capacity) as PDF press
releases plus Excel "verification" workbooks; the only bulk CSV downloads hold
per-bidder detail (電源単位), a different granularity that would have to be
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

# ── Main auction: one record per delivery fiscal year (対象実需給年度) ──────────
# natl/hokkaido/kyushu are clearing prices in yen/kW (円/kW). For FY2025+ `natl`
# is OCCTO's 総平均単価（経過措置控除後） = 約定総額 ÷ 約定総容量 (value-weighted
# national average). FY2024 cleared at a single uniform national price with no
# zonal split, so its zonal fields are None. `procured_gw` is 約定総容量 in GW
# (1万kW = 0.01 GW). `ach` is OCCTO's published 目標調達量比 (procured-vs-target)
# in whole percent.
#
# Figures extracted directly from the six OCCTO press-release PDFs (see SOURCES)
# and cross-checked against media analyses (reivalue, note.com/gridshift,
# itmedia). Zonal prices before FY2025 did not exist; from FY2025 the area
# tables give distinct Hokkaido/Kyushu prices.
MAIN_AUCTION: list[dict] = [
    {"fy": 2024, "held": "Sep 2020", "natl": 14137, "hokkaido": None, "kyushu": None,
     "procured_gw": 167.69, "ach": 97},
    {"fy": 2025, "held": "Dec 2021", "natl": 3109, "hokkaido": 5242, "kyushu": 5242,
     "procured_gw": 165.34, "ach": 93},
    {"fy": 2026, "held": "Jan 2023", "natl": 5226, "hokkaido": 8749, "kyushu": 8748,
     "procured_gw": 162.71, "ach": 92},
    {"fy": 2027, "held": "Jan 2024", "natl": 7847, "hokkaido": 13287, "kyushu": 11457,
     "procured_gw": 167.45, "ach": 98},
    {"fy": 2028, "held": "Jan 2025", "natl": 11134, "hokkaido": 14812, "kyushu": 13177,
     "procured_gw": 166.21, "ach": 97},
    {"fy": 2029, "held": "Jan 2026", "natl": 13303, "hokkaido": 14972, "kyushu": 15112,
     "procured_gw": 166.08, "ach": 96},
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
    """Curated main-auction results in the screen's ``MaRow`` shape."""
    rows: list[dict] = []
    for e in MAIN_AUCTION:
        rows.append({
            "fy": f"FY{e['fy']}",
            "held": e["held"],
            "natl": _fmt_price(e["natl"]),
            "hok": _fmt_price(e["hokkaido"]),
            "kyu": _fmt_price(e["kyushu"]),
            "proc": _fmt_gw(e["procured_gw"]),
            "ach": int(e["ach"]),
            "source": SOURCES.get(e["fy"], ""),
        })
    return rows


def ltda_rows() -> list[dict]:
    """Curated LTDA technology breakdown in the screen's ``LtdaRow`` shape."""
    return [dict(r) for r in LTDA]
