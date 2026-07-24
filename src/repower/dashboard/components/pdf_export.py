"""
Generate a portrait-A4 PDF report with volume and price sparklines
for every product × region in the visible date range.

One page per product — 9 region rows × 2 columns (volume | price).
Uses matplotlib for chart rendering and PdfPages for multi-page output.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages

from repower.dashboard.theme import (
    BRAND_NAVY as NAVY,
)
from repower.dashboard.theme import (
    BRAND_TEAL as TEAL,
)
from repower.dashboard.theme import (
    METRIC_COLORS as _METRIC_COLORS,
)

# Single source of truth for colours lives in theme.py.
RED = _METRIC_COLORS["missing_mw"]
GREY = "#888888"


def _pick_cjk_font() -> str | None:
    """Return the first installed CJK-capable font family, or None.

    Tries a small list of common Windows / Linux Japanese fonts so PDF rendering
    of Japanese labels does not fall back to tofu boxes. Returns None when none
    are available (matplotlib then uses its default font without crashing).
    """
    candidates = [
        "Noto Sans CJK JP",   # canonical Linux CJK (full weight faces)
        "Yu Gothic",          # Windows (full weight faces)
        "Meiryo",             # Windows fallback (full weight faces)
        "Noto Sans JP",       # may ship thin-only on some boxes
        "MS Gothic",
        "IPAexGothic",
        "TakaoPGothic",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            return name
    return None


# Prefer an installed CJK font for Japanese text; fall back gracefully so PDF
# generation never crashes on Windows or Linux.
_CJK_FONT = _pick_cjk_font()
_FONT_STACK = ([_CJK_FONT] if _CJK_FONT else []) + ["Inter", "DejaVu Sans", "sans-serif"]
matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = _FONT_STACK
matplotlib.rcParams["axes.unicode_minus"] = False


# A4 portrait in inches
A4_W, A4_H = 8.27, 11.69
MARGIN_L, MARGIN_R = 0.55, 0.35
MARGIN_T, MARGIN_B = 0.70, 0.45

BODY_W = A4_W - MARGIN_L - MARGIN_R
BODY_H = A4_H - MARGIN_T - MARGIN_B


def _draw_volume_ax(ax, region_df, color_map, label_map, vol_metrics):
    """Draw volume sparklines on a single axes.

    missing_mw is rendered as a shaded area between demand_mw and
    contracted_mw (clamped so negative gaps are hidden), matching
    the dashboard's D3 behaviour.
    """
    dt = region_df["datetime"]

    # Draw shaded unprocured area first (behind lines)
    if "missing_mw" in vol_metrics and "demand_mw" in region_df.columns:
        demand = region_df["demand_mw"].values
        contracted = region_df["contracted_mw"].values if "contracted_mw" in region_df.columns else demand
        # Bottom of the shaded band = min(demand, contracted) so only
        # the positive gap (demand > contracted) is filled.
        lower = np.minimum(demand, contracted)
        c = color_map.get("missing_mw", RED)
        ax.fill_between(dt, lower, demand, step="post",
                        color=c, alpha=0.22, label=label_map.get("missing_mw", "missing_mw"))

    # Draw line metrics (skip missing_mw — it's the shaded area above)
    for m in vol_metrics:
        if m == "missing_mw":
            continue
        if m not in region_df.columns:
            continue
        vals = region_df[m]
        if vals.isna().all():
            continue
        c = color_map.get(m, GREY)
        ax.step(dt, vals, where="post",
                color=c, linewidth=0.8, label=label_map.get(m, m))
    ax.tick_params(labelsize=5, length=2, pad=1)
    ax.yaxis.set_major_locator(plt.MaxNLocator(4, integer=False))
    ax.set_ylabel("MW", fontsize=5, labelpad=2)


def _draw_price_ax(ax, region_df, color_map, label_map, price_metrics):
    """Draw price sparklines on a single axes."""
    for m in price_metrics:
        if m not in region_df.columns:
            continue
        vals = region_df[m]
        if vals.isna().all():
            continue
        c = color_map.get(m, GREY)
        lw = 0.9 if m == "price_avg" else 0.7
        ax.step(region_df["datetime"], vals, where="post",
                color=c, linewidth=lw, label=label_map.get(m, m))
    ax.tick_params(labelsize=5, length=2, pad=1)
    ax.yaxis.set_major_locator(plt.MaxNLocator(4, integer=False))
    ax.set_ylabel("¥/kW·30min", fontsize=5, labelpad=2)


def generate_pdf(
    product_data: dict[str, pd.DataFrame],
    regions: list[str],
    vol_metrics: list[str],
    price_metrics: list[str],
    color_map: dict[str, str],
    label_map: dict[str, str],
    view_start: date,
    view_end: date,
) -> bytes:
    """
    Build a multi-page A4 PDF — one page per product.

    Parameters
    ----------
    product_data : dict mapping product name → wide-format DataFrame
        (already filtered to the visible date range).
    regions : list of region names in display order.
    vol_metrics / price_metrics : metric keys to plot.
    color_map / label_map : styling dicts.
    view_start, view_end : date range shown in title.

    Returns
    -------
    bytes : The PDF file contents.
    """
    buf = BytesIO()
    date_label = f"{view_start.strftime('%Y-%m-%d')} → {view_end.strftime('%Y-%m-%d')}"

    with PdfPages(buf) as pdf:
        for product_name, df in product_data.items():
            if df.empty:
                continue

            fig, axes = plt.subplots(
                nrows=len(regions) or 1, ncols=2,
                figsize=(A4_W, A4_H),
                squeeze=False,
                gridspec_kw={
                    "left": MARGIN_L / A4_W,
                    "right": 1 - MARGIN_R / A4_W,
                    "top": 1 - MARGIN_T / A4_H,
                    "bottom": MARGIN_B / A4_H,
                    "hspace": 0.55,
                    "wspace": 0.30,
                },
            )

            # Page title
            fig.text(
                0.5, 1 - 0.28 / A4_H,
                f"{product_name}  —  {date_label}",
                ha="center", va="top",
                fontsize=11, fontweight="bold", color=NAVY,
            )

            # Column headers
            col_left_x = MARGIN_L / A4_W + (BODY_W / 2 / A4_W) / 2
            col_right_x = (1 - MARGIN_R / A4_W) - (BODY_W / 2 / A4_W) / 2
            header_y = 1 - 0.50 / A4_H
            fig.text(col_left_x, header_y, "Volume",
                     ha="center", fontsize=8, fontweight="600", color=NAVY)
            fig.text(col_right_x, header_y, "Price",
                     ha="center", fontsize=8, fontweight="600", color=NAVY)

            for i, region in enumerate(regions):
                ax_vol = axes[i, 0]
                ax_price = axes[i, 1]

                rdf = df[df["region"] == region].sort_values("datetime")

                if rdf.empty:
                    for ax in (ax_vol, ax_price):
                        ax.text(0.5, 0.5, "no data", ha="center", va="center",
                                fontsize=6, color=GREY, transform=ax.transAxes)
                        ax.set_yticks([])
                        ax.set_xticks([])
                    ax_vol.set_ylabel(region, fontsize=6, fontweight="bold",
                                      color=NAVY, labelpad=8)
                    continue

                _draw_volume_ax(ax_vol, rdf, color_map, label_map, vol_metrics)
                _draw_price_ax(ax_price, rdf, color_map, label_map, price_metrics)

                # Region label on the left y-axis
                ax_vol.set_ylabel(region, fontsize=6, fontweight="bold",
                                  color=NAVY, labelpad=8)

                # X-axis formatting — show labels on every row
                for ax in (ax_vol, ax_price):
                    ax.xaxis.set_major_formatter(
                        mdates.DateFormatter("%b %d"))
                    ax.xaxis.set_major_locator(
                        mdates.AutoDateLocator(minticks=3, maxticks=6))
                    for lbl in ax.get_xticklabels():
                        lbl.set_fontsize(5)
                        lbl.set_rotation(30)
                        lbl.set_ha("right")

                    # Subtle grid
                    ax.grid(axis="y", linewidth=0.3, color="#ddd", linestyle="--")
                    ax.spines["top"].set_visible(False)
                    ax.spines["right"].set_visible(False)
                    ax.spines["left"].set_linewidth(0.4)
                    ax.spines["bottom"].set_linewidth(0.4)

            # Shared legend at the very bottom
            all_metrics = vol_metrics + price_metrics
            handles, labels = [], []
            for m in all_metrics:
                c = color_map.get(m, GREY)
                lbl = label_map.get(m, m)
                h = plt.Line2D([0], [0], color=c, linewidth=1.2)
                handles.append(h)
                labels.append(lbl)
            fig.legend(
                handles, labels,
                loc="lower center",
                ncol=min(len(all_metrics), 5),
                fontsize=5.5,
                frameon=False,
                bbox_to_anchor=(0.5, 0.01),
            )

            # Footer
            fig.text(
                0.98, 0.005,
                "Source: EPRX",
                ha="right", fontsize=4.5, color=GREY,
            )

            pdf.savefig(fig)
            plt.close(fig)

    return buf.getvalue()


# ── Wholesale PDF ─────────────────────────────────────────────────────────────


def generate_wholesale_pdf(
    area_data: dict[str, pd.DataFrame],
    view_start: date,
    view_end: date,
    demand_color: str = NAVY,
    price_color: str = TEAL,
) -> bytes:
    """
    Build a single-page portrait-A4 PDF for the wholesale market.

    One row per area, each with two small subplots: demand line (left) and
    JEPX price line (right).

    Parameters
    ----------
    area_data : dict mapping area display name → DataFrame
        Each DataFrame must carry a ``datetime`` column plus ``area_demand_mw``
        and ``price`` columns (already filtered to the visible date range).
        Insertion order is the row order in the document.
    view_start, view_end : date range shown in the title.
    demand_color / price_color : line colours (defaults from theme.py).

    Returns
    -------
    bytes : The PDF file contents.
    """
    buf = BytesIO()
    date_label = f"{view_start.strftime('%Y-%m-%d')} → {view_end.strftime('%Y-%m-%d')}"
    areas = list(area_data.keys())
    n_rows = len(areas) or 1

    with PdfPages(buf) as pdf:
        fig, axes = plt.subplots(
            nrows=n_rows, ncols=2,
            figsize=(A4_W, A4_H),
            squeeze=False,
            gridspec_kw={
                "left": MARGIN_L / A4_W,
                "right": 1 - MARGIN_R / A4_W,
                "top": 1 - MARGIN_T / A4_H,
                "bottom": MARGIN_B / A4_H,
                "hspace": 0.55,
                "wspace": 0.30,
            },
        )

        # Page title
        fig.text(
            0.5, 1 - 0.28 / A4_H,
            f"Wholesale (JEPX)  —  {date_label}",
            ha="center", va="top",
            fontsize=11, fontweight="bold", color=NAVY,
        )

        # Column headers
        col_left_x = MARGIN_L / A4_W + (BODY_W / 2 / A4_W) / 2
        col_right_x = (1 - MARGIN_R / A4_W) - (BODY_W / 2 / A4_W) / 2
        header_y = 1 - 0.50 / A4_H
        fig.text(col_left_x, header_y, "Demand (MW)",
                 ha="center", fontsize=8, fontweight="600", color=NAVY)
        fig.text(col_right_x, header_y, "JEPX Price (¥/kWh)",
                 ha="center", fontsize=8, fontweight="600", color=NAVY)

        for i, area in enumerate(areas):
            ax_demand = axes[i, 0]
            ax_price = axes[i, 1]
            rdf = area_data[area]
            rdf = rdf.sort_values("datetime") if not rdf.empty else rdf

            has_demand = (
                not rdf.empty
                and "area_demand_mw" in rdf.columns
                and not rdf["area_demand_mw"].isna().all()
            )
            has_price = (
                not rdf.empty
                and "price" in rdf.columns
                and not rdf["price"].isna().all()
            )

            if not has_demand:
                ax_demand.text(0.5, 0.5, "no data", ha="center", va="center",
                               fontsize=6, color=GREY, transform=ax_demand.transAxes)
                ax_demand.set_yticks([])
                ax_demand.set_xticks([])
            else:
                ax_demand.plot(rdf["datetime"], rdf["area_demand_mw"],
                               color=demand_color, linewidth=0.8)
                ax_demand.tick_params(labelsize=5, length=2, pad=1)
                ax_demand.yaxis.set_major_locator(plt.MaxNLocator(4, integer=False))
                ax_demand.set_ylabel("MW", fontsize=5, labelpad=2)

            if not has_price:
                ax_price.text(0.5, 0.5, "no data", ha="center", va="center",
                              fontsize=6, color=GREY, transform=ax_price.transAxes)
                ax_price.set_yticks([])
                ax_price.set_xticks([])
            else:
                ax_price.plot(rdf["datetime"], rdf["price"],
                              color=price_color, linewidth=0.8)
                ax_price.tick_params(labelsize=5, length=2, pad=1)
                ax_price.yaxis.set_major_locator(plt.MaxNLocator(4, integer=False))
                ax_price.set_ylabel("¥/kWh", fontsize=5, labelpad=2)

            # Area label on the left y-axis
            ax_demand.set_ylabel(area, fontsize=6, fontweight="bold",
                                 color=NAVY, labelpad=8)

            # X-axis formatting on rows with data
            for ax, has in ((ax_demand, has_demand), (ax_price, has_price)):
                if not has:
                    continue
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
                ax.xaxis.set_major_locator(
                    mdates.AutoDateLocator(minticks=3, maxticks=6))
                for lbl in ax.get_xticklabels():
                    lbl.set_fontsize(5)
                    lbl.set_rotation(30)
                    lbl.set_ha("right")
                ax.grid(axis="y", linewidth=0.3, color="#ddd", linestyle="--")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.spines["left"].set_linewidth(0.4)
                ax.spines["bottom"].set_linewidth(0.4)

        # Footer
        fig.text(
            0.98, 0.005,
            "Source: JEPX / TSO area data",
            ha="right", fontsize=4.5, color=GREY,
        )

        pdf.savefig(fig)
        plt.close(fig)

    return buf.getvalue()
