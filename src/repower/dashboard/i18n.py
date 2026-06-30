"""
Internationalisation strings for the dashboard.

Usage::

    from repower.dashboard.i18n import T, LANG_OPTIONS

    lang = st.session_state.get("lang", "ja")
    label = T("sidebar_title", lang)
"""
from __future__ import annotations

# ── Available languages ─────────────────────────────────────────────────────
LANG_OPTIONS = {"ja": "日本語", "en": "English"}
DEFAULT_LANG = "ja"

# ── Translation table ───────────────────────────────────────────────────────
# Keys are arbitrary identifiers used in app.py.
# Each maps to {"en": …, "ja": …}.

_STRINGS: dict[str, dict[str, str]] = {
    # ── Sidebar ──────────────────────────────────────────────────────
    "sidebar_title":            {"en": "⚡ Japan Power Markets",   "ja": "⚡ Japan Power Markets"},
    "sidebar_subtitle":         {"en": "Half-Hourly BM Inspector","ja": "30分単位 需給調整市場"},
    "product":                  {"en": "Product",                 "ja": "商品区分"},
    "start_date":               {"en": "Start date",              "ja": "開始日"},
    "end_date":                 {"en": "End date",                "ja": "終了日"},
    "volume_metrics":           {"en": "Volume metrics",          "ja": "量の指標"},
    "price_metrics":            {"en": "Price metrics",           "ja": "価格の指標"},
    "period_comparison":        {"en": "Period Comparison",       "ja": "期間比較"},
    "period_comparison_caption":{"en": "Baseline vs. comparison periods for the Comparison tab",
                                 "ja": "比較タブ用のベースラインと比較期間"},
    "baseline_period":          {"en": "Baseline period",         "ja": "ベースライン期間"},
    "baseline_help":            {"en": "The reference period (e.g. week before March 14)",
                                 "ja": "基準期間（例：3月14日前の1週間）"},
    "baseline_start":           {"en": "Baseline start",          "ja": "基準 開始日"},
    "baseline_end":             {"en": "Baseline end",            "ja": "基準 終了日"},
    "comparison_period":        {"en": "Comparison period",       "ja": "比較期間"},
    "comparison_help":          {"en": "The period to compare against the baseline",
                                 "ja": "ベースラインと比較する期間"},
    "comparison_start":         {"en": "Comparison start",        "ja": "比較 開始日"},
    "comparison_end":           {"en": "Comparison end",          "ja": "比較 終了日"},
    "refresh_btn":              {"en": "🔄 Refresh data from EPRX","ja": "🔄 EPRXからデータ更新"},
    "refreshing":               {"en": "Downloading from EPRX…",  "ja": "EPRXからダウンロード中…"},
    "updated":                  {"en": "Updated",                  "ja": "更新済み"},
    "up_to_date":               {"en": "All data is up to date.",  "ja": "すべてのデータは最新です。"},
    "source_caption":           {"en": "Source: EPRX (eprx.or.jp)","ja": "出典: EPRX (eprx.or.jp)"},
    "cache_caption":            {"en": "Data cached locally — click Refresh to update",
                                 "ja": "データはローカルにキャッシュ — 更新ボタンで最新化"},
    "export_excel":             {"en": "📥 Export to Excel",       "ja": "📥 Excel出力"},
    "export_pdf":               {"en": "📄 Export to PDF",         "ja": "📄 PDF出力"},
    "export_content":           {"en": "PDF content",              "ja": "PDF内容"},
    "export_bm":                {"en": "Balancing Market",         "ja": "需給調整市場"},
    "export_ic":                {"en": "Interconnectors",          "ja": "連系線"},

    # ── Policy observer ──────────────────────────────────────────────
    "policy_header":            {"en": "Policy Observer",          "ja": "政策ウォッチャー"},
    "policy_committee":         {"en": "Committee",                "ja": "委員会"},
    "policy_latest":            {"en": "latest summarised",        "ja": "最新要約"},
    "policy_overview_en":       {"en": "Overview (English)",       "ja": "概要（英語）"},
    "policy_synthesis_ja":      {"en": "Discussion synthesis (Japanese)", "ja": "議論の総括（日本語）"},
    "policy_meetings":          {"en": "Meetings",                 "ja": "会合一覧"},
    "policy_english_digest":    {"en": "English digest",           "ja": "英語ダイジェスト"},
    "policy_download_doc":      {"en": "📥 Download running document", "ja": "📥 ランニングドキュメントをダウンロード"},
    "policy_no_data":           {"en": "No policy data yet. Run `repower policy detect` (and `repower policy run` to summarise).",
                                 "ja": "政策データはまだありません。`repower policy detect`（要約は `repower policy run`）を実行してください。"},
    "policy_no_meetings":       {"en": "No meetings recorded yet for this committee.",
                                 "ja": "この委員会の会合はまだ記録されていません。"},
    "policy_unsummarised":      {"en": "no summaries yet",         "ja": "要約未作成"},

    # ── Main area ────────────────────────────────────────────────────
    "page_header":              {"en": "Half-Hourly Balancing Market Inspector",
                                 "ja": "30分単位 需給調整市場インスペクター"},
    "no_data_product":          {"en": "No data found for **{product}**. Try clicking 'Refresh data from EPRX' in the sidebar.",
                                 "ja": "**{product}** のデータが見つかりません。サイドバーの「EPRXからデータ更新」をクリックしてください。"},
    "no_data_range":            {"en": "No data in the selected date range ({start} → {end}). Try adjusting the dates.",
                                 "ja": "選択した期間（{start} → {end}）にデータがありません。日付を調整してください。"},
    "block_transition":         {"en": "⚠️ This date range spans the 3h→30min block transition (March 14, 2026).",
                                 "ja": "⚠️ この期間は3時間→30分ブロック移行（2026年3月14日）を含みます。"},
    "tab_charts":               {"en": "📊 Block-Level Charts",    "ja": "📊 ブロック別チャート"},
    "tab_product_price":        {"en": "📊 Product Price Comparison", "ja": "📊 商品別価格比較"},
    "price_toggle":             {"en": "Price metric",             "ja": "価格指標"},
    "price_toggle_avg":         {"en": "Average Price",            "ja": "平均価格"},
    "price_toggle_max":         {"en": "Max Price",                "ja": "最高価格"},
    "tab_compare":              {"en": "📋 Period Comparison",     "ja": "📋 期間比較"},
    "visible_range":            {"en": "Visible date range",       "ja": "表示期間"},
    "no_region_data":           {"en": "**{region}** — no data",   "ja": "**{region}** — データなし"},
    "select_vol_sidebar":       {"en": "{region}: select volume metrics in sidebar",
                                 "ja": "{region}: サイドバーで量の指標を選択"},
    "select_price_sidebar":     {"en": "{region}: select price metrics in sidebar",
                                 "ja": "{region}: サイドバーで価格の指標を選択"},

    # ── Comparison tab ───────────────────────────────────────────────
    "compare_no_data":          {"en": "One or both comparison periods have no data. Adjust the period dates in the sidebar.",
                                 "ja": "比較期間の片方または両方にデータがありません。サイドバーで期間を調整してください。"},
    "compare_title":            {"en": "{product}: Baseline ({base}) vs Comparison ({comp})",
                                 "ja": "{product}: ベースライン ({base}) vs 比較 ({comp})"},
    "compare_no_region":        {"en": "**{region}** — no data in either period",
                                 "ja": "**{region}** — 両期間ともデータなし"},
    "narrative_baseline":       {"en": "In the baseline period ({period}), average procurement demand was **{demand:.1f} MW** with **{missing:.1f} MW** unprocured (**{pct:.1f}%**). ",
                                 "ja": "ベースライン期間（{period}）、平均調達需要は **{demand:.1f} MW**、未調達 **{missing:.1f} MW**（**{pct:.1f}%**）。"},
    "narrative_comparison":     {"en": "In the comparison period ({period}), average procurement demand was **{demand:.1f} MW** with **{missing:.1f} MW** unprocured (**{pct:.1f}%**). ",
                                 "ja": "比較期間（{period}）、平均調達需要は **{demand:.1f} MW**、未調達 **{missing:.1f} MW**（**{pct:.1f}%**）。"},
    "narrative_price":          {"en": "Average max price moved from **{from_max:.2f}** to **{to_max:.2f}** ¥/kW·30min ({delta_max:+.2f}); average price moved from **{from_avg:.2f}** to **{to_avg:.2f}** ¥/kW·30min ({delta_avg:+.2f}).",
                                 "ja": "最高落札価格の平均は **{from_max:.2f}** → **{to_max:.2f}** 円/kW·30分（{delta_max:+.2f}）、平均落札価格は **{from_avg:.2f}** → **{to_avg:.2f}** 円/kW·30分（{delta_avg:+.2f}）。"},
    "summary_table":            {"en": "Summary Table",            "ja": "集計テーブル"},

    # ── Product display names ─────────────────────────────────────────
    "prod_Primary":             {"en": "Primary",                 "ja": "一次調整力"},
    "prod_Primary (offline)":   {"en": "Primary (offline)",       "ja": "一次調整力（オフライン）"},
    "prod_Secondary 1":         {"en": "Secondary 1",             "ja": "二次調整力①"},
    "prod_Secondary 2":         {"en": "Secondary 2",             "ja": "二次調整力②"},
    "prod_Tertiary 1":          {"en": "Tertiary 1",              "ja": "三次調整力①"},
    "prod_Tertiary 2":          {"en": "Tertiary 2",              "ja": "三次調整力②"},
    "prod_Composite":           {"en": "Composite",               "ja": "複合計"},

    # ── Region display names ─────────────────────────────────────────
    "rgn_Hokkaido":             {"en": "Hokkaido",   "ja": "北海道"},
    "rgn_Tohoku":               {"en": "Tohoku",     "ja": "東北"},
    "rgn_Tokyo":                {"en": "Tokyo",      "ja": "東京"},
    "rgn_Chubu":                {"en": "Chubu",      "ja": "中部"},
    "rgn_Hokuriku":             {"en": "Hokuriku",   "ja": "北陸"},
    "rgn_Kansai":               {"en": "Kansai",     "ja": "関西"},
    "rgn_Chugoku":              {"en": "Chugoku",    "ja": "中国"},
    "rgn_Shikoku":              {"en": "Shikoku",    "ja": "四国"},
    "rgn_Kyushu":               {"en": "Kyushu",     "ja": "九州"},

    # ── Metric labels ────────────────────────────────────────────────
    "met_demand_mw":            {"en": "Market Procurement (MW)",  "ja": "募集量 (MW)"},
    "met_bid_volume_mw":        {"en": "Bid Volume (MW)",          "ja": "応札量 (MW)"},
    "met_contracted_mw":        {"en": "Cleared Capacity (MW)",    "ja": "落札量 (MW)"},
    "met_missing_mw":           {"en": "Unprocured (MW)",          "ja": "未調達 (MW)"},
    "met_bids_count":           {"en": "Total Bids",               "ja": "応札件数"},
    "met_contracted_count":     {"en": "Cleared Bids",             "ja": "落札件数"},
    "met_price_max":            {"en": "Max Price (¥/kW·30min)",   "ja": "最高落札価格 (円/kW·30分)"},
    "met_price_avg":            {"en": "Avg Price (¥/kW·30min)",   "ja": "平均落札価格 (円/kW·30分)"},
    "met_price_min":            {"en": "Min Price (¥/kW·30min)",   "ja": "最低落札価格 (円/kW·30分)"},
    # Tieline metrics
    "met_upper_limit_fwd":      {"en": "Upper Limit Forward (MW)",  "ja": "連系線確保量上限（順方向）(MW)"},
    "met_upper_limit_rev":      {"en": "Upper Limit Reverse (MW)",  "ja": "連系線確保量上限（逆方向）(MW)"},
    "met_reserved_fwd":         {"en": "Reserved Forward (MW)",     "ja": "連系線確保量（順方向）(MW)"},
    "met_reserved_rev":         {"en": "Reserved Reverse (MW)",     "ja": "連系線確保量（逆方向）(MW)"},

    # ── Tieline / Interconnector tab ─────────────────────────────────
    "tab_tieline":              {"en": "🔗 Interconnectors",       "ja": "🔗 連系線"},
    "tieline_market":           {"en": "Tieline market",            "ja": "連系線市場"},
    "tieline_metrics":          {"en": "Tieline metrics",           "ja": "連系線指標"},
    "tieline_market_dcm":       {"en": "DCM (Balancing Market)",    "ja": "DCM（需給調整市場）"},
    "tieline_market_dam":       {"en": "DAM (Tertiary 2)",          "ja": "DAM（三次調整力②）"},
    "no_tieline_data":          {"en": "No tieline data found. Try clicking 'Refresh data from EPRX' in the sidebar.",
                                 "ja": "連系線データが見つかりません。サイドバーの「EPRXからデータ更新」をクリックしてください。"},
    "no_pair_data":             {"en": "**{pair}** — no data",      "ja": "**{pair}** — データなし"},
    "select_tieline_sidebar":   {"en": "{pair}: select tieline metrics in sidebar",
                                 "ja": "{pair}: サイドバーで連系線指標を選択"},

    # ── Interconnector pair display names ─────────────────────────────
    "pair_Hokkaido → Tohoku":           {"en": "Hokkaido → Tohoku",           "ja": "北海道 → 東北"},
    "pair_Tohoku → Tokyo":              {"en": "Tohoku → Tokyo",              "ja": "東北 → 東京"},
    "pair_Tokyo → Chubu":               {"en": "Tokyo → Chubu",               "ja": "東京 → 中部"},
    "pair_Chubu-Kansai → Hokuriku":     {"en": "Chubu-Kansai → Hokuriku",     "ja": "中部関西 → 北陸"},
    "pair_Chubu → Hokuriku-Kansai":     {"en": "Chubu → Hokuriku-Kansai",     "ja": "中部 → 北陸関西"},
    "pair_Chubu-Hokuriku → Kansai":     {"en": "Chubu-Hokuriku → Kansai",     "ja": "中部北陸 → 関西"},
    "pair_Kansai → Chugoku":            {"en": "Kansai → Chugoku",            "ja": "関西 → 中国"},
    "pair_Kansai → Shikoku":            {"en": "Kansai → Shikoku",            "ja": "関西 → 四国"},
    "pair_Chugoku → Shikoku":           {"en": "Chugoku → Shikoku",           "ja": "中国 → 四国"},
    "pair_Chugoku → Kyushu":            {"en": "Chugoku → Kyushu",            "ja": "中国 → 九州"},

    # ── Comparison table column headers ──────────────────────────────
    "col_Region":                   {"en": "Region",                    "ja": "エリア"},
    "col_Product":                  {"en": "Product",                   "ja": "商品区分"},
    "col_Base Avg Demand (MW)":     {"en": "Base Avg Demand (MW)",      "ja": "基準 平均募集量 (MW)"},
    "col_Base Avg Contracted (MW)": {"en": "Base Avg Contracted (MW)",  "ja": "基準 平均落札量 (MW)"},
    "col_Base Avg Unprocured (MW)": {"en": "Base Avg Unprocured (MW)",  "ja": "基準 平均未調達 (MW)"},
    "col_Base Unprocured %":        {"en": "Base Unprocured %",         "ja": "基準 未調達率 %"},
    "col_Base Avg Max Price":       {"en": "Base Avg Max Price",        "ja": "基準 平均最高価格"},
    "col_Base Avg Price":           {"en": "Base Avg Price",            "ja": "基準 平均価格"},
    "col_Comp Avg Demand (MW)":     {"en": "Comp Avg Demand (MW)",      "ja": "比較 平均募集量 (MW)"},
    "col_Comp Avg Contracted (MW)": {"en": "Comp Avg Contracted (MW)",  "ja": "比較 平均落札量 (MW)"},
    "col_Comp Avg Unprocured (MW)": {"en": "Comp Avg Unprocured (MW)",  "ja": "比較 平均未調達 (MW)"},
    "col_Comp Unprocured %":        {"en": "Comp Unprocured %",         "ja": "比較 未調達率 %"},
    "col_Comp Avg Max Price":       {"en": "Comp Avg Max Price",        "ja": "比較 平均最高価格"},
    "col_Comp Avg Price":           {"en": "Comp Avg Price",            "ja": "比較 平均価格"},
    "col_Δ Demand (MW)":            {"en": "Δ Demand (MW)",             "ja": "Δ 募集量 (MW)"},
    "col_Δ Unprocured (MW)":        {"en": "Δ Unprocured (MW)",         "ja": "Δ 未調達 (MW)"},
    "col_Δ Avg Max Price":          {"en": "Δ Avg Max Price",           "ja": "Δ 平均最高価格"},
    "col_Δ Avg Price":              {"en": "Δ Avg Price",               "ja": "Δ 平均価格"},
}


def T(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """
    Look up a translated string.

    Parameters
    ----------
    key : str
        Translation key (must exist in _STRINGS).
    lang : str
        Language code ("en" or "ja").
    **kwargs
        Format-string substitutions applied to the result.

    Returns
    -------
    str
    """
    entry = _STRINGS.get(key)
    if entry is None:
        return key  # fallback: return the key itself
    text = entry.get(lang, entry.get("en", key))
    if kwargs:
        text = text.format(**kwargs)
    return text


def product_label(internal_name: str, lang: str = DEFAULT_LANG) -> str:
    """Translate a product internal name (e.g. 'Primary') to display label."""
    return T(f"prod_{internal_name}", lang)


def region_label(internal_name: str, lang: str = DEFAULT_LANG) -> str:
    """Translate a region internal name (e.g. 'Hokkaido') to display label."""
    return T(f"rgn_{internal_name}", lang)


def pair_label(internal_name: str, lang: str = DEFAULT_LANG) -> str:
    """Translate an interconnector pair name (e.g. 'Hokkaido → Tohoku')."""
    return T(f"pair_{internal_name}", lang)


def metric_labels(lang: str = DEFAULT_LANG) -> dict[str, str]:
    """Return the full metric_key → display_label dict for the given language."""
    from repower.dashboard.theme import METRIC_LABELS as _EN_LABELS
    if lang == "en":
        return dict(_EN_LABELS)
    return {k: T(f"met_{k}", lang) for k in _EN_LABELS}


def comparison_columns(lang: str = DEFAULT_LANG) -> dict[str, str]:
    """Return English column name → translated column name mapping."""
    cols = [k for k in _STRINGS if k.startswith("col_")]
    return {k[4:]: T(k, lang) for k in cols}
