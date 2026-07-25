"""
Internationalisation strings for the dashboard.

Usage::

    from repower.dashboard.i18n import T, LANG_OPTIONS

    lang = st.session_state.get("lang", "ja")
    label = T("policy_header", lang)
"""
from __future__ import annotations

# ── Available languages ─────────────────────────────────────────────────────
LANG_OPTIONS = {"ja": "日本語", "en": "English"}
DEFAULT_LANG = "ja"

# ── Translation table ───────────────────────────────────────────────────────
# Keys are arbitrary identifiers used in app_main.py.
# Each maps to {"en": …, "ja": …}.

_STRINGS: dict[str, dict[str, str]] = {
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

    # ── Policy: committee management (search / enable-disable / add) ──
    "policy_manage":            {"en": "⚙️ Manage tracked committees",
                                 "ja": "⚙️ 追跡委員会の管理"},
    "policy_manage_help":       {"en": "Toggle which committees are tracked, set summarisation priority, and add new ones. Committee edits are saved to the DB (and ride the Hugging Face sync); summaries are generated locally.",
                                 "ja": "追跡する委員会の切替・要約優先度の設定・新規追加ができます。委員会の編集はDBに保存（Hugging Face同期に同梱）され、要約はローカルで生成します。"},
    "policy_tracked_editor":    {"en": "Tracked committees — tick to track, set priority (lower = summarised first)",
                                 "ja": "追跡中の委員会 — チェックで追跡、優先度を設定（小さいほど先に要約）"},
    "policy_apply_changes":     {"en": "💾 Apply changes",         "ja": "💾 変更を適用"},
    "policy_changes_saved":     {"en": "Saved {n} change(s).",     "ja": "{n}件の変更を保存しました。"},
    "policy_no_changes":        {"en": "No changes to apply.",     "ja": "適用する変更はありません。"},
    "policy_col_enabled":       {"en": "Track",                    "ja": "追跡"},
    "policy_col_priority":      {"en": "Priority",                 "ja": "優先度"},
    "policy_col_name_en":       {"en": "Committee (EN)",           "ja": "委員会（英）"},
    "policy_col_name_ja":       {"en": "Committee (JA)",           "ja": "委員会（日）"},
    "policy_col_source":        {"en": "Source",                   "ja": "出典"},
    "policy_col_key":           {"en": "Key",                      "ja": "キー"},
    "policy_col_latest_num":    {"en": "Latest",                   "ja": "最新回"},
    "policy_discover":          {"en": "🔍 Discover new committees","ja": "🔍 新しい委員会を探す"},
    "policy_search_label":      {"en": "Search energy committees (Japanese name or English keyword)",
                                 "ja": "エネルギー関連委員会を検索（日本語名 または 英語キーワード）"},
    "policy_search_btn":        {"en": "Search the web",           "ja": "Webを検索"},
    "policy_searching":         {"en": "Searching METI / OCCTO / EGC…",
                                 "ja": "METI / OCCTO / EGC を検索中…"},
    "policy_no_candidates":     {"en": "No new committees matched. Try different keywords, or add by URL below.",
                                 "ja": "該当する新規委員会は見つかりませんでした。キーワードを変えるか、下のURL追加をお試しください。"},
    "policy_track_btn":         {"en": "➕ Track",                 "ja": "➕ 追跡する"},
    "policy_already_tracked":   {"en": "✓ tracked",               "ja": "✓ 追跡済み"},
    "policy_add_by_url":        {"en": "➕ Add a committee by URL","ja": "➕ URLで委員会を追加"},
    "policy_url_label":         {"en": "Committee homepage URL",   "ja": "委員会ページのURL"},
    "policy_probe_btn":         {"en": "Check URL",                "ja": "URLを確認"},
    "policy_checking_url":      {"en": "Checking the URL…",        "ja": "URLを確認中…"},
    "policy_add_btn":           {"en": "Add committee",            "ja": "委員会を追加"},
    "policy_added":             {"en": "Added “{name}”.",          "ja": "「{name}」を追加しました。"},
    "policy_add_failed":        {"en": "Could not read that URL — check it and try again.",
                                 "ja": "URLを読み取れませんでした。確認して再試行してください。"},
    "policy_remove":            {"en": "🗑 Remove",                "ja": "🗑 削除"},
    "policy_removed":           {"en": "Removed “{name}”.",        "ja": "「{name}」を削除しました。"},
    "policy_field_key":         {"en": "Key (unique id)",          "ja": "キー（一意なID）"},
    "policy_field_name_en":     {"en": "English name (optional)",  "ja": "英語名（任意）"},
    "policy_field_priority":    {"en": "Priority (lower = first)", "ja": "優先度（小さいほど先）"},
    "policy_field_source":      {"en": "Source",                   "ja": "出典"},

    # ── Policy: generate-on-command ──
    "policy_generate_latest":   {"en": "⚡ Summarise latest meeting","ja": "⚡ 最新会合を要約"},
    "policy_generate_meeting":  {"en": "⚡ Summarise this meeting", "ja": "⚡ この会合を要約"},
    "policy_detecting":         {"en": "Checking the site for new meetings…",
                                 "ja": "サイトの新着会合を確認中…"},
    "policy_generating":        {"en": "Summarising via NotebookLM… this can take a few minutes.",
                                 "ja": "NotebookLMで要約中…数分かかる場合があります。"},
    "policy_gen_done":          {"en": "Summarised {n} meeting(s).","ja": "{n}件の会合を要約しました。"},
    "policy_gen_none":          {"en": "Nothing pending to summarise for this committee.",
                                 "ja": "この委員会に要約待ちの会合はありません。"},
    "policy_gen_queued":        {"en": "Queued for summarisation. It will run on the next `repower policy run` / /policy-catchup.",
                                 "ja": "要約待ちに登録しました。次回の `repower policy run` / /policy-catchup で実行されます。"},
    "policy_auth_stale":        {"en": "NotebookLM sign-in is stale, so this was queued instead of run now. Run `notebooklm login` locally, then summarise.",
                                 "ja": "NotebookLMのサインインが失効しているため、即時実行せず要約待ちに登録しました。ローカルで `notebooklm login` 後に要約してください。"},
    "policy_gen_rate_limited":  {"en": "NotebookLM daily quota reached — remaining meetings stay queued; try again later.",
                                 "ja": "NotebookLMの1日の上限に達しました — 残りは待機のまま。後で再実行してください。"},
    "policy_gen_requested":     {"en": "queued",                   "ja": "要約待ち"},
    "policy_gen_error":         {"en": "Summarisation failed: {err}","ja": "要約に失敗しました: {err}"},
    "policy_gen_local_note":    {"en": "Summaries are generated on this machine and need `notebooklm login`. On the hosted dashboard, use the queue.",
                                 "ja": "要約はこの端末で生成され、`notebooklm login` が必要です。ホスティング版ではキューをご利用ください。"},

    # ── Metric labels ────────────────────────────────────────────────
    # Looked up dynamically as f"met_{key}" for every key in
    # theme.METRIC_LABELS (see metric_labels below) — keep in sync.
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


def metric_labels(lang: str = DEFAULT_LANG) -> dict[str, str]:
    """Return the full metric_key → display_label dict for the given language."""
    from repower.dashboard.theme import METRIC_LABELS as _EN_LABELS
    if lang == "en":
        return dict(_EN_LABELS)
    return {k: T(f"met_{k}", lang) for k in _EN_LABELS}
