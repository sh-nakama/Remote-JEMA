"""
Brand colours and global CSS for the dashboard.
"""

# ── Metric colour palette ──────────────────────────────────────────────────────
METRIC_COLORS = {
    # Volume metrics
    "demand_mw":        "#1B2A4A",   # navy — Market Procurement
    "bid_volume_mw":    "#F4A261",   # orange — Bid Volume
    "contracted_mw":    "#00A5CF",   # teal — Cleared Capacity
    "missing_mw":       "#E63946",   # red  — Unprocured (shaded area)
    "bids_count":       "#E9C46A",   # gold — Total Bids
    "contracted_count": "#2A9D8F",   # deep teal — Cleared Bids

    # Price metrics
    "price_max":        "#E63946",   # red
    "price_avg":        "#1B2A4A",   # navy
    "price_min":        "#00A5CF",   # teal

    # Tieline metrics
    "upper_limit_fwd":  "#264653",   # dark teal — capacity limit forward
    "upper_limit_rev":  "#7B2D8E",   # purple — capacity limit reverse
    "reserved_fwd":     "#E9C46A",   # gold — reserved forward
    "reserved_rev":     "#E76F51",   # coral — reserved reverse
}

METRIC_LABELS = {
    "demand_mw":        "Market Procurement (MW)",
    "bid_volume_mw":    "Bid Volume (MW)",
    "contracted_mw":    "Cleared Capacity (MW)",
    "missing_mw":       "Unprocured (MW)",
    "bids_count":       "Total Bids",
    "contracted_count": "Cleared Bids",
    "price_max":        "Max Price (¥/kW·30min)",
    "price_avg":        "Avg Price (¥/kW·30min)",
    "price_min":        "Min Price (¥/kW·30min)",
    # Tieline metrics
    "upper_limit_fwd":  "Upper Limit Forward (MW)",
    "upper_limit_rev":  "Upper Limit Reverse (MW)",
    "reserved_fwd":     "Reserved Forward (MW)",
    "reserved_rev":     "Reserved Reverse (MW)",
}

VOLUME_METRICS = ["demand_mw", "bid_volume_mw", "contracted_mw", "missing_mw", "bids_count", "contracted_count"]
PRICE_METRICS  = ["price_max", "price_avg", "price_min"]
TIELINE_METRICS = ["upper_limit_fwd", "upper_limit_rev", "reserved_fwd", "reserved_rev"]

DEFAULT_VOLUME_METRICS = ["demand_mw", "missing_mw"]
DEFAULT_PRICE_METRICS  = ["price_max", "price_avg"]
DEFAULT_TIELINE_METRICS = ["upper_limit_fwd", "upper_limit_rev", "reserved_fwd", "reserved_rev"]

# ── Product colour palette ─────────────────────────────────────────────────────
PRODUCT_COLORS = {
    "Primary":          "#1B2A4A",
    "Primary (offline)": "#4A6FA5",
    "Secondary 1":      "#00A5CF",
    "Secondary 2":      "#2A9D8F",
    "Tertiary 1":       "#E9C46A",
    "Tertiary 2":       "#E63946",
    "Composite":        "#7B2D8E",
}

PRODUCT_ORDER = ["Primary", "Primary (offline)", "Secondary 1", "Secondary 2", "Tertiary 1", "Tertiary 2", "Composite"]

# ── Generation-mix (fuel) colour palette ───────────────────────────────────────
# One neutral, distinct hex per supply-side mix column from read.MIX_COLUMNS.
# `total_supply` is the sum of the others — never stack it; it is here only so
# callers can colour/label a total overlay if desired.
GENERATION_COLORS = {
    "nuclear":       "#7B2D8E",   # purple
    "lng":           "#00A5CF",   # teal-blue
    "coal":          "#3A3A3A",   # dark grey
    "oil":           "#6B4226",   # brown
    "thermal_other": "#9C6B4E",   # muted brown/clay
    "hydro":         "#1B2A4A",   # navy
    "geothermal":    "#C1440E",   # burnt orange
    "biomass":       "#2A9D8F",   # green
    "solar_actual":  "#E9C46A",   # amber
    "wind_actual":   "#4FB0A5",   # light teal
    "pumped":        "#4A6FA5",   # steel blue
    "battery":       "#8AB17D",   # sage green
    "interconnect":  "#9AA0A6",   # neutral grey
    "other":         "#C9CCD1",   # light grey
    "total_supply":  "#1B2A4A",   # navy (overlay only — not a stack layer)
}

GENERATION_LABELS = {
    "nuclear":       "Nuclear",
    "lng":           "LNG",
    "coal":          "Coal",
    "oil":           "Oil",
    "thermal_other": "Other Thermal",
    "hydro":         "Hydro",
    "geothermal":    "Geothermal",
    "biomass":       "Biomass",
    "solar_actual":  "Solar",
    "wind_actual":   "Wind",
    "pumped":        "Pumped Storage",
    "battery":       "Battery",
    "interconnect":  "Interconnect",
    "other":         "Other",
    "total_supply":  "Total Supply",
}

# ── Brand constants ────────────────────────────────────────────────────────────
BRAND_NAVY      = "#1B2A4A"
BRAND_TEAL      = "#00A5CF"
BRAND_DARK_TEAL = "#264653"
BRAND_WHITE     = "#FFFFFF"
BRAND_LIGHT_BG  = "#FAFAFA"
BRAND_GREY      = "#E8E8E8"
BRAND_TEXT       = "#333333"

FONT_STACK = "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif"

# ── Global CSS injected into Streamlit ─────────────────────────────────────────
GLOBAL_CSS = f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {{
        font-family: {FONT_STACK};
        color: {BRAND_TEXT};
    }}

    header[data-testid="stHeader"] {{
        background-color: {BRAND_NAVY};
    }}

    section[data-testid="stSidebar"] {{
        background-color: {BRAND_NAVY};
        color: {BRAND_WHITE};
    }}
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stRadio label,
    section[data-testid="stSidebar"] .stMultiSelect label,
    section[data-testid="stSidebar"] span {{
        color: {BRAND_WHITE} !important;
    }}
    section[data-testid="stSidebar"] hr {{
        border-color: rgba(255,255,255,0.2);
    }}

    button[data-baseweb="tab"] {{
        font-family: {FONT_STACK};
        font-weight: 600;
        color: {BRAND_NAVY};
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: {BRAND_TEAL};
        border-bottom-color: {BRAND_TEAL};
    }}

    .block-container {{
        padding-top: 2rem;
        max-width: 1800px;
    }}

    div[data-testid="stMetric"] {{
        background: {BRAND_WHITE};
        border: 1px solid {BRAND_GREY};
        border-radius: 8px;
        padding: 12px 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }}
    div[data-testid="stMetric"] label {{
        color: {BRAND_DARK_TEAL} !important;
        font-weight: 600;
    }}

    footer {{
        visibility: hidden;
    }}

    [data-testid="stVerticalBlockBorderWrapper"] {{
        margin-bottom: -1rem;
    }}
    [data-testid="column"] > div {{
        padding-bottom: 0 !important;
    }}

    .dataframe th {{
        background-color: {BRAND_NAVY} !important;
        color: {BRAND_WHITE} !important;
        font-weight: 600;
    }}
</style>
"""
