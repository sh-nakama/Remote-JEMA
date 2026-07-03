# JEMA — Product Design Spec

*A build-ready product & visual design specification for JEMA (Japan Energy Market Analytics): a bilingual (JP/EN) web SaaS that fuses JEPX wholesale prices, EPRX balancing-market procurement, interconnector capacity, and a METI/OCCTO/EGC policy observer into one workspace. Every element is grounded in the RePower codebase; anything not yet buildable is marked PROPOSED with the integration it requires.*

## Table of Contents

1. [Product Overview & Positioning](#1-product-overview--positioning)
2. [Information Architecture & Navigation](#2-information-architecture--navigation)
3. [App Shell (global layout)](#3-app-shell-global-layout)
4. [Design System](#4-design-system)
5. [Screen — Market Overview](#5-screen--market-overview)
6. [Screen — Market Data (Wholesale & Balancing)](#6-screen--market-data-wholesale--balancing)
7. [Screen — Policy Deep Dive](#7-screen--policy-deep-dive)
8. [Data Sources, Feasibility & Open Questions (Appendix)](#8-data-sources-feasibility--open-questions-appendix)

## How to use this spec with Claude Design

- **This is a data + interaction contract, not a rendering target.** The existing app is Streamlit; JEMA is mocked as a responsive web SaaS. Treat Streamlit/D3 behaviour as the source of truth for *what the data means and how it behaves*, not for markup.
- **Tokens are named, not raw.** Reference tokens by name (Section 4). Concrete HEX values live in the design-system section; components cite `--token` names so a palette change is one edit.
- **Status legend used throughout:** **EXISTS** = queryable today from a cited table/field; **DERIVED** = computed at read time from existing data (no new collection); **PROPOSED** = not in the codebase, requires the named integration. Render every PROPOSED surface in a clearly labelled empty/awaiting state — never as populated live data.
- **One accent, consistently.** The single confident interactive accent is teal `#00A5CF` everywhere (Section 4a resolves this). Navy `#1B2A4A` is ink / dark-surface, not the interactive accent.
- **Bilingual is first-class.** Every user-facing string flows through `T(key, lang)`; default language **ja**. Never hardcode display text; never machine-translate JP source documents on the fly.
- **Brand rule (hard):** user-facing brand is **JEMA / Japan Energy Market Analytics** only. Never surface the repo name or any legacy product string in chrome, copy, or examples.

---

## 1. Product Overview & Positioning

### 1.1 One-line value proposition

> **JEMA — Japan Energy Market Analytics.** The one-stop intelligence hub for Japan's power markets: wholesale prices, balancing-market procurement, interconnector capacity, and live policy signals — half-hourly data and committee-level insight, in one bilingual workspace.

**JP:** 日本の電力市場を一つに。卸売価格・需給調整市場・連系線・政策動向を、30分単位のデータと委員会レベルの洞察で束ねる、日英対応のインテリジェンス基盤。

Positioning notes for the designer:

- **Category:** premium, independent energy-analytics SaaS (boutique, not a mass-market terminal).
- **Tone made visual:** authoritative, precise, data-forward, quietly premium. This translates to airy whitespace, a single confident accent, muted neutral text hierarchy, and restrained motion. No dashboard "gamification," no loud gradients except the one dark feature card.
- **Differentiator to surface in the shell:** JEMA is the only view that fuses **market data** (JEPX wholesale + EPRX balancing/tieline) with a **policy observer** (METI / OCCTO / EGC committee tracking and NotebookLM-generated briefings). The landing (Market Overview) is where those two worlds meet.
- **Brand naming rule (hard):** user-facing brand is **JEMA / Japan Energy Market Analytics** only. Never surface the repo name or any legacy product string in chrome, copy, or examples.

### 1.2 Primary personas and what each needs from the landing view

| Persona | Who they are | Primary jobs-to-be-done | What they need on the landing (Market Overview) first-fold |
|---|---|---|---|
| **① Energy traders / analysts** (トレーダー・アナリスト) | Desk traders and market analysts at utilities, trading houses, and funds tracking JEPX day-ahead and EPRX balancing. | Read today's clearing prices per area; spot spreads and anomalies; compare periods; catch balancing scarcity (missing/unprocured MW). | Latest **JEPX area price** KPIs (avg / peak, ¥/kWh), a **wholesale price trend** chart, a **balancing scarcity** signal (unprocured MW), and quick jump to Market Data with their watched areas/products preselected. Freshness stamp is non-negotiable. |
| **② Commercial investors & IPP developers** (投資家・IPP開発者) | Investment/BD teams evaluating generation, storage, and renewables projects; IPP developers modeling revenue stacks. | Understand structural trends (generation mix, renewable share, area price differentials); assess balancing-market revenue opportunity; monitor tieline constraints affecting siting. | **Generation-mix / renewable-share** snapshot, **area price differential** view (which areas run rich/cheap), **balancing product** revenue signals, and interconnector capacity context. Prefers Daily/Weekly aggregation over half-hourly noise. |
| **③ Policy / regulatory-affairs teams** (政策・規制対応チーム) | Government-affairs, regulatory, and strategy staff at utilities, trade bodies, and advisories tracking market-design reform. | Stay ahead of METI/OCCTO/EGC deliberations; get fast bilingual briefings on new committee meetings; connect policy moves to market data. | A **Policy pulse** card: newest/important committee meetings, an English digest teaser, and "unread since last visit." Wants one click into the Policy Deep Dive with the committee already open. |

Design implication: the landing must serve all three in one scannable fold — **prices for ①, structural trends for ②, policy pulse for ③** — without forcing a role switch. Personalization is achieved through the **watchlist** (areas, products, committees a user follows), not through separate role dashboards.

---

## 2. Information Architecture & Navigation

### 2.1 Top-level destinations (mapped to the client's vision)

Three primary destinations, plus a settings/account area. Each maps directly to the client's three-part vision and to what exists in the codebase.

| # | Destination | EN label | JP label | Icon (line, monochrome) | Purpose | Grounding |
|---|---|---|---|---|---|---|
| a | **Market Overview** | Market Overview | マーケット概況 | `layout-dashboard` | The **hybrid landing** — KPI strip + trend/mix/policy-pulse mixed grid; a curated cross-section of everything. | Aggregates existing JEPX, EPRX, and policy tables. |
| b | **Market Data** | Market Data | マーケットデータ | `bar-chart-3` | Wholesale + balancing **deep data**: the 9-area × 2-column grids, aggregation, period comparison, interconnectors, export. | `DemandSupply30m`, `JepxAreaPrice30m`, EPRX balancing/tieline Parquet; `app_main.py` grid, `read.py` loaders. |
| c | **Policy Deep Dive** | Policy Deep Dive | 政策ディープダイブ | `landmark` | The **policy observer**: committee running documents, per-meeting briefings, English digests, discovery, tracked-committee management. | `PolicyCommittee` / `PolicyMeeting` / `PolicyMaterial`; `pipeline.py`, `store.py`. |

Under **Market Data**, the sub-destinations reflect the existing tab structure. All four sub-destinations are reachable on-screen (see the sub-view segmented control in Section 6.1):

| Sub-item | EN | JP (canonical `T()` value) | Icon | Binds |
|---|---|---|---|---|
| Wholesale | Wholesale | 卸電力（JEPX） | `line-chart` | JEPX area price + generation mix |
| Balancing | Balancing | 需給調整市場 | `activity` | EPRX 7 products, volumes + clearing price |
| Interconnectors | Interconnectors | 連系線 | `git-compare-arrows` | EPRX tieline — DCM (需給調整市場 / Balancing Market) & DAM (三次調整力② / Tertiary 2) |
| Drivers | Drivers | ドライバー | `flame` | `FuelDaily` (Brent / NG / FX) + JEPX correlation |

The Interconnectors panel (Section 6.5.5) exposes the tieline **market selector** with its full meaning: **DCM (需給調整市場 / Balancing Market)** and **DAM (三次調整力② / Tertiary 2)** — per i18n keys `tieline_market_dcm` / `tieline_market_dam` — so a designer never mislabels DAM as a generic "day-ahead" market.

> **Note on "Analyses":** the existing Analyses tab binds `AnalysisRecord`. Its `features_json` is written today, but `narrative_md` (the LLM narrative) is **NOT generated** — the column is scaffolded, not wired. Analyses is therefore **omitted from primary nav** in this spec. If/when generation is wired, add it under Market Overview as an **"AI Daily Brief"** card, marked **PROPOSED**; in the prototype it renders only an empty/awaiting state (see 5.10) and is never bound to live narrative data.

### 2.2 Supporting global systems

| System | EN | JP | Where it lives | Status |
|---|---|---|---|---|
| **Global search** | Search markets & committees | 市場・委員会を検索 | Top bar | PROPOSED — needs a unified index over areas/products/pairs (from `theme.py`/`i18n.py` label maps) + committees/meetings (`PolicyCommittee`/`PolicyMeeting`). Client-side static index over the finite known entities is feasible today; no new data source required. |
| **Watchlist / follow** | Watchlist / Follow | ウォッチリスト / フォロー | Sidebar GENERAL group + follow-star on entities | PROPOSED — needs a per-user `watchlist` store (areas, products, tieline pairs, committee keys). No such table today; add a `watchlist` table or user-prefs JSON. |
| **Notifications** | Notifications | 通知 | Top bar bell | PARTIAL — new-meeting events derivable from `PolicyMeeting.detected_at`; committee importance from `priority`. **Price alerts are PROPOSED** and need a threshold-evaluation job over `JepxAreaPrice30m` / EPRX prices (rules defined in 3.5). |
| **Language toggle** | 日本語 / English | 日本語 / English | Top bar | EXISTS — `LANG_OPTIONS = {"ja","en"}`, `DEFAULT_LANG="ja"`, `T(key, lang)` in `i18n.py`. |
| **Account** | Account | アカウント | Top bar avatar → menu | PROPOSED — no auth today (Streamlit app). Needs auth + user record for the SaaS web app. |

### 2.3 Sitemap

```
JEMA (bilingual JP/EN — default JA)
│
├── Market Overview  ｜ マーケット概況              [landing / hybrid]
│     ├─ KPI strip (JEPX avg, JEPX peak, Balancing unprocured, Policy pulse)
│     ├─ Wholesale price trend (watched areas)
│     ├─ Generation mix / renewable share snapshot
│     ├─ Balancing scarcity signal
│     ├─ Policy pulse (newest / important meetings — the METI Committee Radar)
│     └─ Watchlist quick-glance
│
├── Market Data  ｜ マーケットデータ
│     ├── Wholesale       ｜ 卸電力（JEPX）
│     │     ├─ 9-area × 2-col grid (mix + price)
│     │     ├─ Aggregation (Native / Daily / Weekly / Monthly)
│     │     ├─ Period Comparison
│     │     └─ Export (Excel / PDF)
│     ├── Balancing       ｜ 需給調整市場
│     │     ├─ Product selector (7 products)
│     │     ├─ 9-area × 2-col grid (volume + clearing price)
│     │     ├─ Aggregation · Period Comparison · Export
│     │     └─ Interconnectors panel (DCM / DAM)
│     ├── Interconnectors ｜ 連系線     (also reachable standalone)
│     └── Drivers         ｜ ドライバー  (fuels / FX / correlation)
│
├── Policy Deep Dive  ｜ 政策ディープダイブ
│     ├─ Committee list (METI / OCCTO / EGC, by priority)
│     ├─ Running document (per committee)
│     ├─ Per-meeting briefings (JP) + English digest
│     ├─ Discovery (web search / add-by-URL)
│     └─ Manage tracked committees
│
└── Globals (persistent chrome)
      ├─ Global search        ｜ 市場・委員会を検索
      ├─ Watchlist / Follow   ｜ ウォッチリスト / フォロー
      ├─ Notifications        ｜ 通知
      ├─ Language toggle      ｜ 日本語 / English
      └─ Account & Settings   ｜ アカウント / 設定
```

### 2.4 Complete nav label glossary (JP + EN) — single source of truth

These `T()` values are the canonical bilingual labels. Every screen references these keys; no section may re-render these two destinations with alternate Japanese wording.

| Key | English | 日本語 |
|---|---|---|
| `nav_group_menu` | MENU | メニュー |
| `nav_group_general` | GENERAL | 全般 |
| `nav_overview` | Market Overview | マーケット概況 |
| `nav_market_data` | Market Data | マーケットデータ |
| `nav_wholesale` | Wholesale | 卸電力（JEPX） |
| `nav_balancing` | Balancing | 需給調整市場 |
| `nav_interconnectors` | Interconnectors | 連系線 |
| `nav_drivers` | Drivers | ドライバー |
| `nav_policy` | Policy Deep Dive | 政策ディープダイブ |
| `nav_watchlist` | Watchlist | ウォッチリスト |
| `nav_notifications` | Notifications | 通知 |
| `nav_settings` | Settings | 設定 |
| `nav_account` | Account | アカウント |
| `nav_search_placeholder` | Search markets, areas, committees… | 市場・エリア・委員会を検索… |
| `nav_lang_toggle` | 日本語 / English | 日本語 / English |
| `nav_help` | Help & docs | ヘルプ・ドキュメント |

---

## 3. App Shell (global layout)

The shell adapts the **Donezo** reference structure and polish: left vertical sidebar (logo → grouped nav → pinned utility card), a top bar (search + icons + user), and an airy main content region. Design-system tokens are referenced by name; concrete values are in Section 4.

### 3.1 Responsive layout grid

| Region | Placement | Desktop (≥1280px) | Tablet (768–1279px) | Mobile (<768px) |
|---|---|---|---|---|
| **Sidebar** | Fixed left, full height | `264px` expanded; `72px` collapsed (icon-rail) | Collapsed icon-rail (`72px`) by default; expands on hover/toggle as overlay | Hidden; opens as full-height drawer from a hamburger in the top bar |
| **Top bar** | Fixed top, spans content region | Height `72px`, spans viewport minus sidebar | Same, spans minus rail | Height `56px`; search collapses to an icon that expands to full-width overlay |
| **Main content** | Right of sidebar, below top bar | Max content width `1800px`, centered, `32px` gutters; 12-column fluid grid, `24px` gap | 12→8 column reflow, `24px` gutters | Single column, `16px` gutters, cards stack |

- **Grid tokens:** 12-column fluid grid, `--space-gap: 24px`, page padding `--space-page: 32px` (desktop) / `16px` (mobile). Content max-width `1800px` (inherited from shipped `.block-container`).
- **Breakpoints:** `--bp-sm: 768px`, `--bp-md: 1024px`, `--bp-lg: 1280px`, `--bp-xl: 1536px`.
- **Card radius / shadow:** `--radius-card: 16–20px`, `--shadow-card: soft diffuse (0 1px 3px rgba(27,42,74,0.06), 0 8px 24px rgba(27,42,74,0.05))`. Buttons pill-shaped (`--radius-pill: 999px`).
- **Surfaces:** page background `--color-bg (#F6F8FB)`, cards `--color-surface (#FFFFFF)`, **accent `--color-accent (#00A5CF)`** (the single interactive accent), primary ink `--color-ink (#1B2A4A)`, body text `--color-text (#333333)`, borders `--color-border (#E8E8E8)`.

### 3.2 Sidebar navigation

**Structure (top → bottom):**

1. **Logo lockup** (top, `24px` padding): "JEMA" wordmark in `--color-ink`, with a small ⚡ mark in `--color-accent`. Collapsed rail shows the ⚡ mark only. Beneath the wordmark, a `9px` uppercase tagline "Japan Energy Market Analytics" / 「日本エネルギー市場分析」 (hidden when collapsed).
2. **MENU group** (`nav_group_menu` — MENU / メニュー): the primary destinations.
3. **GENERAL group** (`nav_group_general` — GENERAL / 全般): supporting/global items.
4. **Pinned utility card** (bottom): a compact "Data freshness" card (dark-gradient variant of the feature card) showing last sync time + a follow-up CTA.

**Nav items and grouping:**

| Group | Item | Icon | Notes |
|---|---|---|---|
| MENU | Market Overview / マーケット概況 | `layout-dashboard` | Default landing; active on first load. |
| MENU | Market Data / マーケットデータ | `bar-chart-3` | Expands to sub-items (Wholesale, Balancing, Interconnectors, Drivers). |
| MENU | Policy Deep Dive / 政策ディープダイブ | `landmark` | Shows an unread-count badge when new meetings detected. |
| GENERAL | Watchlist / ウォッチリスト | `star` | Count badge = number of followed entities. |
| GENERAL | Notifications / 通知 | `bell` | Count badge = unread alerts; mirrors top-bar bell. |
| GENERAL | Settings / 設定 | `settings` | Language default, alert thresholds, export prefs. |

**Sub-item behavior (Market Data):** clicking the parent expands an indented accordion (left inset `+16px`, small dot markers). On collapsed rail, hovering the parent opens a flyout submenu.

**States:**

| State | Treatment |
|---|---|
| **Default** | Item label `--color-text-muted`, icon monochrome `--color-text-muted`, transparent background. |
| **Hover** | Background `--color-hover (rgba(0,165,207,0.06))`, label/icon shift to `--color-ink`, `120ms` ease. |
| **Active / selected** | **Accent pill** background (`--color-accent-soft`, rounded `12px`) spanning the item, label + icon in `--color-accent` (or `--color-ink` on soft fill), plus a **`3px` left color bar** in `--color-accent` flush to the sidebar edge. Only one active at a time; parent of an active sub-item also shows the left bar. |
| **Focus (keyboard)** | `2px` focus ring `--color-accent` at `40%` opacity, offset `2px`. |
| **Badge** | Small pill on the right (`--color-accent` fill, white `10px` numerals) for unread counts. |
| **Collapsed** | Icons centered in the `72px` rail; labels hidden; tooltip on hover shows the full JP/EN label; active item keeps the left color bar + a subtle icon-background pill. |

**Collapse toggle:** a `chevrons-left` / `chevrons-right` button pinned at the sidebar footer above the utility card; state persists per user (Settings). On tablet the rail is collapsed by default.

### 3.3 Top bar

Left-to-right, height `72px` (desktop):

1. **Breadcrumb / page context** (far left, optional): current section name echoing the page title, muted. On mobile this is replaced by a hamburger that opens the sidebar drawer.
2. **Global search field** (center-left, flex-grow, max `520px`): large rounded (`--radius-pill` or `12px`) input, `search` icon leading, placeholder "Search markets, areas, committees…" / 「市場・エリア・委員会を検索…」, and a trailing **keyboard hint chip** (`⌘K` / `Ctrl K`). States: default (border `--color-border`), hover (border darkens), focus (border `--color-accent`, soft glow), active-typing (dropdown of grouped results: **Areas · Products · Interconnectors · Committees**), empty-results ("No matches / 一致する項目がありません"). Loading shows a subtle inline spinner.
3. **Icon buttons** (right cluster, `40px` circular, ghost):
   - **Mail / inbox** (`mail`) — reserved; PROPOSED (no messaging backend today) — can be hidden in v1 or shown disabled with tooltip "Coming soon / 近日公開".
   - **Notifications** (`bell`) — dot/count badge; opens a right-aligned popover listing new important meetings and price alerts (see 3.5).
4. **Language toggle** (`nav_lang_toggle`): a compact segmented control `日本語 | English` (or a globe `languages` icon opening a 2-item menu). Reflects `st.session_state.lang`; persists to Settings; re-renders all `T()`-backed copy. Default **日本語**.
5. **User cluster** (far right): circular **avatar** + stacked **name** (`--color-ink`, `13px` 600-weight) and **email** (`--color-text-muted`, `11px`). Click opens an account menu: Account / アカウント, Settings / 設定, Language, Help & docs / ヘルプ・ドキュメント, Sign out / サインアウト. (Auth is PROPOSED; in the prototype, bind to a placeholder user, e.g. name "Analyst", neutral email domain.)

Top-bar states: sticky on scroll with a `1px` bottom hairline `--color-border` and a faint shadow appearing only once scrolled (`--shadow-topbar`).

### 3.4 Content region

- **Page header row** (top of main): **page title** (H2, `--color-ink`, 600-weight) + **one-line subtitle** (`--color-text-muted`) on the left; a **primary action** (accent-filled pill button) and a **secondary action** (outline pill button) on the right. Example (Market Overview): primary **"Open Market Data / マーケットデータを開く"**, secondary **"All Committees / 政策レーダー全体"**. Example (Market Data): primary **"Export / エクスポート"**, secondary **"Compare periods / 期間比較"**.
- **Freshness stamp:** immediately under the subtitle or as a small chip near the actions — "Updated {timestamp} JST / 更新: {timestamp} JST" bound to the HF sync time (from `last_refreshed_at` / DB max date). Data is JST; state the timezone explicitly.
- **Content grid:** cards laid on the 12-column grid with `--space-gap`. KPI strips use 4×3-col cards on desktop, 2×2 on tablet, stacked on mobile. Charts occupy 6–12 cols depending on emphasis.
- **Global loading:** skeleton cards (shimmer on `--color-surface`) while data loads; charts show an axis skeleton. **Empty state:** centered muted illustration + one-line guidance and a CTA (e.g., "No committees tracked yet / 追跡中の委員会がありません"). **Error state:** inline card with an `alert-triangle` icon, message, and a "Retry / 再試行" button; never a raw traceback (matches the codebase's clean-message convention).

### 3.5 Notifications popover (shell-level)

Opened from the top-bar bell (and mirrored by the sidebar Notifications item). Right-aligned popover, `360px` wide, card radius, soft shadow.

| Section | Content | Binding / status |
|---|---|---|
| **New policy meetings** / 新規の会合 | List of newly detected meetings for followed/high-priority committees: committee name (`region/committee` label), meeting number + date, "New" chip. | EXISTS — `PolicyMeeting.detected_at`, importance via `PolicyCommittee.priority`. |
| **Price alerts** / 価格アラート | Threshold breaches, e.g. "TEPCO JEPX avg > ¥18/kWh (Daily)". | PROPOSED — see rule definition below. |
| **Footer** | "Mark all read / すべて既読に" + "View all / すべて表示" (→ Notifications page). | — |

**Price-alert rule definition (PROPOSED — needed so the prototype can render the concrete example alert).** A price alert fires when a monitored metric crosses a user-set threshold within a chosen aggregation bucket:

- **Rule shape:** `{scope, metric, comparator, threshold, aggregation, direction}` — e.g. `TEPCO · JEPX avg price · > · ¥18/kWh · Daily · rising`.
- **Scope:** per-user in the shipped SaaS (each user's Settings hold their rules); until auth exists (PROPOSED), the prototype uses a single **global** rule set stored in prefs.
- **Metrics available:** `JepxAreaPrice30m.price` (per area or System), EPRX `price_avg`/`price_max` (per product), EPRX `missing_mw` (unprocured breach). Evaluated by a threshold-evaluation job on each daily ingest (there is no rule engine today — this is the PROPOSED piece; webhook delivery plumbing exists per `notify/webhook.py`).
- **Dedup:** at most one alert per rule per aggregation bucket (e.g. one "TEPCO > ¥18 (Daily)" alert per day); re-arm on the next bucket. Suppress repeats while the condition stays continuously true.
- **Rendering:** the example alert "TEPCO JEPX avg > ¥18/kWh (Daily)" renders as a list row with area chip, breached value, threshold, and timestamp.

States: default (list), empty ("You're all caught up / 未読はありません"), loading (skeleton rows), item hover (row tint `--color-hover`), unread (accent left dot).

---

## 4. Design System

The JEMA design system is a token-first specification. Every value below is a named token intended for direct use in Claude Design; component specs reference tokens by name rather than raw HEX. The system is grounded in the colors, metrics, and data model that already exist in the RePower codebase (`src/repower/dashboard/theme.py`, `i18n.py`, `read.py`, `db.py`) — no data binding is invented. All inherited color names are neutral.

---

### 4a. Brand & Art Direction

**Art direction.** Quietly premium, data-forward, Japanese-precise. Airy whitespace, one confident accent, muted neutral hierarchy, generous radii, soft diffuse shadows, small monochrome line icons. Charts are the hero; chrome recedes. The reference "Donezo" polish (pill buttons, ~16–20px card radius, single accent, ghost/striped inactive states) is adopted at the structural level, not the content level.

**The single accent is teal `#00A5CF`, decided once for the whole spec.** It is the only confident interactive accent — used for the primary button, active nav pill, the one accent-filled KPI card per row, chart hero line, active tab/segment, rank #1, and focus rings. Navy `#1B2A4A` is **ink and dark-surface** (headings, sidebar, dark feature card, table header), never the interactive accent. There is no "navy or teal" choice anywhere; every screen (including Policy, Section 7) uses teal as `--fill-accent` and navy as ink/surface-inverse.

#### Two candidate palettes

Both reuse HEX values already present in the codebase so charts stay consistent with shipped RePower components (`theme.py`), but rename all constants to neutral JEMA tokens.

**Palette A — "Harbor" (RECOMMENDED).** Deep navy ink + cyan-teal accent. This is the palette the existing D3 charts, PDF/Excel exports, and metric colors are already built around (`#1B2A4A`, `#00A5CF`), so adopting it means zero re-coloring of the data layer and maximal visual coherence between KPI chrome and chart interiors. Reads as institutional, trustworthy, "market-terminal premium."

| Token | HEX | Role |
|---|---|---|
| `color.brand.ink` | `#1B2A4A` | Primary brand navy — ink / dark surfaces |
| `color.brand.accent` | `#00A5CF` | Accent cyan-teal — the single confident interactive accent |
| `color.brand.accent-deep` | `#264653` | Deep teal for secondary emphasis / gradient end |
| `color.brand.ink-tint-90` | `#2E3E5E` | Navy hover/pressed |
| `color.brand.accent-tint-12` | `rgba(0,165,207,0.12)` | Accent wash (chart bands, active pill fill) |

**Palette B — "Slate/Amber" (alternative).** Cooler graphite ink with a warm amber accent (`#E9C46A`, already the solar/gold data color). Distinguishes chrome-accent from the teal used heavily inside charts, at the cost of chrome/data color coherence. Choose only if the client wants a warmer, more editorial feel.

| Token | HEX | Role |
|---|---|---|
| `color.brand.ink` | `#22262E` | Graphite ink |
| `color.brand.accent` | `#E9C46A` → CTA text darkened to `#1B2A4A` | Amber accent (needs dark text for contrast) |
| `color.brand.accent-deep` | `#C1440E` | Burnt-orange emphasis |

> **Recommendation:** ship **Palette A ("Harbor")**. It is contrast-safe on white for accent-on-light chips and matches the entire existing chart palette; Palette B's amber accent fails WCAG AA as a text/icon color on white and forces dark-on-amber buttons, which reads less premium.

#### Semantic tokens (Palette A, light mode)

| Semantic token | HEX | Notes / source |
|---|---|---|
| `bg` | `#F6F8FB` | App background (airy, cooler than pure white) |
| `surface` | `#FFFFFF` | Cards, top bar, sidebar cards |
| `surface-alt` | `#FAFAFA` | Chart interiors, table zebra |
| `surface-inverse` | `#1B2A4A` | Sidebar, dark feature card, table header |
| `text-primary` | `#1B2A4A` | Headings, metrics |
| `text-secondary` | `#4A5568` | Body, subtitles |
| `text-muted` | `#8A93A3` | Captions, axis labels, disabled |
| `text-on-inverse` | `#FFFFFF` | Text on navy surfaces |
| `border` | `#E8E8E8` | Card/table borders |
| `border-strong` | `#CBD2DC` | Input borders, dividers on white |
| `accent` | `#00A5CF` | The single primary interactive accent |
| `positive / up` | `#2A9D8F` | Positive delta |
| `negative / down` | `#E63946` | Negative delta, unprocured, price spikes |
| `warning` | `#F4A261` | Quota/stale-data warnings |
| `info` | `#4A6FA5` | Neutral informational |
| `focus-ring` | `#00A5CF` @ 40% + 2px offset | Keyboard focus |

#### DATA tokens — 9-area per-TSO palette

Bound to `AREA_ORDER` (`db.py` / `scrapers.areas`). This palette is **new** (there is no shipped per-area color map — the grid renders one area per card, so RePower never needed one). It is chosen for categorical distinctness AND colorblind-safety (see 4h), drawing HEX from the existing brand/fuel pools so it composes with chart interiors.

| Area token | Area (EN / JA) | HEX |
|---|---|---|
| `color.area.hokkaido` | Hokkaido / 北海道 | `#1B2A4A` |
| `color.area.tohoku` | Tohoku / 東北 | `#00A5CF` |
| `color.area.tepco` | Tokyo / 東京 | `#7B2D8E` |
| `color.area.chubu` | Chubu / 中部 | `#2A9D8F` |
| `color.area.hokuriku` | Hokuriku / 北陸 | `#4A6FA5` |
| `color.area.kansai` | Kansai / 関西 | `#E76F51` |
| `color.area.chugoku` | Chugoku / 中国 | `#C1440E` |
| `color.area.shikoku` | Shikoku / 四国 | `#E9C46A` |
| `color.area.kyushu` | Kyushu / 九州 | `#8AB17D` |

#### DATA tokens — fuel / generation-mix palette

**Exists today**, verbatim from `theme.GENERATION_COLORS` (do not alter — the stacked-area chart, legend, and exports depend on these). Renamed to `color.fuel.*` tokens.

| Fuel token | Fuel | HEX | | Fuel token | Fuel | HEX |
|---|---|---|---|---|---|---|
| `color.fuel.nuclear` | Nuclear / 原子力 | `#7B2D8E` | | `color.fuel.geothermal` | Geothermal / 地熱 | `#C1440E` |
| `color.fuel.lng` | LNG | `#00A5CF` | | `color.fuel.biomass` | Biomass / バイオマス | `#2A9D8F` |
| `color.fuel.coal` | Coal / 石炭 | `#3A3A3A` | | `color.fuel.solar` | Solar / 太陽光 | `#E9C46A` |
| `color.fuel.oil` | Oil / 石油 | `#6B4226` | | `color.fuel.wind` | Wind / 風力 | `#4FB0A5` |
| `color.fuel.thermal-other` | Other Thermal / その他火力 | `#9C6B4E` | | `color.fuel.pumped` | Pumped / 揚水 | `#4A6FA5` |
| `color.fuel.hydro` | Hydro / 水力 | `#1B2A4A` | | `color.fuel.battery` | Battery / 蓄電池 | `#8AB17D` |
| `color.fuel.interconnect` | Interconnect / 連系 | `#9AA0A6` | | `color.fuel.other` | Other / その他 | `#C9CCD1` |

`color.fuel.total` = `#1B2A4A` — **overlay line only, never a stack layer** (mirrors the `total_supply` rule in `theme.py`).

**Balancing product tokens** (`color.product.*`) and **tieline tokens** (`color.tieline.*`) carry over verbatim from `PRODUCT_COLORS` and the tieline block of `METRIC_COLORS` — 7 products (Primary `#1B2A4A` … Composite `#7B2D8E`) and 4 tieline metrics (`upper_limit_fwd #264653`, `upper_limit_rev #7B2D8E`, `reserved_fwd #E9C46A`, `reserved_rev #E76F51`).

---

### 4b. Typography

Two families: a JP-capable UI typeface and a Latin/tabular partner. Inter is already the shipped Latin face (`FONT_STACK` in `theme.py`); we keep it and add a Japanese companion whose metrics match Inter closely.

| Role | Family | Fallback |
|---|---|---|
| Latin UI + numerals | **Inter** | `'Segoe UI', system-ui, -apple-system, sans-serif` (matches shipped `FONT_STACK`) |
| Japanese UI | **Noto Sans JP** | `'Hiragino Kaku Gothic ProN', 'Yu Gothic', 'Meiryo', sans-serif` |
| Tabular numerals (metrics, tables, prices) | Inter with `font-feature-settings: "tnum" 1` | — |

Rule: `font.stack.jp = "'Inter', 'Noto Sans JP', 'Hiragino Kaku Gothic ProN', 'Yu Gothic', system-ui, sans-serif"` — Inter first so Latin glyphs use Inter and JP glyphs fall through to Noto Sans JP. Weights: 300/400/500/600/700.

#### Type scale

| Token | Size / line-height | Weight | Usage |
|---|---|---|---|
| `type.display` | 32 / 40 | 700 | Page title (e.g. dashboard hero) |
| `type.h1` | 24 / 32 | 700 | Section/page headers |
| `type.h2` | 20 / 28 | 600 | Card group titles |
| `type.h3` | 16 / 24 | 600 | Card titles ("Tokyo — Price") |
| `type.metric` | 34 / 40 | 700, `tnum` | KPI big number |
| `type.metric-sm` | 22 / 28 | 700, `tnum` | Secondary metrics, table totals |
| `type.body` | 14 / 22 | 400 | Body copy, list rows |
| `type.body-strong` | 14 / 22 | 600 | Emphasized labels, active tab |
| `type.label` | 13 / 18 | 600 | Card labels, chip text (uppercase optional for EN only) |
| `type.caption` | 12 / 16 | 400 | Subtitles, source captions, deltas |
| `type.micro` | 9–11 / 14 | 400 | Chart axis labels (9px matches shipped D3 charts), legends |

Note: never uppercase Japanese text; `text-transform: uppercase` applies to `:lang(en)` only.

---

### 4c. Spacing, Radius, Shadow, Elevation, Grid

#### Spacing scale (4px base)

`space.0`=0, `space.1`=4, `space.2`=8, `space.3`=12, `space.4`=16, `space.5`=20, `space.6`=24, `space.8`=32, `space.10`=40, `space.12`=48, `space.16`=64. Card interior padding = `space.5` (20px); page gutters = `space.8`.

#### Radius scale

| Token | px | Usage |
|---|---|---|
| `radius.sm` | 8 | Chips, inputs, small buttons (matches shipped metric card `8px`) |
| `radius.md` | 12 | Nested panels, chart interior frame |
| `radius.lg` | 18 | Cards, KPI cards, chart cards (Donezo ~16–20) |
| `radius.xl` | 24 | Feature card, modal |
| `radius.pill` | 999 | Buttons, segmented control, filter chips |

#### Shadow / elevation

| Token | Value | Elevation use |
|---|---|---|
| `shadow.xs` | `0 1px 3px rgba(27,42,74,0.06)` | Resting cards (matches shipped metric card) |
| `shadow.sm` | `0 2px 8px rgba(27,42,74,0.08)` | KPI cards, chart cards |
| `shadow.md` | `0 8px 24px rgba(27,42,74,0.10)` | Hover lift, popovers, dropdowns |
| `shadow.lg` | `0 16px 48px rgba(27,42,74,0.16)` | Modal, side drawer |
| `elevation.focus` | `0 0 0 3px rgba(0,165,207,0.35)` | Focus ring companion |

#### Responsive 12-column grid

| Breakpoint | Range | Columns | Gutter | Margin | Sidebar |
|---|---|---|---|---|---|
| `bp.xs` (mobile) | < 640 | 4 | 16 | 16 | off-canvas drawer |
| `bp.sm` (tablet-p) | 640–1023 | 8 | 20 | 24 | collapsed rail (icons) |
| `bp.md` (tablet-l) | 1024–1279 | 12 | 24 | 32 | 72px rail, expandable |
| `bp.lg` (desktop) | 1280–1799 | 12 | 24 | 40 | 264px fixed |
| `bp.xl` (wide) | ≥ 1800 | 12 | 24 | auto (max-width 1800, matches shipped `.block-container`) | 264px fixed |

Content max-width 1800px (inherited from shipped CSS). KPI row = 4 cards each spanning 3 cols at `lg`, 2×2 at `sm`, stacked at `xs`. The 9-area market grid = 2 cards per row at `lg`/`xl` (left supply, right price), 1 per row below `md`.

---

### 4d. Core Component Library

Every component references tokens above. States listed as: default / hover / active(pressed) / selected / focus / disabled / loading / empty / error where applicable.

#### Buttons

| Variant | Default | Hover | Pressed | Disabled | Loading |
|---|---|---|---|---|---|
| **Primary** (accent-filled, pill) | `accent` bg, white text, `radius.pill`, `shadow.xs` | `accent` −8% + `shadow.md` | `accent` −14%, no shadow | 40% opacity, no shadow | spinner + label dimmed, non-interactive |
| **Secondary** (outline) | `surface` bg, `border-strong`, `text-primary` | `surface-alt` bg | `border` inset | 40% opacity | inline spinner |
| **Ghost / tertiary** | transparent, `text-secondary` | `surface-alt` bg | — | muted | — |
| **Icon-button** (32px, the KPI up-right arrow ↗) | `surface`, `border`, monochrome icon | `surface-alt`, `accent` icon | pressed inset | muted | — |
| **Danger** | `negative` bg, white | `negative` −8% | −14% | 40% | — |

Focus (all): `elevation.focus` ring. Sizes: sm 32h / md 40h / lg 48h. Example copy: **Refresh data / データ更新**, **Export PDF / PDF出力** (from `i18n.py` keys `refresh_btn`, `export_pdf`).

#### KPI / Stat card

Content: label (`type.label`, `text-muted`), big metric (`type.metric`, `tnum`), delta chip, icon-button (↗) top-right. Two variants: **filled** (exactly one per row — `surface-inverse` navy bg, `text-on-inverse`, delta chip inverted) and **default** (`surface`, `border`, `shadow.sm`). States: hover (lift to `shadow.md`), loading (shimmer skeleton on metric + chip), empty ("—" metric, muted "No data / データなし"), error (`negative` left bar + "Load failed / 読み込み失敗").

#### Chart card

Header row: title (`type.h3`, `text-primary`) + subtitle (`type.caption`, `text-muted`) left; toolbar right (aggregation segmented control, fullscreen icon-button `⊞` — carried from shipped D3 charts). Body: chart at `radius.md` `surface-alt` interior, `space.5` padding matching shipped `.chart-container`. States: loading (axis skeleton + centered spinner), empty ("No data for selected range / 選択期間のデータなし"), error (`warning` banner). Fullscreen expands margins/fonts (9→12px axis) per shipped behavior.

#### Sub-view switcher (segmented control) — Market Data top-level view

This is the top-level view switch for the **Market Data** screen (Section 6). It is a **segmented control**, not a legacy 5-tab bar, and it is consistent with the IA in Section 2 (Policy is a **top-level destination**, not a tab, and Analyses is omitted from nav):

- **Segments:** **Wholesale (Spot) / 卸電力（JEPX）** and **Balancing / 需給調整市場** — using the canonical `nav_wholesale` / `nav_balancing` glossary values from 2.4. (Section 6.1 additionally exposes **Interconnectors / 連系線** and **Drivers / ドライバー** as sibling Market-Data sub-destinations via a secondary control, so all four sub-destinations from 2.1 are reachable on-screen.)
- **Active state:** single accent-filled segment (teal `#00A5CF`), `text-on-inverse`; inactive segments `text-muted` on `surface-alt`. Focus ring on the control; arrow-key navigable (roving tabindex).
- **Performance note:** **only the active view renders** (the perf pattern is preserved from the shipped app — keeps D3 chart sizing correct).

There is **no** "Analyses" or "Policy" segment in this component — Policy is reached from the primary sidebar nav, and Analyses is not in nav (see 2.1).

#### Aggregation & mode segmented controls

Aggregation switch **Native / Daily / Weekly / Monthly (生 / 日次 / 週次 / 月次)** and the Grid/Comparison toggle. Pill container `surface-alt`, selected segment `surface` + `shadow.xs` + `text-primary`; unselected `text-muted`. Sizes sm/md.

#### Filter chips

Area/product selection. Default `surface` `border` pill; **selected** `accent-tint-12` fill + `accent` border + `accent` text; hover `surface-alt`; removable variant shows ✕; disabled muted. Example: `関西 ✕`, `Kansai ✕`.

#### Date / period picker

Range picker (default 60-day window, from `read.py` `DEFAULT_DATE_WINDOW`). Two-field range for Grid; four-field (Baseline A start/end, Comparison B start/end) for Period Comparison (`i18n` keys `baseline_start`…`comparison_end`). States: focus ring, invalid range (`negative` border + helper), empty prompt.

#### Area selector

Multiselect over `AREA_ORDER` (default all 9). Rendered as filter-chip set + "All / すべて" toggle. Each chip carries its `color.area.*` dot. Loading = disabled skeleton chips.

#### Data table (period comparison)

Bound to `read.py` period-stats frames. Header row `surface-inverse` navy, white 600 (matches shipped `.dataframe th`). Body zebra `surface`/`surface-alt`. Delta columns colored by sign (`positive`/`negative`) with ▲/▼. Right-aligned `tnum` numerics. States: sortable header hover, loading (row skeletons), empty ("No overlapping data / 重複データなし"), sticky header on scroll. Columns per grounding (Area, A/B/Δ demand, price, etc.).

#### List row

Policy meetings / reminders / scrollable lists (Donezo list card). Left: title + meta (`type.body` / `type.caption`); right: status chip + chevron. States: hover `surface-alt`, selected `accent-tint-12` left bar, focus ring, disabled muted.

#### Status & delta chips

- **Delta chip**: pill, `tnum`, ▲ `positive` / ▼ `negative` / — neutral; bg = sign color @ 12%.
- **Status chip** (policy meeting `state`): `detected` (info), `generating` (accent, pulsing dot), `done` (positive), `error` (negative), `ocr_suspect`/`short_output` quality flags (warning). Bound to `PolicyMeeting.state` / `quality_flag` (`db.py`).

#### Badges

Small count/label badges: notification count (accent dot), "JP/EN" language badge, quota badge ("Rate-limited / レート制限" warning) from policy pipeline `rate_limited` flag.

#### Tooltip

Chart tooltip: `surface-inverse` bg `rgba(27,42,74,0.92)`, white text, `radius.sm`, max-width 280px, right-align near edge — **verbatim from shipped D3 `.tooltip`**. Vertical dashed guide line `#aaa` on hover. UI tooltips (icon buttons) same styling, smaller.

#### Modal & side drawer

- **Modal**: centered, `surface`, `radius.xl`, `shadow.lg`, scrim `rgba(27,42,74,0.4)`. Used for export config, "Manage tracked committees." Focus-trapped, Esc closes.
- **Side drawer**: right-slide 420px, `shadow.lg`; used for filters on mobile and meeting detail (briefing_md + English digest). Off-canvas nav drawer on `bp.xs`.

#### Toast

Bottom-right, `surface`, `shadow.md`, left accent bar by type (info/positive/warning/negative). Auto-dismiss 4s. Example: **Data refreshed / データを更新しました**, **Rate limit reached — try again tomorrow / レート制限に達しました。明日再試行してください**.

#### Empty / Loading / Error (global patterns)

- **Loading**: skeleton shimmer (`surface-alt` → `border` sweep) for cards/tables; centered spinner for charts.
- **Empty**: muted line icon + one-line JP/EN message + optional CTA (e.g. Policy empty state cites `policy_no_data`: "No policy data yet / 政策データはまだありません").
- **Error**: `negative` left bar, plain-language message, retry ghost button. Never surface tracebacks (mirrors CLI's clean-message rule).

---

### 4e. Data-Viz Style Guide

#### Chart-type mapping (all bindings exist today unless marked PROPOSED)

| Data | Chart type | Source (grounding) |
|---|---|---|
| JEPX area price (max/avg/min) | **Line + shaded band** between max/min (`accent-tint-12`) | `JepxAreaPrice30m` → `price_chart.py` |
| Generation mix by fuel | **Stacked area** — **14 stacked fuel layers + total overlay**, `curveStepAfter`, demand line overlay | `DemandSupply30m` (15 `MIX_COLUMNS`) → `generation_chart.py` |
| Balancing volume | **Composite step lines + shaded "unprocured" area**, dual Y (MW / count) | EPRX balancing Parquet → `volume_chart.py` |
| Balancing price | **Line + band** (¥/kW·30min) | EPRX balancing → shared price chart |
| Interconnector capacity | **Dashed limit lines + solid reserved lines w/ area** | EPRX tieline Parquet → `tieline_chart.py` |
| Fuel/FX drivers | **Multi-line**; **JEPX↔Brent scatter** w/ Pearson r | `FuelDaily` → Drivers tab |
| **Per-area × 48-slot price** | **Heatmap** (area rows × time-slot cols, color = ¥/kWh) | PROPOSED — data exists (`JepxAreaPrice30m`, 48 slots) but no heatmap component today; needs a new D3/viz component. Marked clearly as new. |
| Procurement fill-rate | **Semicircular gauge** (contracted ÷ demand %) | PROPOSED — derivable from existing `contracted_mw`/`demand_mw`; new gauge component. |
| Candlestick / OHLC | **Not applicable** — JEPX/EPRX are cleared single prices per slot, not OHLC. Offer max/avg/min band instead. Do **not** invent OHLC. |
| KPI trend | **Sparkline** (bare line, no axes) in KPI card | Uses existing price/demand series. |
| Category compare (KPI analytics card) | **Bar** with one highlighted bar + ghost bars | Donezo-style; binds to any existing per-area aggregate. |

> **Generation-mix stack-key count (canonical statement, used by 6.3.3 too):** the stacked-area chart renders **14 stacked fuel layers** — nuclear, lng, coal, oil, thermal_other, hydro, geothermal, biomass, solar_actual, wind_actual, pumped, battery, interconnect, other — **plus `total_supply` as a non-stacked overlay line** and **`area_demand_mw` as a navy overlay line**. `MIX_COLUMNS` counts 15 (the 14 stackable layers + `total_supply`); `total_supply` is charted as an overlay, never a layer. `DemandSupply30m` also carries `solar_curtail` and `wind_curtail`, which **exist in the schema but are not charted** (curtailment is tracked separately, not stacked). Legend shows the 14 layers + the two overlay lines.

#### Axis / gridline / tooltip styling (from shipped D3 conventions)

- Gridlines: dashed `#eee`, subtle. Axis text `type.micro` (9px normal, 12px fullscreen). Axis/title `text-primary`; subtitle `text-muted`.
- Margins: `{top:10,right:20,bottom:28,left:42}` normal; `{top:20,right:30,bottom:40,left:60}` fullscreen (preserve shipped values).
- Curve: `curveStepAfter` for all market series (block data is stepwise — do not smooth).
- Legend: flex-wrap below chart, click to toggle series (muted opacity 0.25).
- Tooltip: dark navy per 4d. Price values 2-decimal, MW 1-decimal (shipped formatting).

#### Up/down color conventions

- Generic delta: `positive #2A9D8F` up, `negative #E63946` down.
- **Price context is directional-neutral by default** (a price rise isn't "good"); color price deltas by sign, not by desirability, and never imply value judgment in market prices. For **unprocured / missing volume**, higher = worse → always `negative`. Document this so red on a price spike is read as "spike," not "bad."

#### Ghost / inactive treatment

Inactive/muted chart series → opacity 0.25 (shipped). Inactive bars in the analytics bar card → **striped ghost fill**: 45° diagonal stripes in `border` over `surface-alt`, no solid fill (the Donezo "ghost bar"). Toggled-off legend items render their swatch at 30% + strikethrough label.

---

### 4f. Iconography

Small monochrome line icons, 1.5px stroke, 20/24px grid, rounded joins. `icon.default` = `text-secondary`; `icon.active` = `accent`; `icon.muted` = `text-muted`. Set: search, mail, bell, user, chevrons, arrow-up-right (KPI ↗), fullscreen `⊞`, download, filter, calendar, refresh, globe (language), warning-triangle, info-circle, check, x. Energy-specific line glyphs: bolt (wholesale), scale/balance (balancing), gauge (drivers), document (policy), grid/map-pin (area). Keep glyphs neutral — no branded marks. Recommended source: a single consistent line set (e.g. Lucide) themed to tokens.

---

### 4g. Dark Mode

Token-swap, same structure. The navy already used for sidebar/header becomes the base surface family.

| Semantic | Dark HEX |
|---|---|
| `bg` | `#0E1626` |
| `surface` | `#16213A` |
| `surface-alt` | `#1B2A4A` (the brand navy becomes chart interior) |
| `surface-inverse` | `#F6F8FB` (rare inverted cards) |
| `text-primary` | `#EAF0F8` |
| `text-secondary` | `#AAB6C8` |
| `text-muted` | `#6E7A8C` |
| `border` | `#2A3A57` |
| `accent` | `#33B8DC` (accent lightened +1 step for AA on dark) |
| `positive/negative/warning/info` | lightened ~10% for contrast |

Data palettes (area/fuel/product/tieline): keep hues, raise minimum luminance so the two darkest (`hydro`/`hokkaido` navy, `coal` `#3A3A3A`) don't collapse into `surface-alt`; navy fuel gets a subtle outline on dark. Shadows switch to darker, tighter values; borders do more separation work than shadows in dark mode. Tooltip already dark — light-on-dark stays, add a 1px border.

---

### 4h. Accessibility

- **Contrast targets:** body/labels meet WCAG **AA** (≥4.5:1); large text/metrics ≥3:1; UI/graphic boundaries ≥3:1. `text-muted #8A93A3` on `surface` passes for ≥14px 600 or larger only — never for <14px body. Accent `#00A5CF` is used as a **fill with white text** (passes as large/UI) and as a border/icon; accent text on white is reserved for ≥16px 600.
- **Focus rings:** always visible `focus-ring` (`0 0 0 3px rgba(0,165,207,0.35)` + 2px offset); never remove outline. Distinct from hover.
- **Keyboard nav:** full tab order; segmented controls & tabs are arrow-key navigable (roving tabindex); modals/drawers focus-trap + Esc; chart legends toggle via Enter/Space; table headers sortable via keyboard.
- **Colorblind-safe data palette:** the 9-area palette is ordered so adjacent legend/stack neighbors differ in **both hue and luminance** (navy → teal → purple → green → steel → coral → burnt-orange → amber → sage), validated against deuteranopia/protanopia. Because area cards are individually titled, color is never the *sole* channel. In charts, series are additionally distinguished by **line style / label** (limits dashed vs reserved solid, per shipped tieline), and the unprocured area uses texture (shaded) plus label — never color alone. Delta direction always pairs color with ▲/▼ glyph.
- **Heatmap accessibility (6.3.4):** the sequential accent→red ramp is **not** relied on as the sole channel. Each cell exposes its ¥/kWh value on hover/focus, cells carry an accessible label (`area · slot · ¥/kWh`), and a **"view as table" fallback** (the aggregated area×slot frame) is offered so the ramp is never the only way to read a value. The legend ramp shows numeric ¥/kWh ticks; extreme cells (top/bottom quintile) additionally carry a subtle texture/border so high/low reads without hue discrimination.
- Minimum hit target 44×44 on touch (`bp.xs`/`sm`); icon-buttons get padded targets.
- Charts expose an accessible summary and a "view as table" affordance reusing existing period-stat frames (PROPOSED for charts other than the heatmap).

---

### 4i. Bilingual / i18n & Formatting Rules

Language toggle bound to `LANG_OPTIONS = {ja, en}`, default **ja** (`i18n.py`). Every user-facing string flows through `T(key, lang)`; area/product/pair/metric labels via `region_label` / `product_label` / `pair_label` / `metric_labels`. Never hardcode display text.

| Rule | JP | EN |
|---|---|---|
| **Timezone** | All timestamps **JST (Asia/Tokyo)**, implicit in source data (`db.py` note); label axes/tooltips "JST" once per view. Never convert to UTC in UI. | same |
| **30-min slots** | 48 half-hour slots/day (or 8×3h in EPRX 8-block mode); slot labels `HH:MM`; the 24:00 row rolls to next-day 00:00 (shipped `_rollover_datetime`). Never interpolate 8→48. | same |
| **Price units** | Wholesale **¥/kWh**; balancing **¥/kW·30min**; tieline capacity **MW**. Show unit in axis title + tooltip. Do **not** silently convert to ¥/MWh — if a ¥/MWh toggle is added it is PROPOSED and must relabel explicitly. | Wholesale **¥/kWh**; balancing **¥/kW·30min** |
| **Thousands separator** | comma every 3 digits, `tnum`; MW 1-decimal, price 2-decimal (shipped). | same |
| **Date format** | `YYYY年M月D日`（例：2026年7月2日）; short axis `M月D日` | `D MMM YYYY` (2 Jul 2026); short axis `MMM D` |
| **Number/percent** | 全角 not used for figures; use half-width digits + `%`. | same |
| **Currency glyph** | `¥` prefix, no space before number. | `¥` prefix |

**Canonical bilingual metric labels (`metric_labels(lang)`).** The Market Data KPI cards and chart series **must** pull labels from `metric_labels(lang)` — do not re-invent strings (e.g. never "requirement"). The canonical labels are:

| Field | 日本語 | English |
|---|---|---|
| `price_avg` | 平均約定価格 | Avg clearing price |
| `price_max` | 最高価格 | Peak price |
| `price_min` | 最安価格 | Min price |
| `demand_mw` | 募集量 (MW) | Market Procurement (MW) |
| `contracted_mw` | 約定量 (MW) | Contracted (MW) |
| `bid_volume_mw` | 応札量 (MW) | Bid volume (MW) |
| `missing_mw` | 未達量 (MW) | Unprocured (MW) |
| `area_demand_mw` | エリア需要 (MW) | Area demand (MW) |

Note `demand_mw` = **募集量 (MW) / Market Procurement (MW)** everywhere (this is the single canonical label; "requirement" is not used anywhere in this spec).

Layout note: JP strings can run longer or shorter than EN — components use flexible min-widths and never truncate the metric number; labels ellipsize (with tooltip) rather than the value. `uppercase` styling applies to `:lang(en)` only; JP text is never transformed.

---

**Grounding boundaries.** Everything above binds to data that exists in the codebase except three items explicitly marked **PROPOSED** — the per-area × 48-slot **heatmap**, the procurement **gauge**, and an optional **¥/MWh toggle** / chart "view as table." Each is derivable from existing tables (`JepxAreaPrice30m`, EPRX balancing Parquet) but needs a new front-end component; none require new data collection. Candlestick/OHLC is deliberately excluded because the markets clear single prices per slot. The recommended brand palette is **"Harbor" (Palette A)**, which reuses the exact HEX values in `src/repower/dashboard/theme.py` under neutral token names, with the single interactive accent fixed at teal `#00A5CF`.

---

## 5. Screen — Market Overview

The default landing route (`/` → **Market Overview / マーケット概況**). It fuses two answers a subscriber wants in the first three seconds: **how is JEPX clearing at the system level right now**, and **which METI committee meetings matter most this week**. Structurally and tonally it mirrors the Donezo reference — generous radii, one confident accent, airy whitespace — but every number is bound to a real RePower table unless explicitly marked PROPOSED.

---

### 5.1 Layout — regions & responsive grid

The page uses the shared 12-column app grid (see design system `--grid-12`, `--gutter-24`, page max-width `1800px`, `--page-pad-x`). The persistent left sidebar and top bar (Section 3) are assumed present; this section describes the **main region** only.

| Region | Placement (desktop ≥1280px) | Tablet (768–1279px) | Mobile (<768px) |
|---|---|---|---|
| **A. Page header** | Row 1, cols 1–12. Title + subtitle left; action buttons right. | Same, buttons wrap under title. | Stacked; buttons full-width. |
| **B. JEPX System KPI strip** | Row 2, cols 1–12. 4 equal cards, `gap: var(--space-24)`. | 2×2 grid. | 1 column, stacked. |
| **C. System-price intraday chart** | Row 3, cols 1–8. Large card, min-height 360px. | Cols 1–12 (full width). | Full width, height 280px. |
| **D. Market Pulse (spot snapshot + per-area strip)** | Row 3, cols 9–12. Tall card aligned to C's height. | Cols 1–12, below C. | Full width, below C. |
| **E. METI Committee Radar** | Row 4, cols 1–8. Scrollable ranked list card. | Cols 1–12. | Full width. |
| **F. Data freshness / provenance rail** | Row 4, cols 9–12. Dark-gradient feature card. | Cols 1–12, below E. | Full width. |

Vertical rhythm between rows: `var(--space-24)`. Cards use `--radius-card: 20px`, `--shadow-card` (soft diffuse), `--card-bg: var(--surface)`.

---

### 5.2 Region A — Page header

**Purpose:** orient and offer the two top-of-funnel actions.

- **Title (H1, `--type-display`):** JP「マーケット概況」/ EN "Market Overview".
- **Subtitle (`--type-body-muted`):** JP「JEPXシステム価格と政策委員会の最新動向」/ EN "JEPX system price & the latest policy-committee signals".
- **Primary button (accent-filled, pill, `--btn-primary`):** JP「マーケットデータを開く」/ EN "Open Market Data" → navigates to Market Data (wholesale 9-area grid).
- **Secondary button (outline, `--btn-secondary`):** JP「政策レーダー全体」/ EN "All Committees" → Policy Deep Dive.

**States:** default / hover (primary darkens to `--accent-600`, secondary fills `--accent-050`) / focus-visible ring `--focus-ring`. No loading/error state — always rendered.

---

### 5.3 Region B — JEPX System KPI strip

Mirrors the reference's 4-card row: **exactly one card accent-filled** (the "live" latest price, teal), the other three white.

**Card anatomy** (each, `--radius-card`, `--shadow-card`): big metric (`--type-metric`, ~32px), label above (`--type-label-muted`, 600-weight), a small round up-right arrow icon-button top-right (line icon, `--icon-btn`), and a delta chip bottom-left.

| # | Card | Metric & units | Delta chip | Fill |
|---|---|---|---|---|
| 1 | **Latest system price / 最新システム価格** | Most recent 30-min `system_price`, `¥/kWh`, 2 dp | vs. same slot yesterday (Δ¥ + %) | **Accent-filled** (`--accent-500` teal bg, white text) |
| 2 | **Today's average / 本日平均** | Mean across today's 48 cleared `system_price` slots, `¥/kWh` | vs. yesterday's full-day avg | White |
| 3 | **Today's high / 本日高値** | Max `system_price` today + the slot label (e.g. "18:00") | vs. yesterday high | White |
| 4 | **Today's low / 本日安値** | Min `system_price` today + slot label | vs. yesterday low | White |

**Data binding — all four (EXISTS TODAY):**

- Source: `JepxSpot30m.system_price` (SQLite table `jepx_spot_30m`; unique on `date, time`; 48 half-hour slots). Confirmed in `src/repower/db.py`.
- Units: `¥/kWh`, formatted `.2f` per the dashboard's existing convention.
- Cadence: JEPX day-ahead spot clears once daily — **gate close 10:00 JST prior day, results ~10:30 JST**. Because clearing is day-ahead, **all 48 of today's slots are known each morning** after results post; the daily GitHub Actions cron ingests them. "Latest" = the current-or-most-recent 30-min slot by JST wall clock, not a live tick. Card 2's "today's average" is therefore the mean across all 48 cleared slots (not an intraday-accumulating figure).
- Delta chips: computed against `system_price` for the matching slot / prior calendar day from the same table. Green chip `--chip-up`, red `--chip-down`, neutral grey `--chip-flat` when |Δ|<0.5%.

> Microcopy caveat (footnote link on card 1): JP「JEPXスポットは前日約定。『最新』は本日の最新30分コマ」/ EN "JEPX spot is day-ahead; 'latest' = the most recent 30-min slot of today. All 48 of today's slots clear the prior day." Keeps the authoritative tone honest — no false "real-time tick" implication.

**States:**

- *Default:* values rendered.
- *Loading:* skeleton shimmer bars in metric + chip positions (`--skeleton`); label text stays.
- *Empty* (no rows for today, e.g. pre-10:30 ingest): metric shows "—", chip hidden, tiny caption JP「本日データ待機中」/ EN "Awaiting today's clearing".
- *Error* (DB read fails): metric shows "—", card border `--border-error`, tooltip JP「データ取得エラー」/ EN "Data unavailable".

**Interactions:** each card's arrow icon-button and the card body both drill to the **System Price detail** view (a filtered Market Data view scoped to system price). Hovering a delta chip shows a tooltip with the exact prior-day value and slot.

---

### 5.4 Region C — System-price intraday chart (48 half-hour slots)

**Purpose:** the hero visualization — how system price moved across today's 48 slots, echoing Donezo's highlighted-bar analytics card but as a line/area.

- **Chart type:** area chart with a bold line on top (`--accent-500` teal stroke, gradient fill `--accent-500` → transparent at 0.14 opacity). Reuses the existing D3 idiom (`curveStepAfter`, dashed `#eee` grid, dark-navy tooltip `rgba(27,42,74,0.92)` white text, vertical hover guide) documented for the current dashboard charts — a straight port of `price_chart.py` conventions, not a new component.
- **X-axis:** 48 half-hour slot labels (00:00 → 23:30), thinned to every 2 hours for legibility.
- **Y-axis:** `¥/kWh`.
- **Highlighted slot:** the current/most-recent slot rendered as an emphasized point + subtle vertical band (`--accent-050`), mirroring the reference's "one highlighted bar + tooltip".
- **Optional ghost series (default ON, toggle):** yesterday's 48-slot curve as a striped/ghost line (`--series-ghost`, dashed, 0.4 opacity) — the reference's "subtle striped/ghost state" applied to comparison data.

**Card header:** title JP「システム価格 日中推移」/ EN "System Price — Intraday". Subtitle JP「48コマ・¥/kWh・前日約定」/ EN "48 half-hour slots · ¥/kWh · day-ahead". Top-right: a small segmented control **Today / Yesterday / 7-day avg** (`--segmented`) and a fullscreen glyph (⊞) matching the current dashboard.

**Data binding (EXISTS TODAY):**

- Source: `JepxSpot30m.system_price` for the selected date (48 rows). Ghost/comparison series: same column, prior day. "7-day avg" option: mean per slot over the trailing 7 days — computed at read time, no new storage.
- Cadence: same daily day-ahead pipeline as §5.3.

**Interactions:** hover → vertical guide + tooltip (slot, today ¥, yesterday ¥, Δ). Legend items toggle series (opacity 0.25 when muted — existing pattern). Clicking any slot deep-links to Market Data with that date/slot preselected. Fullscreen expands via the existing `requestFullscreen` path.

**States:** default / loading (skeleton chart block + spinner) / empty (centered JP「本日の約定価格待機中」/ EN "Awaiting today's clearing prices" with a muted illustration) / error (JP「チャートを表示できません」/ EN "Chart unavailable", retry link).

---

### 5.5 Region D — Market Pulse (spot snapshot + mini per-area strip)

A compact, scannable companion to C — the reference's scrollable list card, repurposed.

**D1 — Spot snapshot (top block):**

- JP「スポット概況」/ EN "Spot Snapshot".
- Three tight stat rows: **System price now** (`system_price`, latest slot), **Tokyo area now** (`JepxSpot30m.tokyo_area_price`, latest slot), **System–Tokyo spread** (derived Δ, `¥/kWh`). All EXIST TODAY (`jepx_spot_30m`).

**D2 — Mini per-area strip (below):**

- Nine compact rows, one per TSO area (`hokkaido, tohoku, tepco, chubu, hokuriku, kansai, chugoku, shikoku, kyushu`), each showing: area name (bilingual via `region_label()`), latest area price (`¥/kWh`), and a tiny 48-slot sparkline.
- **Data binding (EXISTS TODAY):** `JepxAreaPrice30m.price` (SQLite `jepx_area_price_30m`, unique on `area, date, time`; one row per area-slot).
- Rows sorted by latest price descending; the highest area gets a faint `--chip-up`/`--chip-down` tint vs. system price so congestion pops.

**Interactions:** clicking any area row → Market Data, wholesale view, scrolled to that area's price panel with the current date range. Clicking the D1 header → System Price detail.

**States:** default / loading (9 skeleton rows) / empty (JP「エリア価格待機中」/ EN "Awaiting area prices") / error (inline retry).

---

### 5.6 Region E — METI Committee Radar

The distinguishing panel: a **ranked feed of the most important recent committee meetings across the committees JEMA tracks** — the policy half of the "one-stop view."

**Scope note (data-binding truth).** `PolicyMeeting` rows exist only for the **tracked committees** (detection runs per committee; the 14 tracked committees, whether currently *enabled* or *disabled*, all have rows — a disabled committee still has its previously-detected meetings). There is **no data source of meetings for never-tracked committees**, so the Radar ranks meetings **that exist in `PolicyMeeting`**. The "enabled vs tracked" distinction matters: *enabled* gates future detection/summarisation, but *disabled-yet-tracked* committees still contribute their existing meeting rows to the candidate set. Surfacing meetings for **never-tracked** committees ("the whole METI/OCCTO/EGC landscape beyond JEMA's set") is **PROPOSED** and would require a broad discovery/detection pass that persists `PolicyMeeting` rows for non-enabled committees; until that ships, the Radar does not claim to cover untracked committees.

#### Header

- Title JP「METI委員会レーダー」/ EN "METI Committee Radar".
- Subtitle JP「重要度順・直近の会合」/ EN "Recent meetings, ranked by importance".
- Right side: a **"?" info icon** → *"Why this ranking?"* popover (§5.6.4), and a filter chip group **Followed / Followed+Watchlist / All tracked** (`--chip-filter`), default **All tracked** so the panel surfaces every meeting in `PolicyMeeting` (enabled + disabled tracked committees).

#### 5.6.1 Ranked meeting row (list item, repeating)

Each row (`--list-row`, `--radius-12`, hover raises `--shadow-hover`):

| Element | Content | Binding |
|---|---|---|
| **Rank badge** | 1–N, accent (teal) for #1 | Derived score (§5.6.2) |
| **Committee name** | JP + EN, two lines | `PolicyCommittee.name_ja` / `name_en` (EXISTS) |
| **Meeting label + date** | e.g.「第58回・2026-06-24」/ "No. 58 · 2026-06-24" | `PolicyMeeting.meeting_num`, `meeting_date` (EXISTS) |
| **One-line AI summary** | Single sentence, truncated to ~110 chars | Derived from `PolicyMeeting.digest_en_json` (EN) / first line of `briefing_md` (JP) — both EXIST; see note |
| **Importance indicators** | Recency + tier badge; a "とりまとめ" milestone pill when `has_torimatome=true`; a tier dot (METI/OCCTO/EGC); a views chip only when view data is connected (PROPOSED, §5.6.3) | `has_torimatome`, `source` EXIST; views PROPOSED |
| **Followed flag** | Small filled dot if committee is enabled/followed | `PolicyCommittee.enabled` / tracked registry (EXISTS) |
| **CTA** | Accent text-button JP「詳細を見る」/ EN "Deep dive →" | Navigates to Policy Deep Dive, deep-linked to `committee_key` + `meeting_num` |

> **One-line summary binding note:** the codebase stores a full Japanese `briefing_md` and an English `digest_en_json` (answer + references) per meeting once summarized. The radar's one-liner is the **first sentence** of those, computed at read time — no new column. For meetings not yet summarized (`state != 'done'`), show a muted JP「要約待ち」/ EN "Summary pending" placeholder; the row still ranks (recency + tier + views can score without a summary).

#### 5.6.2 Ranking / importance score (references the single canonical model)

The Radar uses the **single canonical Importance Score defined once in Appendix (b)** — `I ∈ [0,100]` — computed over meetings that exist in `PolicyMeeting` within a trailing-90-day window (across all tracked committees, enabled or disabled). There is **no second formula**: this section deliberately does **not** restate a competing set of weights. See §8(b) for the exact signals (`P̂` tier, `R̂` recency with a **30-day half-life**, `Â` activity, `D̂` decision density, `F̂` summary freshness, `V̂` public attention/views), the default weight profile `I = 100·(0.35·P̂ + 0.25·R̂ + 0.15·Â + 0.10·D̂ + 0.05·F̂ + 0.10·V̂)`, and the graceful-degradation rule when views are missing.

- When the **Followed** filter is active, only enabled committees are shown (the score is unchanged; the candidate set is filtered).
- **Views are PROPOSED** (§5.6.3). Today `w_V = 0` and its weight is re-normalized across the remaining signals per §8(b); the ranking runs entirely on data that EXISTS TODAY.

#### 5.6.3 View-count data source — PROPOSED (YouTube Data API)

> **Clearly marked PROPOSED — does not exist in the codebase today.** There is no view-count field in any table (`PolicyMeeting` schema in `db.py` has no such column; grep confirms no YouTube/view-count code under `src/repower`).

- **What it is:** METI uploads each council meeting's live recording to its official channel (`@metichannelshingikai`) on the meeting day. The view count of that video is the audience-attention proxy (`V̂` in the §8(b) model).
- **Integration required:**
  1. New nullable columns, e.g. `PolicyMeeting.yt_video_id (String)`, `yt_view_count (Integer)`, `yt_views_checked_at (DateTime)`.
  2. A resolver mapping a meeting → its YouTube video (committee channel + title/date match), then a **YouTube Data API v3** `videos.list?part=statistics` call to fetch `viewCount`.
  3. A refresh cadence: daily for meetings <30 days old, weekly thereafter; values ride the existing HF sync like other columns.
- **Why proxy, not truth:** view count approximates market/analyst attention. The popover (§5.6.4) states this plainly.

#### 5.6.4 Fallback when views are unavailable (the default state today)

Ranking degrades per the §8(b) rule: `w_V = 0`, remaining weights re-normalized to sum to 1 (no imputed views). The importance indicator shows a neutral **tier + recency badge** (e.g. "METI · 6日前" / "METI · 6d ago") with no view figure. A tiny caption under the panel header notes the degraded mode: JP「視聴回数データ未接続 — 新しさ・機関重要度で表示」/ EN "View data not connected — ranked by recency & institutional weight."

#### 5.6.5 "Why this ranking?" popover

Triggered by the header "?" icon (`--popover`, arrow-anchored, max-width 320px). Content lists the top 2–3 contributing signals from the §8(b) model with their normalized values (no black-box number):

- JP「重要度スコア = 機関の重み ＋ 新しさ ＋ 活動量 ＋ 決定密度 ＋ 要約の新しさ ＋ 視聴回数（提案中）」
- EN "Importance = institutional tier + recency + activity + decision density + summary freshness + views (proposed)."
- Honesty note: JP「視聴回数はMETI公式YouTubeの推定注目度です」/ EN "Views are a proxy for attention from METI's official YouTube — not an official significance measure." In fallback mode, the popover explains the re-normalized weighting.
- Link: JP「重み付けを調整」/ EN "Adjust weighting" → opens a settings drawer (PROPOSED, ties to whatever preferences layer JEMA ships; the weight profile is a named token set `radar.weights.regulatory_lead`).

#### 5.6.6 Radar states

| State | Rendering |
|---|---|
| **Default** | Top ~6 ranked rows; card scrolls to reveal up to ~15; sticky footer link JP「全ての会合を見る」/ EN "See all meetings" → Policy Deep Dive. |
| **Loading** | 6 skeleton rows (badge circle + two text bars + chip). |
| **Empty** | If no meetings in the 90-day window: centered muted state JP「直近の会合はありません」/ EN "No recent meetings" + link to browse all committees. |
| **Error** | Card body replaced with JP「政策データを取得できません」/ EN "Couldn't load policy data" + retry. If **only** the (PROPOSED) view fetch failed, the panel renders normally in fallback mode (§5.6.4) — a partial failure never blanks the panel. |
| **Summary-pending row** | Row still shown/ranked with "要約待ち / Summary pending" muted line; CTA reads JP「会合を開く」/ EN "Open meeting". |

---

### 5.7 Region F — Data freshness / provenance rail

The dark-gradient feature card from the reference — here it earns the "trustworthy, quietly premium" tone by being explicit about provenance.

- **Header:** JP「データ鮮度」/ EN "Data Freshness" on `--gradient-navy` (`#1B2A4A` → `#264653`), white text.
- **Rows (all EXIST TODAY):**
  - **JEPX spot** — last ingested date/slot + JP「前日約定・毎日更新」/ EN "Day-ahead · daily". Source: latest `date` in `jepx_spot_30m`.
  - **Area prices** — latest `date` in `jepx_area_price_30m`.
  - **Balancing (EPRX)** — latest `date` in `eprx_balancing.parquet` + JP「FY2025以降・毎日更新」/ EN "FY2025+ · daily".
  - **Interconnectors (tieline)** — latest `date` in `eprx_tieline.parquet`.
  - **Fuels / FX** — latest `date` in `FuelDaily` (Brent / NG / USD·JPY; yfinance daily close).
  - **Policy detection** — most recent `PolicyCommittee.last_checked`.
  - **Policy summaries** — most recent `PolicyCommittee.last_refreshed_at`.
- **Sync note:** JP「Hugging Face同期・GitHub Actions日次」/ EN "Synced via Hugging Face · daily GitHub Actions cron" (from README pipeline).
- **CTA (outline-on-dark):** JP「更新」/ EN "Refresh" → triggers a client refetch (cache-buster bump, mirroring the existing dashboard's refresh mechanic).

**States:** default / loading (skeleton timestamps) / stale-warning (if newest JEPX `date` < today−1, or balancing/tieline/fuels older than their expected cadence, an amber `--chip-warn` "遅延 / delayed" pill on that row) / error (JP「同期状況不明」/ EN "Sync status unknown").

---

### 5.8 Cross-screen interactions & navigation targets

| Trigger | Target |
|---|---|
| KPI card / arrow button (§5.3), chart slot click (§5.4), D1 header (§5.5) | Market Data → System Price detail (date/slot preselected) |
| Per-area row (§5.5) | Market Data → wholesale, scrolled to that area |
| Radar row CTA / body (§5.6) | Policy Deep Dive (deep-linked `committee_key` + `meeting_num`) |
| Header primary/secondary buttons (§5.2) | Market Data / Policy Deep Dive |
| Radar footer, "?" popover "Adjust weighting" | Policy Deep Dive / preferences drawer (PROPOSED) |

---

### 5.9 Design-token summary (Donezo-anchored)

| Token | Value / role |
|---|---|
| `--accent-500` | The single confident accent = **teal `#00A5CF`** (used only on KPI card 1, primary buttons, chart hero line, rank #1, active nav/segments). Never navy. |
| `--radius-card` / `--radius-pill` | 20px cards / full-pill buttons & chips |
| `--shadow-card` / `--shadow-hover` | Soft diffuse; lifts on hover |
| `--gradient-navy` | `#1B2A4A → #264653` (Region F) |
| `--chip-up` / `--chip-down` / `--chip-flat` / `--chip-warn` | Delta & freshness chips |
| `--series-ghost` | Striped/ghost comparison series |
| Type | Inter (300–700), humanist sans; muted neutral hierarchy `#333` body, muted labels |
| Icons | Small monochrome line icons (mail, bell, arrow-up-right, ⊞ fullscreen, "?") |

**Naming guardrail:** every constant binds to existing `theme.py` values by neutral name (hex only) — no legacy brand names surfaced. User-facing brand is **JEMA / Japan Energy Market Analytics** only.

---

### 5.10 AI Daily Brief card — PROPOSED empty-state (Analyses surface)

Because Analyses is omitted from primary nav (2.1) but the client may want a daily narrative on the landing, the Market Overview reserves an optional **"AI Daily Brief / AI日次ブリーフ"** card (cols 1–8, above or beside the Radar). It is **PROPOSED** and, in the prototype, renders **only** an empty/awaiting state — never fabricated narrative:

- **Empty-state copy:** JP「本日のAIブリーフは未生成です — 日次ナラティブ生成は準備中」/ EN "Today's AI brief hasn't been generated yet — daily narrative generation is not wired."
- **Layout:** card header "AI Daily Brief / AI日次ブリーフ" with a small `PROPOSED` badge; body shows a muted document glyph + the copy above + a disabled "Generate / 生成" ghost button (tooltip "Coming soon / 近日公開").
- **Binding:** would populate from `AnalysisRecord.narrative_md` once an LLM generation job exists (`features_json` is written today; `narrative_md` is not). Do not bind to live data in the prototype.

---

**Grounding recap for the prototyper:**

- **Exists today:** all four KPIs, intraday & ghost curve, spot snapshot, 9-area strip, freshness timestamps (JEPX, area, balancing, tieline, fuels, policy detection, policy summaries), committee names, meeting dates, one-line summaries, `has_torimatome` milestone, followed flag, tier (via `source`/`committee_key`). Files: `src/repower/db.py` (`JepxSpot30m`, `JepxAreaPrice30m`, `PolicyCommittee`, `PolicyMeeting`).
- **Proposed (needs integration):** YouTube view count + trend for the Radar's attention signal → **YouTube Data API v3** + new `PolicyMeeting.yt_video_id / yt_view_count / yt_views_checked_at` columns + a meeting→video resolver; the AI Daily Brief narrative (`AnalysisRecord.narrative_md`); surfacing meetings for never-tracked committees. The ranking, indicators, and popover all degrade gracefully to the DB-only signals when views are absent.

---

## 6. Screen — Market Data (Wholesale & Balancing)

The workhorse screen. It productizes the RePower views (JEPX day-ahead spot per area, the 9-area supply/demand generation mix, and the EPRX 需給調整市場 balancing/tieline views) into a responsive SaaS layout adapted from the Donezo reference: left nav rail, top bar, page header with actions, and a scannable card grid.

Everything below is grounded in tables the scrapers actually populate. New visuals are marked **PROPOSED** with the integration they require.

---

### 6.1 Page layout & responsive grid

Regions on a 12-column grid (max content width `--layout-max: 1800px`, gutter `--space-6`, card radius `--radius-card: 18px`, `--shadow-card` soft diffuse).

| Region | Placement | Desktop (≥1280px) | Tablet (768–1279px) | Mobile (<768px) |
|---|---|---|---|---|
| Sidebar nav | Fixed left, full height | 240px fixed rail | Collapses to 64px icon rail | Off-canvas drawer (hamburger) |
| Top bar | Sticky top of content | Global search + icon buttons + avatar | Same, search shrinks | Search becomes icon |
| Page header | Row 1 of content | Title + subtitle left; sub-view switcher + actions right | Actions wrap below title | Actions stack |
| Control bar | Row 2, full width, sticky under header | Single row: date range · area select · aggregation · product (balancing) · compare | Wraps to 2 rows | Vertical filter sheet via "Filters" button |
| KPI row | Row 3 | 4 KPI cards, equal width (3 cols each) | 2×2 | 1 col stack |
| Chart grid | Row 4+ | Per-area cards, 2 cards per area (see 6.4) | 1 area per row, 2 cols | 1 col; charts stack |

**Sub-view switcher (page header).** A **primary segmented control** for the two data-dense grids, plus a **secondary segmented control** so all four Market-Data sub-destinations from Section 2.1 are reachable on-screen. Labels use the canonical `T()` glossary values (2.4):

Primary segmented control (single accent-filled active segment, teal):

| Segment | JA (`T()`) | EN (`T()`) |
|---|---|---|
| Wholesale | 卸電力（JEPX） | Wholesale (Spot) |
| Balancing | 需給調整市場 | Balancing |

Secondary control (sibling sub-destinations, reachable from the same header):

| Segment | JA (`T()`) | EN (`T()`) | Target |
|---|---|---|---|
| Interconnectors | 連系線 | Interconnectors | Tieline panel (6.5.5), also standalone |
| Drivers | ドライバー | Drivers | Fuels / FX / correlation (legacy Drivers view) |

Only the active view renders (perf pattern preserved). Design tokens referenced throughout: `--accent` (the single teal accent), `--accent-weak` (ghost/striped inactive), `--surface`, `--surface-raised`, `--text-strong` / `--text-muted` / `--text-subtle`, `--border-hairline`, `--chart-grid` (dashed). Chart series colors reuse the existing hex palette (see 6.7) but are exposed only as neutral token names.

---

### 6.2 Control bar (shared by both sub-views)

| Control | Type / variant | Content & options | JA / EN copy | Binding & notes |
|---|---|---|---|---|
| Date range | Pill dropdown with calendar popover; presets + custom | Presets: 7D / 30D / 60D (default) / FYTD / Custom. Default window = 60 days back from latest available date | 期間 / Period; プリセット: 7日・30日・60日・年度累計・カスタム | Bounds the query window. Latest date = max over `DemandSupply30m.date` / `JepxAreaPrice30m.date` (wholesale) or EPRX Parquet `date` (balancing). **Exists** (60-day default is current behavior). |
| Area selector | Multi-select chips + "System" chip | 9 TSO areas + **System** (Japan-wide). Default: all 9 areas on; System off | エリア / Area; システム / System | Areas → `area` slug (`hokkaido…kyushu`). **System** binds only in wholesale (see 6.3.1); balancing has no system aggregate → chip disabled with tooltip "エリア別のみ / Area-level only". Areas **exist**; System-price series **exists** (`JepxSpot30m.system_price`) but is not currently surfaced per this grid → **PROPOSED** wiring. |
| Aggregation | Segmented radio | Native / Daily (default) / Weekly / Monthly | 粒度 / Granularity; 生 / 日次 / 週次 / 月次 | Bucketing via `read.aggregate()`. Reducers: MW→mean, `price_avg`→mean, `price_max`→max, `price_min`→min, counts→mean. **Exists.** |
| Product (balancing only) | Single-select dropdown | Primary / Primary (offline) / Secondary 1 / Secondary 2 / Tertiary 1 / Tertiary 2 / Composite. Default: Primary | 商品 / Product; 一次調整力… | `PRODUCT_ORDER`; maps to EPRX Parquet `product` / `product_code`. **Exists.** Hidden in wholesale. |
| Compare mode | Toggle → reveals Period A / Period B pickers | Two 7-day windows | 期間比較 / Compare periods | Period-comparison tables (6.5.6, 6.3.5). **Exists.** |
| Reset | Text button | — | リセット / Reset | Restores defaults. |

**States:** control bar is `position: sticky` under the header. On data refresh the whole bar shows a subtle top progress hairline in `--accent`.

---

### 6.3 WHOLESALE sub-view

Data spine: `DemandSupply30m` (30-min demand + 15-column generation mix, MW) and `JepxAreaPrice30m` (30-min area clearing price, ¥/kWh). Both **collected daily, from 2024-04 (supply) / 2024 (JEPX) onward**. System price from `JepxSpot30m` (`system_price`, `tokyo_area_price`).

#### 6.3.1 KPI row (4 cards; exactly one accent-filled per Donezo pattern)

Each card: big metric, label (from `metric_labels(lang)` per 4i), small up-right arrow icon-button (drills to the matching chart), and a delta chip (vs. prior equal-length window). Card 1 is accent-filled (teal); cards 2–4 white.

| # | Metric (label JA / EN) | Value & unit | Delta chip | Binding | Exists? |
|---|---|---|---|---|---|
| 1 (accent) | 平均約定価格 / Avg clearing price | mean over window, ¥/kWh, 2 dp | Δ% vs prior window | mean(`JepxAreaPrice30m.price`) over selected areas+range | **Exists** (computed like `avg_price` stat) |
| 2 | 最高価格 / Peak price | max ¥/kWh + slot/date | Δ vs prior | max(`JepxAreaPrice30m.price`) | **Exists** |
| 3 | ピーク需要 / Peak demand | max MW + timestamp | Δ% | max(`DemandSupply30m.area_demand_mw`) | **Exists** (`peak_demand_mw` stat) |
| 4 | 再エネ比率 / Renewable share | %, see formula below | Δ pp | Derived from `DemandSupply30m` mix columns | **PROPOSED** (ratio not currently computed; needs a read helper — all inputs exist) |

**Renewable-share formula (card 4, PROPOSED).** Numerator = `solar_actual + wind_actual + hydro + geothermal + biomass`; denominator = `total_supply`. **Curtailed solar/wind (`solar_curtail`, `wind_curtail`) are excluded** (they are tracked separately and represent energy not delivered), and **pumped storage is excluded** (it is not primary renewable generation). Caption on the card: JP「再エネの定義（大規模水力を含む）は要確認・設定可能」/ EN "'Renewable' definition (incl. large hydro) is configurable and subject to client confirmation." Keep the `PROPOSED` badge — the numerator's inclusion of large hydro and all biomass is a domain-debatable choice.

**Loading:** skeleton shimmer in metric slot. **Empty:** "データがありません / No data in range". **Error:** red hairline + "読み込みエラー / Load error" with retry.

#### 6.3.2 Chart — Price lines (per area, right column of each area row)

| Property | Spec |
|---|---|
| Type | Multi-line time series with shaded max–min band |
| Series | `price_max` (red), `price_avg` (navy), `price_min` (teal); band = area between max & min at `--accent-weak` 0.12 opacity |
| X axis | datetime bucket start (date labels) |
| Y axis | ¥/kWh, 2 dp |
| Curve | step-after |
| Binding | `JepxAreaPrice30m.price` → three series **derived** (at Native the three collapse to one line; they diverge only after Daily/Weekly/Monthly aggregation). **Exists.** |
| Interactions | Hover: vertical guide + dark tooltip (per-series ¥/kWh, date); click legend to mute a series (opacity 0.25); brush/zoom on X (**PROPOSED** — current build has no brush, only fullscreen); fullscreen expand button |
| Title / subtitle | "{Area} — 価格 / Price" · "¥/kWh · Click legend to toggle" |
| Empty | ghost gridlines + "価格データなし / No price data" |

#### 6.3.3 Chart — Generation-mix stacked area (per area, left column of each area row)

| Property | Spec |
|---|---|
| Type | Stacked area (supply by fuel) + overlay lines |
| Stack keys | **14 stacked fuel layers**: nuclear, lng, coal, oil, thermal_other, hydro, geothermal, biomass, solar_actual, wind_actual, pumped, battery, interconnect, other |
| Overlays (not stacked) | `total_supply` as a line (never a stack layer); `area_demand_mw` as a navy overlay line |
| Not charted | `solar_curtail` and `wind_curtail` exist in `DemandSupply30m` but are **not** charted (curtailment is tracked separately) |
| X / Y | datetime · MW |
| Curve | step-after |
| Binding | `DemandSupply30m` (`area_demand_mw` + `MIX_COLUMNS`). Canonical count: **14 stacked + total overlay** (matches 4e). **Exists.** |
| Interactions | Hover tooltip: per-fuel MW + total generation + demand; legend click toggles a fuel layer; fullscreen; brush/zoom (**PROPOSED**) |
| Title / subtitle | "{Area} — 電源構成 / Generation mix" · "Stacked supply · Demand overlaid" |
| States | Loading shimmer over plot; empty → "供給データなし / No supply data" |

#### 6.3.4 Chart — Area × time-slot price heatmap (**PROPOSED**)

Requested new visual. Productizes the 48-slot JEPX structure the data already supports.

| Property | Spec |
|---|---|
| Type | Heatmap grid |
| Layout A (default) | Rows = 9 areas; columns = 48 half-hour slots (00:00→23:30); cell = mean ¥/kWh for that area×slot over the window |
| Layout B (toggle) | Rows = dates in window; columns = 48 slots; single-area calendar heatmap (area chosen from area selector, first selected) |
| Color scale | Sequential ramp on `--accent` teal (low) → red `--series-price-max` (high); legend ramp with ¥/kWh ticks |
| Accessibility | Per 4h: cells expose ¥/kWh value + accessible label (`area · slot · ¥/kWh`) on hover/focus; a **"view as table" fallback** (the aggregated area×slot frame) is provided; extreme cells carry a subtle texture/border so the ramp is never the sole channel |
| Binding | `JepxAreaPrice30m` (`area`, `date`, `time`→48 slots, `price`). All fields **exist**; the aggregation to area×slot means and the heatmap renderer are **PROPOSED** (needs a `load_price_heatmap()` read helper + a heatmap component; no new scraping). |
| Interactions | Hover cell → tooltip (area/date, slot HH:MM, ¥/kWh); click cell → filters price-line chart to that area+slot; toggle Layout A/B; toggle metric mean/max/min |
| Copy | Title "価格ヒートマップ / Price heatmap" · subtitle "エリア × 30分コマ / Area × 30-min slot" |
| Empty / loading | Greyed cells with dashed hairlines; spinner overlay while aggregating |

Placement: full-width card spanning both columns, pinned above the per-area grid when the heatmap accordion is expanded.

#### 6.3.5 Area comparison

Two forms, both **exist** unless noted:

- **Compare-periods table** (via Compare toggle): styled table. Columns: エリア/Area, A/B/Δ Avg Demand (MW), A/B/Δ Peak Demand (MW), A/B/Δ Avg Price (¥/kWh). Caption: "A: {date}→{date} · B: {date}→{date}（生30分値の平均 / means over raw 30-min rows)". Navy header row, white text, no index, striped body rows. Binding: per-area window stats (`avg_demand_mw`, `peak_demand_mw`, `avg_price`).
- **Overlay mode** (**PROPOSED** enhancement): a single price-line card overlaying all selected areas' `price_avg` on shared axes, area toggled via the area chips. Reuses existing series; needs one multi-area read helper.

---

### 6.4 The 9-area grid (2-column-per-area restyle)

Both sub-views render the same grid skeleton — the documented 9-area × 2-column layout, restyled as cards.

```
┌───────────────────────── AREA ROW (repeats ×9, AREA_ORDER) ─────────────────────────┐
│  ▸ Area header pill:  北海道 / Hokkaido        [expand ▾]   [★ pin]                    │
│  ┌───────────────── LEFT card ─────────────────┐ ┌──────────── RIGHT card ──────────┐│
│  │ Wholesale: Generation-mix stacked area      │ │ Wholesale: Price lines            ││
│  │ Balancing: Volume composite (proc/contr/miss)│ │ Balancing: Clearing-price lines  ││
│  └─────────────────────────────────────────────┘ └───────────────────────────────────┘│
└───────────────────────────────────────────────────────────────────────────────────────┘
```

- **Order:** `AREA_ORDER` = hokkaido, tohoku, tepco, chubu, hokuriku, kansai, chugoku, shikoku, kyushu.
- **Card sizing:** each card min-height 300px chart body (matches base `CHART_HEIGHT_BASE`), `--radius-card` corners, `--shadow-card`. Left/right split 1:1 on desktop; stacks on tablet/mobile.
- **Area header pill:** rounded chip with the bilingual area name (`region_label`), an expand/collapse chevron, and a pin toggle (pinned areas float to top — **PROPOSED**, session-only).
- **De-selected areas:** hidden entirely (not greyed) so charts render at full width — mirrors the "only active view renders" rule that keeps D3 sizing correct.
- **Interactions across cards:** hovering a timestamp in one card raises a shared vertical guide in the paired card (**PROPOSED** cross-hair sync; today each chart is independent).

---

### 6.5 BALANCING sub-view (EPRX 需給調整市場)

Data spine: `eprx_balancing.parquet` (long → pivoted wide) and `eprx_tieline.parquet`. **Collected from FY2025 (April 2025) onward.** Product chosen in control bar.

#### 6.5.1 KPI row (4 cards; one accent-filled)

Labels pulled from `metric_labels(lang)` (4i) — the canonical `demand_mw` label is **募集量 (MW) / Market Procurement (MW)** (not "requirement").

| # | Metric (JA / EN) | Value & unit | Delta | Binding | Exists? |
|---|---|---|---|---|---|
| 1 (accent) | 平均約定価格 / Avg clearing price | ¥/kW·30min, 2 dp | Δ% | mean(`price_avg`) for product across areas | **Exists** |
| 2 | 募集量 (MW) / Market Procurement (MW) | mean MW | Δ% | mean(`demand_mw`) | **Exists** |
| 3 | 約定量 (MW) / Contracted (MW) | mean MW | Δ% | mean(`contracted_mw`) | **Exists** |
| 4 | 未達量 (MW) / Unprocured (MW) | MW (= demand − contracted) | Δ | `missing_mw` derived post-aggregation | **Exists** (derived) |

#### 6.5.2 Chart — Volume composite (per area, left card)

| Property | Spec |
|---|---|
| Type | Multi-series step lines + shaded shortfall band, dual Y-axis |
| Series | `demand_mw` (**募集量 / Market Procurement**, navy), `contracted_mw` (約定量 / Contracted, teal), `bid_volume_mw` (応札量 / Bid volume, orange), `missing_mw` (未達量 / Unprocured, red shaded area between procurement & contracted, 0.25 opacity, only when both active); counts on right axis: `bids_count`, `contracted_count` |
| Y (left/right) | MW / Count |
| Binding | EPRX balancing Parquet, pivoted: `demand_mw, contracted_mw, bid_volume_mw, bids_count, contracted_count`; `missing_mw` derived. Series labels from `metric_labels(lang)`. **Exists.** |
| Interactions | Hover tooltip (per-series MW/count); legend mute; fullscreen; brush/zoom (**PROPOSED**) |
| Title | "{Area} — 量 / Volume" · "Market Procurement vs contracted · shortfall shaded" |

#### 6.5.3 Chart — Clearing-price lines (per area, right card)

Identical structure to the wholesale price chart: `price_max` / `price_avg` / `price_min` step lines with max–min band. **Y axis units: ¥/kW·30min** (not ¥/kWh). Binding: EPRX Parquet price metrics. **Exists.** Title "{Area} — 価格 / Price".

#### 6.5.4 Procurement-adequacy focus (**PROPOSED** compact view)

A "procurement adequacy" toggle on each area's left card that reduces the composite to just `demand_mw` (**募集量 / Market Procurement**) vs `contracted_mw` (約定量 / Contracted) with the `missing_mw` gap emphasized and a per-area **fill-rate %** badge (= contracted ÷ market procurement). Uses the canonical `metric_labels(lang)` strings — no "requirement". All inputs **exist**; the ratio badge + simplified render mode are **PROPOSED** (read helper only).

#### 6.5.5 Interconnector (tieline) panel

Full-width card below the 9-area grid (matches current placement). Also reachable as a standalone sub-destination via the secondary sub-view control (6.1).

| Property | Spec |
|---|---|
| Market selector | Segmented: **DCM (需給調整市場 / Balancing Market)** / **DAM (三次調整力② / Tertiary 2)** — copy from i18n keys `tieline_market_dcm` / `tieline_market_dam`; binds `market` field |
| Per-pair chart | Step lines: `upper_limit_fwd` / `upper_limit_rev` (dashed strokes), `reserved_fwd` / `reserved_rev` (solid + shaded fill 0.18) |
| X / Y | datetime (bilingual date format) · MW |
| Pairs | Up to 11 routes via `pair_label`; pre-2026-03-14 pairs merged into combined-zone equivalents (`is_combined`) |
| Binding | `eprx_tieline.parquet` (`market`, `pair`, `date`, `time`, metric, value). **Exists.** |
| Interactions | Hover tooltip (JP/EN datetime), legend mute (dashed vs solid swatches), fullscreen |
| Title | "{pair} — 連系線 / Interconnector" · subtitle "Dashed = 上限 upper limit" |

#### 6.5.6 Balancing compare-periods table

**Exists.** Styled table, columns: Area · A/B/Δ 平均募集量 / Avg Market Procurement (MW) · A/B/Δ 平均約定量 / Avg Contracted (MW) · A/B/Δ 平均未達量 / Avg Unprocured (MW) · A/B/Δ Avg Price (¥/kW·30min) · A/B/Δ Avg Max Price. Navy header, block-level caption. Column labels from `metric_labels(lang)`.

---

### 6.6 Export, filters, and global states

#### Export / download affordances (page header, secondary outline button with dropdown)

| Affordance | Output | Binding | Exists? |
|---|---|---|---|
| Export Excel | One sheet per area, merged demand+price (wholesale) or volume+price (balancing). File: `wholesale_{start}_{end}.xlsx` / `balancing_{product}_{start}_{end}.xlsx` | `build_excel_workbook` | **Exists** |
| Export PDF | A4, region rows with paired charts | `generate_wholesale_pdf` / `generate_pdf` | **Exists** |
| Copy chart PNG | Per-card overflow menu (⋯) → download current chart as PNG | **PROPOSED** (SVG→PNG capture; not in current build) |
| Copy CSV (window) | Per-card ⋯ → the plotted frame as CSV | **PROPOSED** (frame exists in memory; needs endpoint) |

Empty-export state: button disabled with caption "エクスポートするデータがありません / No data to export".

#### Filters summary

Date range · area chips · aggregation · product (balancing) · compare toggle — all in the control bar (6.2). Applied filters echo as removable chips beneath the control bar (e.g. "60日 / 60D ✕", "関西 +5 areas ✕"); a "clear all" text link resets.

#### Global states

| State | Treatment |
|---|---|
| Loading | Control bar top hairline in `--accent`; KPI cards shimmer; chart cards show dashed ghost gridlines + centered spinner. Do not blank the previous data — dim to 0.5 opacity until refresh completes. |
| Empty (no data in range) | Card body shows illustration + "この期間・エリアのデータがありません / No data for this period and area" + "期間を広げる / Widen range" button. |
| Partial (balancing pre-FY2025) | Info banner: "需給調整市場データは2025年度以降 / Balancing data available from FY2025" when range predates April 2025. |
| Error | Red hairline + toast "データの読み込みに失敗しました / Failed to load data" with Retry; last-good data stays dimmed. |
| Stale / refresh | After HF sync or Refresh, cache-buster bumps and a "更新しました / Updated {time}" toast appears. |

---

### 6.7 Series-color token mapping

Existing hex values are reused but surfaced only under neutral token names (no brand-derived names).

| Token | Applies to | Hex (from theme) |
|---|---|---|
| `--series-demand` | demand line / market procurement | `#1B2A4A` |
| `--series-price-avg` | avg price | `#1B2A4A` |
| `--series-price-max` | max price / shortfall / heatmap-high | `#E63946` |
| `--series-price-min` | min price | `#00A5CF` |
| `--series-contracted` | contracted MW | `#00A5CF` |
| `--series-bid` | bid volume | `#F4A261` |
| Fuel tokens ×14 | generation mix | per `GENERATION_COLORS` (nuclear `#7B2D8E`, lng `#00A5CF`, solar `#E9C46A`, …) |
| Tieline tokens ×4 | limits/reserved | `#264653` / `#7B2D8E` / `#E9C46A` / `#E76F51` |

---

**Grounding notes for the prototyper.** Everything in 6.3.2, 6.3.3, 6.4, 6.5.2, 6.5.3, 6.5.5, 6.5.6 and the Excel/PDF exports maps 1:1 to shipping RePower behavior. Items explicitly marked **PROPOSED** — the price heatmap (6.3.4), renewable-share KPI (6.3.1 card 4), area-overlay compare (6.3.5), fill-rate badge (6.5.4), brush/zoom, cross-hair sync, pinning, and PNG/CSV per-chart export — are new UI over data that **already exists in the tables** (`JepxAreaPrice30m`, `JepxSpot30m`, `DemandSupply30m`, EPRX Parquet); none requires new scraping, only new read helpers/components. No data is invented beyond what the scrapers collect.

Key grounding files: `src/repower/dashboard/read.py` (loaders, aggregation, period stats), `src/repower/dashboard/components/{generation_chart,price_chart,volume_chart,tieline_chart}.py`, `src/repower/dashboard/theme.py` (color hex), `src/repower/dashboard/i18n.py` (JA/EN labels, `metric_labels`), `src/repower/db.py` (`DemandSupply30m`, `JepxAreaPrice30m`, `JepxSpot30m` schema).

---

## 7. Screen — Policy Deep Dive

Turns the RePower policy-observer backend (committee tracking, meeting detection, NotebookLM briefings + synthesis, source-document ingestion, the daily catch-up/backfill routine) into a first-class analyst workspace inside JEMA. Three linked panes — **Committee Explorer**, **Meeting Feed**, and **Meeting Detail** — sit over a persistent search + filter bar and a "What changed" strip driven by the catch-up run.

All Japanese source content (committee names, meeting titles, agenda PDFs, the detailed `briefing_md`) is preserved verbatim; English is a parallel layer (`digest_en_json`, `running_digest_en_md`). The UI never machine-translates JP source docs on the fly — it surfaces the human-grade JP briefing and the model-written EN digest side by side and lets the reader pick. See **Bilingual handling** at the end.

---

### 7.1 Layout

Responsive 12-column grid, max content width `1800px`, page gutter `--pad-xl`. Three regions on a master–feed–detail pattern.

| Breakpoint | Columns | Behaviour |
|---|---|---|
| `≥1280px` (desktop) | Explorer rail `3` · Feed `4` · Detail `5` | All three panes visible; Detail is the reading surface. |
| `768–1279px` (tablet) | Explorer collapses to a `240px` drawer (toggle); Feed `5` · Detail `7` | Two-pane; tapping a feed row swaps Detail in place. |
| `<768px` (mobile) | Single column, stacked | Explorer → Feed → Detail as a drill-down stack with a back affordance. |

Region placement, top to bottom:

1. **Page header** (full width, `64px`): title + subtitle left; primary/secondary actions right.
2. **Search + filter bar** (full width, sticky under header, `56px`): global full-text search field, filter chips, view toggle.
3. **"What changed" strip** (full width, collapsible, appears only when the last catch-up produced results): horizontally scrollable cards.
4. **Three-pane body**: Committee Explorer (left rail) · Meeting Feed (center) · Meeting Detail (right).

Tokens: cards `12px` radius on `--surface-2` with `0.5px solid var(--border)`; pill buttons. **Accent = teal `#00A5CF` (`--fill-accent`)** — the single interactive accent, consistent with the design system and Screen 1. **Navy `#1B2A4A` is ink / surface-inverse** (headings, dark surfaces), not the accent. Type stack Inter/`--font-sans`. One accent-filled action per view (the "Run catch-up" primary); everything else secondary/ghost.

---

### 7.2 Page header

- **Title (H1):** EN `Policy deep dive` / JP `政策ディープダイブ`.
- **Subtitle (one line):** EN `Committee tracking and AI briefings across METI, OCCTO, and EGC` / JP `METI・OCCTO・EGC 委員会のトラッキングとAI要約`.
- **Primary action (accent-filled pill, teal):** EN `Run catch-up` / JP `キャッチアップ実行` — triggers one NotebookLM summarisation round (see 7.5). Icon `ti-refresh`.
- **Secondary action (outline pill):** EN `Manage committees` / JP `委員会を管理` — opens the committee-management panel (7.3.4). Icon `ti-settings`.

Data binding: the header actions map to existing CLI verbs — `repower policy run` (catch-up) and the `list_committees` / `add_committee` / `set_committee_enabled` / `set_committee_priority` / `delete_committee` registry writes (`store.py`). EXISTS TODAY.

---

### 7.3 Committee Explorer (left rail)

A directory of tracked + discoverable committees, grouped by governing body.

#### 7.3.1 Structure

- **Group headers** by `source`: `METI`, `OCCTO`, `EGC`. Count badge per group (e.g. `METI · 9`). Binding: `PolicyCommittee.source`; today 9 METI / 2 OCCTO / 3 EGC (14 tracked total). EXISTS TODAY.
- **Committee row** (per committee): bilingual name, tier badge, follow toggle, freshness line.

#### 7.3.2 Committee row — content and bindings

| Element | Content (EN / JP) | Binding | Exists? |
|---|---|---|---|
| Primary name | `name_en` (e.g. `System Review Working Group`) | `PolicyCommittee.name_en` | EXISTS |
| Secondary name | `name_ja` (e.g. `制度検討作業部会`) shown muted below | `PolicyCommittee.name_ja` | EXISTS |
| Tier badge | `Tier 1` / `Tier 2` / `Tier 3` / `Standard` | `PolicyCommittee.priority` (1/2/3/100) | EXISTS |
| Follow toggle | `Following` / `フォロー中` ↔ `Follow` | `PolicyCommittee.enabled` (gates detection + summarisation) | EXISTS |
| Latest meeting | `Latest: 第58回` | `PolicyCommittee.latest_meeting` (highest to reach `done`) | EXISTS |
| Last checked | `Checked 2h ago` | `PolicyCommittee.last_checked` | EXISTS |
| Source link | external `ti-external-link` to committee homepage | `PolicyCommittee.url` | EXISTS |

**Tier mapping (also feeds the Radar `tier_weight`/`P̂` in §8(b)).** The tier is exact and derived from `priority`: `priority=1 → Tier 1` (parent councils / core review WGs, e.g. `system_review`), `2 → Tier 2` (e.g. `emissions_trading`), `3 → Tier 3` (e.g. `chousei_jukyu`), everything else `priority=100 → Standard`. Lower number = summarised first when the daily quota binds. This `committee_key → priority-tier` mapping is the enumerated source of truth the Radar uses; it lives in the committee registry (`store.py` / `committees.py`), not as a separate undocumented constant. The three named-tier committees above are illustrative; the authoritative list is whatever `priority` each `committee_key` carries in the registry.

#### 7.3.3 Row states

| State | Trigger | Visual |
|---|---|---|
| default | followed, up to date | white row, tier badge, teal "following" toggle on |
| active/selected | row clicked → filters Feed to this committee | accent left bar (3px teal) + `--bg-accent` pill |
| unfollowed | `enabled = false` | name muted, toggle off; row still visible but greyed; detection paused (existing meeting rows remain) |
| user-added | `user_added = true` | small `Custom` chip; only these can be deleted |
| stale | `last_checked` > 7 days | amber `ti-clock` "Check overdue" hint |
| discoverable (not tracked) | from discovery, not yet added | dashed border row + `Add` button; shows probe note |

#### 7.3.4 Manage / discover panel (opened from header secondary action)

Two tabs inside a side sheet:

- **Tracked** — editable list: reorder tier (priority), toggle follow, delete user-added rows. Bindings: `set_committee_priority`, `set_committee_enabled`, `delete_committee` (refuses code-config committees — those can only be disabled). EXISTS TODAY.
- **Discover** — two inputs:
  - Free-text search across curated METI/OCCTO/EGC index roots. Binding: `discover.discover_committees(query)`; returns `Candidate` rows with `already_tracked` flag and an EN→JP keyword bridge (e.g. typing `capacity` matches `容量`). EXISTS TODAY.
  - **Add by URL** — paste a committee homepage; a probe validates it and previews `"24 meeting(s) found"`. Binding: `discover.probe_url(url)` → `Candidate.note`; save via `add_committee`. EXISTS TODAY.

Discover-row states: `default` (untracked candidate, `Add` CTA), `already tracked` (muted, check icon), `probing` (spinner + `Checking…`), `unreachable`/`could not parse` (error hint from `Candidate.note`), `added` (row collapses into Tracked).

---

### 7.4 Meeting Feed (center pane)

A reverse-chronological feed of meetings across the current filter scope, showing detection + processing lifecycle. Newest first.

#### 7.4.1 Feed row — content and bindings

| Element | Content (EN / JP) | Binding | Exists? |
|---|---|---|---|
| Committee tag | short committee name + tier dot | `committee_key` → `PolicyCommittee` | EXISTS |
| Meeting number | `第58回` | `PolicyMeeting.meeting_num` | EXISTS |
| Meeting date | `2026-06-18` | `PolicyMeeting.meeting_date` | EXISTS (nullable — omit if null) |
| Title | JP meeting title | `PolicyMeeting.title` | EXISTS (nullable) |
| Milestone flag | `🏁 とりまとめ` / `Compilation` chip | `PolicyMeeting.has_torimatome` | EXISTS |
| Minutes flag | `議事録` chip | `PolicyMeeting.has_minutes` | EXISTS |
| Status chip | see 7.4.2 | `PolicyMeeting.state` (+ `quality_flag`, `gen_requested`) | EXISTS |
| Snippet | first ~140 chars of EN digest | `digest_en_json.answer` | EXISTS |

#### 7.4.2 Status chip — one per row, driven by `PolicyMeeting.state`

| `state` | Chip label (EN / JP) | Color role |
|---|---|---|
| `detected` | `Pending summary` / `要約待ち` | neutral gray |
| `downloading` | `Fetching sources` / `資料取得中` | teal (in progress) |
| `ingesting` | `Ingesting` / `取り込み中` | teal |
| `generating` | `Summarising…` / `要約生成中` | teal, animated `ti-loader` |
| `done` | `Summarised` / `要約済み` | success green |
| `error` | `Failed — will retry` / `失敗（再試行）` | danger red |

Overlays on top of the base chip:

- `gen_requested = true` → small `Queued` badge (`優先キュー`). Binding: dashboard queue flag; these jump the worklist (`pending_meetings` orders `gen_requested` first). EXISTS TODAY.
- `retry_count ≥ 3` on an `error` row → chip becomes `Gave up` (`断念`) and the row exits the active worklist (matches `MAX_RETRIES` in `store.py`). EXISTS TODAY.
- `quality_flag` present on a `done` row → info dot with tooltip: `ocr_suspect → "Low-text source, briefing may be thin"`, `short_output → "Short summary"`, `download_failed`, `no_sources`. Binding: `PolicyMeeting.quality_flag`. EXISTS TODAY.

#### 7.4.3 Feed ordering and interactions

- Default order matches `pending`/`done` reality: within scope, newest `meeting_num` first; when "Followed only" + priority sort is on, mirror `pending_meetings` ordering (`gen_requested` → tier → committee → newest). Binding: `store.pending_meetings` / a proposed `done_meetings` reader. Feed of *all* meetings by state is PROPOSED (a thin read over `PolicyMeeting`); the ordering logic itself EXISTS.
- **Row click** → loads Meeting Detail (right pane / drill-down on mobile).
- **"Generate summary" button** on a `detected`/`error` row → calls `request_generation(key, meeting_num)` (`gen_requested = true`). If auth is stale it queues; if auth is live and quota remains it runs on the next catch-up. EXISTS TODAY.
- **Backfill affordance**: a committee header row in the feed shows `Latest online 第60回 · summarised to 第52回` so the reader sees the backfill gap. Binding: online-latest from detection vs `latest_meeting`. `latest_online` surfacing is PROPOSED (detection computes it in `detect.detect()` but doesn't persist a dedicated column); the summarised watermark EXISTS (`latest_meeting`).

#### 7.4.4 Feed states

- **loading** — skeleton rows.
- **empty (scope)** — `No meetings match these filters` / `該当する会合はありません`, with a `Clear filters` ghost button.
- **empty (committee never detected)** — `No meetings detected yet. Detection runs daily.` / `会合は未検出です`.
- **error (read failure)** — `Couldn't load the feed. Retry` (no raw exception text).

---

### 7.5 "What changed" strip (catch-up reflection)

A dismissible horizontal strip surfacing the output of the daily catch-up/backfill routine (`policy-catchup` skill / `repower policy run`). Renders only when there is recent activity.

- **Cards** (one per newly-`done` meeting in the window): committee name, `第N回`, `🏁` if compilation, and the EN digest snippet.
- **Binding:** `store.recent_done_meetings(since_days)` → returns `committee_key`, `meeting_num`, `has_torimatome`, `digest_en_json`. EXISTS TODAY.
- **Strip header:** EN `Newly summarised · last 7 days` / JP `新規要約（直近7日）`, with a count and a `View all` link that applies a `state:done, updated in last 7d` filter to the Feed.
- **Run summary line** (after a manual "Run catch-up"): mirrors the skill's output contract — `Processed 8 · Summarised 3 · Errored 0 · Synthesised 2 · Rate-limited: no`. Binding: parsed from `policy run` output (`processed=N done=M errored=X synthesized=Y rate_limited=[bool]`). EXISTS TODAY.
- **States:** `default` (cards), `empty` (strip hidden — no `recent_done` rows), `running` (progress line `Summarising committee 1 of 3…` while a catch-up round is live).

---

### 7.6 Meeting Detail (right pane)

The reading surface for a single meeting: AI briefing + committee synthesis context, source materials, recording, importance signals, and (proposed) audio overview.

#### 7.6.1 Header block

- Committee (bilingual) + `第N回` + date + milestone/minutes chips (same bindings as feed).
- Status line reflecting `state` and `quality_flag`.
- Deep-link to source homepage (`PolicyCommittee.url`) and this meeting's index page.

#### 7.6.2 AI briefing (primary content)

- **English digest (top, default-open):** three-heading bullets — `Key decisions`, `Points of disagreement`, `Action items`. Binding: `PolicyMeeting.digest_en_json.answer` (produced by the pipeline's `ask`). EXISTS TODAY. A `references` list (if present in the JSON) renders as citation chips.
- **Detailed Japanese briefing (expandable):** the full 4-part structured briefing — 主要な論点 / 主要な数値・データ / 結論・決定事項 / 今後の検討課題. Binding: `PolicyMeeting.briefing_md` (Markdown). EXISTS TODAY. Rendered as rich Markdown; JP is authoritative (built from minutes/handouts).
- **"Key points" quick-scan** (chips above the briefing): decisions vs. pending-items split. Binding: EXISTS via the EN digest headings today; a structured key-point extraction is otherwise PROPOSED (would parse `briefing_md`).

Briefing states:

- `done` → full briefing + digest.
- `done` + `short_output`/`ocr_suspect` → briefing shown with a banner `This summary may be thin — source was low-text` / `出典のテキストが少なく要約が薄い可能性`.
- not yet `done` → **pending state card** (7.8), no fabricated content.

#### 7.6.3 Committee synthesis context (collapsible section)

- **Synthesis overview (EN):** where the committee's debate stands. Binding: `PolicyCommittee.running_digest_en_md`. EXISTS TODAY.
- **議論の総括 (JP synthesis):** 4-part cross-meeting synthesis (現在の主要論点 / 未解決の争点 / 会合を跨ぐ議論の推移 / 直近の決定事項). Binding: `PolicyCommittee.running_summary_md`. EXISTS TODAY.
- **Download running document:** the full deterministic Markdown doc. Binding: `store.build_running_doc(key)` / `data/policy/<key>.md`. EXISTS TODAY.

#### 7.6.4 Source materials

A list card of the meeting's PDFs, kind-classified.

| Element | Binding | Exists? |
|---|---|---|
| Document title (JP link text) | `PolicyMaterial.title` | EXISTS |
| Kind chip | `PolicyMaterial.kind` — `Minutes 議事録` / `Brief 議事要旨` / `Compilation とりまとめ` / `Handout 資料` / `Agenda 議事次第` / `Appendix 別紙` | EXISTS |
| Open PDF | `PolicyMaterial.url` (`ti-file`, external) | EXISTS |
| Used-as-source indicator | `nblm_source_id` present → `Fed to AI` badge | EXISTS |

Ordering follows the ingestion priority (minutes → brief → compilation → handout → agenda → appendix) so the reader sees what the briefing was actually built from. Empty state: `No source documents detected` / `資料は未検出`.

#### 7.6.5 Live recording + importance signals

- **Live recording link:** METI uploads meeting recordings to its official YouTube channel (`@metichannelshingikai`). A `Watch recording` (`ti-player-play`) button deep-links to the committee's video. Binding: **PROPOSED** — no recording URL is stored today; needs a new `PolicyMeeting.recording_url` column plus a resolver (channel search or a per-committee mapping). Button hidden when null; mark clearly as proposed in the UI until wired.
- **YouTube view count (importance signal):** a `▶ 12.4k views` chip next to the recording, gauging public/industry attention. Binding: **PROPOSED** — requires the YouTube Data API v3 (view counts aren't available via plain web fetch); needs `PolicyMeeting.yt_view_count` + a periodic fetch job. Show as a labelled `Proposed` metric, never a fabricated number.
- **Other importance signals (a small signal row).** These map directly to the **single canonical importance model in §8(b)** — this section does **not** introduce a separate score. The row surfaces the model's contributing signals for this meeting:
  - `🏁 Compilation` — `has_torimatome` marks a milestone/decision meeting (feeds `D̂` decision density). EXISTS. Strongest existing importance signal.
  - `Minutes available` — `has_minutes` (fuller record; also feeds `D̂`). EXISTS.
  - `Tier N committee` — committee `priority` tier (feeds `P̂`). EXISTS.
  - `Materials: N docs` — `PolicyMaterial` count (a proxy contributing to `Â` activity). EXISTS.
  - `Recency` — from `meeting_date` (feeds `R̂`, 30-day half-life). EXISTS.
  - View count (feeds `V̂`) — **PROPOSED**.
  - A "why this rank" affordance opens the same popover as the Radar (§5.6.5), showing this meeting's top contributing signals from the §8(b) model. There is **no** separate "attention score" here.

#### 7.6.6 NotebookLM audio overview / podcast player (PROPOSED — empty-state only)

- **Component:** an audio player card with play/pause, scrubber, duration, and a `Download audio` action; bilingual caption `AI audio overview` / `AI音声概要`.
- **Binding & status:** **PROPOSED — no audio artifact exists here, ever.** The RePower pipeline generates only a text report (`generate report --format custom`) and an English `ask` digest; **no audio/podcast artifact is persisted anywhere in the policy package**, and no implementation for audio/podcast generation exists in the pipeline. Audio-overview generation is a **NotebookLM platform capability**, but it is **not wired into the RePower pipeline and has never produced an artifact here** — do not treat it as near-shipped or imply any timeline. Wiring it would require: (a) a pipeline step to request an audio overview on the per-meeting/committee notebook, (b) storage for the artifact (e.g. a new `PolicyMeeting.audio_url` / object-store path), and (c) HF-sync of the audio file.
- **Prototype rendering:** the card's default and **only** rendered state is the empty `Not generated yet` / `未生成` state, with a disabled/optional `Generate audio` request affordance (would queue like `gen_requested`). The whole feature is labelled PROPOSED.
- **States (for reference once wired):** `available` (player), `generating` (progress), `not generated` (empty CTA — the only prototype state), `unavailable` (feature off / no auth).

---

### 7.7 Search + filters (persistent bar)

- **Full-text search field** (large, rounded, `⌘K` hint): searches across summaries — EN digests, JP briefings, and synthesis text. Placeholder: `Search briefings, decisions, committees…` / `要約・決定事項・委員会を検索`. Binding: **PROPOSED** — a full-text index over `PolicyMeeting.briefing_md`, `digest_en_json`, `PolicyMeeting.title`, and `PolicyCommittee.running_summary_md`/`running_digest_en_md` (SQLite FTS5 is the natural fit). The underlying text columns EXIST TODAY; the search index/endpoint is the new piece. Results list highlights the matched snippet and jumps to Meeting Detail.
- **Filter chips (multi-select):**
  - **Committee** — from tracked registry. EXISTS.
  - **Date range** — over `meeting_date`. EXISTS (nullable dates excluded).
  - **Status** — `Pending`, `In progress`, `Summarised`, `Failed` → maps to `PolicyMeeting.state`. EXISTS.
  - **Followed only** — `enabled` committees only. EXISTS.
  - **Milestones only** — `has_torimatome`. EXISTS.
  - **Topic** — e.g. `Balancing market`, `Emissions trading`, `Capacity market`, `Offshore wind`, `FIT/FIP`. Binding: **PROPOSED** — no topic taxonomy column today; derive from committee mapping (cheap, deterministic) or from keyword tagging of briefings. The committee→topic mapping is trivially derivable from existing `committee_key`; free-text topic tagging is the proposed extension.
- **View toggle:** `Feed` (default) ↔ `Search results`. Search state: `idle`, `typing` (debounced), `results`, `empty` (`No summaries match "…"` / `該当なし`), `error`.

---

### 7.8 Processing / auth / quota states (user-friendly)

These states surface the real operational constraints of the NotebookLM pipeline. Each is a calm, actionable banner or card — never a raw traceback (the CLI already returns clean messages on stale auth).

| Condition | Where | Copy (EN / JP) | Action | Binding |
|---|---|---|---|---|
| Pending summarisation | Meeting Detail + feed chip | `Not summarised yet — queued for the next run.` / `未要約（次回実行待ち）` | `Generate summary` → `request_generation` | `state != done`; EXISTS |
| Daily quota reached | header banner after catch-up | `Daily AI quota reached. Summaries resume tomorrow.` / `本日のAI枠に到達。明日再開します。` | dismiss; auto-clears next day | `rate_limited=true` from `policy run` / `NotebookLMRateLimitError`; EXISTS |
| NotebookLM auth needed | header banner (blocking the run action) | `NotebookLM sign-in needed to generate summaries. Run notebooklm login, then retry.` / `要約生成にはNotebookLMのサインインが必要です。` | link to runbook; disable `Run catch-up` | `auth_ok()` / `NotebookLMAuthError`; EXISTS |
| Generation timeout | Meeting Detail | `Summary is taking longer than expected — it'll finish on the next run.` / `要約生成がタイムアウト。次回に持ち越します。` | none (auto-resumes) | `NotebookLMTimeout`; meeting stays `generating` for `resume()`; EXISTS |
| Retry exhausted | feed chip + detail | `Couldn't summarise after 3 tries. Check the source documents.` / `3回の試行後も失敗しました。` | `Retry manually` (`request_generation`) | `retry_count ≥ MAX_RETRIES`; EXISTS |
| Synthesis nearing cap | committee header note | `This committee's AI notebook is nearly full — a roll-up will run soon.` / `シンセシスの容量が上限に近づいています。` | informational | 80% of `NOTEBOOKLM_SOURCE_CAP` (`source_count`); EXISTS |

Banner behaviours: quota/auth banners are page-level and persist until resolved; timeout/pending states are row/detail-scoped. All states are derived from fields and exit codes that exist today — no new backend needed except the audio, recording, view-count, and full-text-search items already marked PROPOSED.

---

### 7.9 Bilingual handling (JP source vs EN summary)

- **Source content stays Japanese, always.** Committee names (`name_ja`), meeting titles (`title`), and every source PDF (`PolicyMaterial.title`/`url`) render in their original Japanese. The detailed `briefing_md` is Japanese and is the authoritative, human-verifiable record (built directly from 議事録/資料). No on-the-fly translation of source docs.
- **English is a parallel digest layer.** `digest_en_json.answer` (per meeting) and `running_digest_en_md` (per committee) are model-written English summaries. They are labelled `AI-generated English digest` / `AI英語ダイジェスト` so readers know provenance differs from the JP briefing.
- **UI language toggle (JP/EN)** governs *chrome* (labels, chips, buttons, banners) globally — mapped to the existing `T(key, lang)` i18n mechanism. It does **not** hide the opposite-language *content*: in either mode, a meeting shows the EN digest up top and the JP briefing in an expander, so a bilingual analyst never loses the authoritative source.
- **Names:** every committee, product, and body renders bilingually (`name_en` primary + `name_ja` muted, or swapped by toggle). Where only Japanese exists (meeting titles, PDF link text), it renders as-is with a subtle `JP` tag rather than an empty English slot.
- **Search** indexes both languages so an English query (`capacity market`) and a Japanese query (`容量市場`) both hit the same meetings; the discovery EN→JP keyword bridge (`discover.py`) is reused for query expansion.

---

**Grounding notes for the designer (what is real vs. proposed):**

- EXISTS TODAY: committee registry + tiers + follow/enable + discovery/probe; meeting detection + full lifecycle states + retry/quality flags + `gen_requested` queue; JP briefings + EN digests + JP/EN committee synthesis + downloadable running docs; source-material list with kinds; "recently summarised" feed; all processing/auth/quota/timeout states. Files: `src/repower/policy/{store.py, detect.py, pipeline.py, discover.py, committees.py, notebook.py}`, `src/repower/db.py`, `.claude/skills/policy-catchup/SKILL.md`.
- PROPOSED (needs integration): NotebookLM **audio overview/podcast** player (no audio artifact is generated or stored today — pipeline emits text report + `ask` digest only; audio generation has never run here); **YouTube live-recording link** and **view-count importance signal** (needs `recording_url`/`yt_view_count` + the YouTube Data API); **full-text search** index over the existing summary text columns (SQLite FTS5); **topic filter** taxonomy beyond the trivial committee→topic mapping; surfacing **online-latest vs summarised watermark** as a persisted backfill-gap signal.

---

## 8. Data Sources, Feasibility & Open Questions (Appendix)

This appendix is the honesty layer of the spec. It maps every data element the design binds to its actual origin in the RePower codebase, flags anything **PROPOSED** (and the integration work it requires), and records the assumptions, open questions, and build phasing so a designer can prototype in Claude Design without over-promising to the client.

> **Legend.** ✅ **EXISTS** = collected today and queryable from a cited table/parquet/field. 🟡 **DERIVED** = computed at read time from existing data (no new collection). 🟠 **PROPOSED** = not in the codebase; requires the named integration before it can be bound. Cadences are the *upstream refresh*, not the dashboard poll rate. "Latency" is worst-case staleness a user might see.

### (a) Data-element → source feasibility matrix

#### Wholesale (JEPX) — all EXISTS today

| Data element (spec label EN / JA) | Source: table · field · scraper | Status | Units | Refresh cadence | Risk / latency notes |
|---|---|---|---|---|---|
| Area spot price max/avg/min / エリアスポット価格 | `JepxAreaPrice30m.price` (9 areas) via `jepx_spot.py`; max/avg/min **derived** on aggregation | ✅ / 🟡 | ¥/kWh | Daily cron (JEPX posts ~10:30 JST prev day) | max/avg/min are **identical at Native** — they only diverge once Daily/Weekly/Monthly aggregation runs. Do not imply intraday min/max at 30-min resolution. |
| System price / システムプライス | `JepxSpot30m.system_price`, `.tokyo_area_price` (legacy, system + Tokyo only) | ✅ | ¥/kWh | Daily cron | Legacy table; only system-wide + Tokyo. For per-area use `JepxAreaPrice30m`. |
| Generation mix (14 stacked layers + total) / 電源構成 | `DemandSupply30m` — `nuclear, lng, coal, oil, thermal_other, hydro, geothermal, biomass, solar_actual, wind_actual, pumped, battery, interconnect, other, total_supply` via `scrapers/areas.py` | ✅ | MW | Daily cron (TSO monthly CSVs) | 22-col vs 20-col layouts differ by TSO; older/legacy areas may lack `thermal_other`/`biomass` splits. `total_supply` is an overlay line, never stacked (14 stack keys + total overlay). `solar_curtail`/`wind_curtail` exist but are not charted. |
| Area demand / エリア需要 | `DemandSupply30m.area_demand_mw` | ✅ | MW | Daily cron | JST implicit (no tz column). |
| Aggregation Native/Daily/Weekly/Monthly | `read.py` reducers (`price_max`→max, `price_min`→min, mean elsewhere) | 🟡 | — | Read-time | Weekly = ISO-week Monday; Monthly = month-start bucket. |

#### Balancing (EPRX 需給調整市場) — all EXISTS today (FY2025+)

| Data element | Source: parquet · field | Status | Units | Cadence | Risk / latency |
|---|---|---|---|---|---|
| Market procurement / contracted / bid volumes / 募集量・約定量・応札量 | `eprx_balancing.parquet` — `metric ∈ {demand_mw, contracted_mw, bid_volume_mw}` per `product × area` | ✅ | MW | Daily cron | `demand_mw` label is **募集量 / Market Procurement** (see 4i). 8-block (3h) vs 48-block (30-min) coexist; **never interpolate 8→48**. |
| Unprocured / 未達 (`missing_mw`) | **derived** post-aggregation as `demand − contracted` | 🟡 | MW | Read-time | Only meaningful when both present; can be negative near zero — clamp/annotate. |
| Clearing price max/avg/min / 約定価格 | `eprx_balancing.parquet` — `metric ∈ {price_max, price_avg, price_min}` | ✅ | ¥/kW·30min | Daily cron | Note the **unit differs from wholesale** (¥/kW·30min, not ¥/kWh). |
| Bid / contract counts / 応札・約定件数 | `metric ∈ {bids_count, contracted_count}` | ✅ | count | Daily cron | Dimensionless; render on right Y-axis only. |
| 7 products (Primary … Composite) | `product_code ∈ {1-0,1-1,2-1,2-2,3-1,3-2,4-0}` | ✅ | — | Daily cron | — |
| Interconnector limits/reserved / 連系線 | `eprx_tieline.parquet` — `metric ∈ {upper_limit_fwd/rev, reserved_fwd/rev}`, `market ∈ {DCM,DAM}` | ✅ | MW | Daily cron | `market` meaning: DCM = 需給調整市場 (Balancing Market); DAM = 三次調整力② (Tertiary 2). Pair naming changed **post-2026-03-14** (combined zones via `is_combined`); pre-date pairs merged. |

#### Drivers — all EXISTS today

| Data element | Source | Status | Units | Cadence | Risk / latency |
|---|---|---|---|---|---|
| Brent crude / Henry Hub NG / USD·JPY | `FuelDaily` — `ticker ∈ {BZ=F, NG=F, JPY=X}`, `.close`, `.currency` via `fuels_futures.py` (yfinance) | ✅ | USD/bbl, USD proxy, JPY/USD | Daily close, rolling ~7-day cache | yfinance is a **third-party, unstable** feed — gaps/holidays common. NG=F is a *proxy* for JKM, not JKM itself; label carefully. |
| JEPX ↔ Brent correlation | Pearson r **derived** from `JepxAreaPrice30m` × `FuelDaily` (`legacy.py`) | 🟡 | r (−1..1) | Read-time | Correlation only; not a causal/forecast signal. |

#### Analyses — PARTIALLY exists (omitted from nav; see 2.1 / 5.10)

| Data element | Source | Status | Notes |
|---|---|---|---|
| Per-date feature JSON / 指標 | `AnalysisRecord.features_json` — written by `analysis/features.py` | ✅ | Confirmed written to DB today. |
| Daily narrative / 日次ナラティブ | `AnalysisRecord.narrative_md` | 🟠 **PROPOSED** | Column is **scaffolded but not generated** — no LLM writes it today. Needs an LLM narrative-generation job (cost/token tracking columns `model, tokens_in, tokens_out, cost_usd` already exist). **Do not render as populated in mockups**; show the empty-state "AI Daily Brief" card (5.10). |

#### Policy Observer — mostly EXISTS; committee-radar attention layer is PROPOSED

| Data element | Source: table · field | Status | Cadence | Risk / latency |
|---|---|---|---|---|
| Tracked committees (14) + priority/enabled | `PolicyCommittee` — `committee_key, name_ja/en, source, priority, enabled, user_added` | ✅ | On edit / daily catch-up | Priority tiers: `system_review=1, emissions_trading=2, chousei_jukyu=3, default=100`. This `committee_key→priority-tier` map is the enumerated source of truth for the Radar `P̂`/`tier_weight` (7.3.2). |
| Meeting list, state, dates | `PolicyMeeting` — `meeting_num, meeting_date, title, state, quality_flag` | ✅ | Detection (auth-free, daily) | State machine: detected→…→done/error; `quality_flag ∈ {ocr_suspect, short_output, download_failed, no_sources}`. Rows exist **only for tracked committees** (enabled or disabled). |
| JP briefing / EN digest | `PolicyMeeting.briefing_md`, `.digest_en_json` | ✅ | NotebookLM catch-up (~1 run/24h, quota-bound) | **Not real-time.** Summaries lag detection by days; gated on NotebookLM auth freshness (weekly re-auth). Mockup must show "awaiting summary" states. |
| Committee running doc / synthesis | `PolicyCommittee.running_summary_md`, `.running_digest_en_md`; `data/policy/<key>.md` | ✅ | Regenerated each cycle | Deterministic from DB (never appended). |
| Materials (PDF sources) | `PolicyMaterial` — `kind, url, title, sha256` | ✅ | Detection | `kind ∈ {minutes, brief, compilation, handout, agenda, appendix}`. |
| Dashboard "generate now" queue | `PolicyMeeting.gen_requested` | ✅ | On click; consumed at next catch-up | Jumps priority queue; **not instant** — still quota-bound. UI must say "queued", not "generating". |
| **Committee "importance" / radar rank** | — | 🟡/🟠 | Read-time | Computed from existing signals per (b); no stored importance/score field. The `V̂` view term is 🟠 PROPOSED. |
| **METI YouTube recording link / view count** | — | 🟠 **PROPOSED** | — | **Confirmed absent from codebase** (grep: no YouTube/view-count references). Links to `@metichannelshingikai` can be *constructed/manual*; **view counts require the YouTube Data API v3** (API key + quota + video-ID mapping per meeting). |
| **NotebookLM audio overview / podcast** | — | 🟠 **PROPOSED** | — | **No audio artifact is generated or stored anywhere**; pipeline emits text report + `ask` digest only. Audio generation is a NotebookLM *platform* capability but has never been wired or run here (7.6.6). |
| Committee-tier taxonomy (Shingikai › EGC › WG) | Implicit in `source ∈ {METI, OCCTO, EGC}` + `priority` | 🟡/🟠 | — | Grouping by `source` + priority-tier EXISTS; a richer *hierarchical* taxonomy (advisory-committee → division → WG) is PROPOSED (static config, no scraping). |

#### News / alerts — thin today

| Data element | Source | Status | Notes |
|---|---|---|---|
| News items (METI/OCCTO/Google News JP) | `NewsItem` — `source, title, summary, published_at` | ✅ (detection) | `summary` is **RSS-provided, not LLM-generated**. Fine for a raw feed list; do not label as "AI summary". |
| Threshold alerts / price-spike notifications | `notify/webhook.py` exists (webhook plumbing) | 🟠 **PROPOSED** | Webhook delivery exists, but there is **no alerting rule engine** (thresholds, dedup, per-user subscriptions). The concrete rule shape is defined in 3.5 so the prototype can render the example alert. |
| Global search (top-bar) | — | 🟠 **PROPOSED** | Donezo-style omni-search needs a search index over areas/products/committees/meetings. Buildable cheaply as a **client-side static index** (finite, known entities) — mark as PROPOSED-lite. |
| User / avatar / auth | — | 🟠 **PROPOSED** | No auth/identity layer in RePower (single Streamlit app). Any avatar/email in the top bar is PROPOSED (needs SaaS auth). Mock with a placeholder user. |

### (b) METI Committee Radar — the single canonical importance-ranking model

There is exactly **one** importance model in this spec. Sections 5.6.2, 5.6.5, and 7.6.5 all reference it; none defines a competing formula. It produces a transparent, explainable score `I ∈ [0,100]` per meeting (and per committee) used to rank the Policy "radar", size cards, and drive the "why this rank" popover. It **ships with view-count weight redistributed to 0** until the YouTube Data API is integrated, and degrades gracefully.

**Candidate set:** meetings that exist in `PolicyMeeting` (tracked committees, enabled or disabled) with `meeting_date` in the trailing 90 days. Never-tracked committees have no rows (see 5.6 scope note).

**Inputs** (all derivable from existing tables except `V`):

| Signal | Symbol | Source | Direction | Normalization |
|---|---|---|---|---|
| Editorial priority tier | `P` | `PolicyCommittee.priority` (1/2/3/100) → enumerated `committee_key`→tier map (7.3.2) | lower = more important | `P̂ = 1 − (rank−1)/(N−1)` over distinct tiers |
| Recency of latest meeting | `R` | `PolicyMeeting.meeting_date` (max) | newer = higher | exponential decay, **30-day half-life**: `R̂ = 0.5^(age_days/30)` |
| Activity / cadence | `A` | count of `PolicyMeeting` in trailing 90d | more = higher | min-max across committees |
| Decision density | `D` | share of recent meetings with `has_torimatome` / minutes present (`PolicyMaterial.kind`) | more = higher | ratio 0–1 |
| Summary freshness | `F` | `state=done` & `synth_done` coverage of recent meetings | more complete = higher | ratio 0–1 |
| **Public attention (view count)** | `V` | 🟠 YouTube Data API v3 `statistics.viewCount` mapped per meeting video | more = higher | log-scaled then min-max: `V̂ = (log(1+v)−min)/(max−min)` |

**Weighting (default profile "Regulatory-lead"):**

```
I = 100 · ( 0.35·P̂ + 0.25·R̂ + 0.15·Â + 0.10·D̂ + 0.05·F̂ + 0.10·V̂ )
```

- Weights are a **named token set** (`radar.weights.regulatory_lead`) so the client can tune without redesign; a secondary "Attention-lead" profile shifts `V̂→0.25` once view data exists.
- **Recency uses a single constant: a 30-day half-life** (`R̂ = 0.5^(age_days/30)`). This is the one recency parameter in the spec — there is no separate 21-day τ anywhere.

**Normalization rules:** all sub-scores mapped to `[0,1]` before weighting; committee-level `I` = its latest-meeting score blended 70/30 with a trailing-90-day mean to damp single-meeting spikes.

**Fallback when view counts are missing (the default state today):**

1. Set `w_V = 0` and **re-normalize the remaining weights to sum to 1** (so `I` stays on a 0–100 scale) — do *not* impute a fake view count.
2. Badge affected cards with a subtle "attention data unavailable / 注目度データなし" tooltip so the ranking is honestly explained.
3. When some committees have views and others don't, rank the view-less set by the re-normalized non-`V` score and **sort them below** any equally-scored committee that *does* carry a real `V̂` (never let a null outrank a measured signal).

**Explainability:** each radar card / meeting-detail signal row exposes a "why this rank" popover listing the top 2–3 contributing signals with their normalized values — no black-box number, and no second scoring notion.

### (c) Assumptions this spec makes

- **Target = a responsive web SaaS app**, mocked in Claude Design — *not* the existing Streamlit app. Streamlit/D3 components are treated as a **data + interaction contract**, not the rendering target. Layout uses a 12-col responsive grid (desktop ≥1280, tablet 768–1279, mobile <768).
- **Brand palette is pending client sign-off.** The navy/teal hex values (`#1B2A4A`, `#00A5CF`, etc.) are reused as *values only* under neutral token names. The single Donezo-style accent is fixed at **teal `#00A5CF`** across the whole spec; navy is ink/dark-surface only. No color-constant name derives from any prior brand. **Client decision (2026-07-02): keep this placeholder "Harbor" palette for the prototypes;** a distinct JEMA brand palette may follow later — tokens are named so a swap is a one-line change.
- **Time & units conventions:** all energy timestamps are **JST** (implicit in source; no tz column — the UI must state "All times JST"). Units are fixed: MW (volumes), **¥/kWh** (wholesale), **¥/kW·30min** (balancing), USD/JPY (fuels). Counts are dimensionless.
- **Resolution truth:** native granularity is 30-min (or 8-block/3h for some EPRX series). max/avg/min price spreads and `missing_mw` are **aggregation-derived**, not native fields.
- **Data recency is cron-bound, not live.** Everything refreshes on a daily GitHub Actions cron via HF sync; the app is **near-daily, not real-time**. No streaming/tick data exists. Mockups should avoid "live" language.
- **Bilingual JP/EN** is first-class; every user-facing string has a `T(key, lang)` counterpart, and metric labels come from `metric_labels(lang)`. Default language assumed **ja**.
- **The internal repo name is never surfaced** in user-facing copy; user-facing brand is JEMA only.
- **Deployment = single-tenant / internal for now** (client decision 2026-07-02). Logins, per-user watchlist, and price alerts are planned but deferred; in v1 mockups the top-bar user zone, watchlist, and alert bell render as clearly-labelled **placeholders** (bind to a placeholder user; use global-scope prefs where a rule store is implied).

### (d) Client decisions & open questions

**Decisions locked with the client (2026-07-02):**

1. **Brand palette — keep the placeholder.** Prototype on the teal `#00A5CF` + navy `#1B2A4A` "Harbor" base; a distinct JEMA palette may follow later. Named tokens make a later swap trivial.
2. **Committee Radar view counts — deferred.** No YouTube Data API for now. The Radar ships with `w_V = 0`, ranking on DB-derived signals only (priority, recency, activity, decision density, summary freshness). The views chip and the "adjust weighting → views" affordance render only in the fallback/empty treatment (§5.6.3–5.6.4).
3. **AI Daily Brief / Analyses narrative — deferred.** Not in v1. Analyses stays out of primary nav; if the landing card is ever added it remains the labelled empty state (§5.10).
4. **Auth & tenancy — single-tenant for now.** No login in v1. Accounts, per-user watchlist, and price alerts are planned but **deferred**; the top-bar user zone, watchlist, and alert bell render as **placeholders** in the mockups (placeholder user; global-scope prefs where a rule store is implied).
5. **Untracked-committee radar coverage — future pass.** The Radar covers **tracked committees only** (§5.6); a broad discovery/detection pass to surface never-tracked committees is a later phase.

**Still open (not yet decided):**

- **Committee taxonomy depth:** `source` (METI/OCCTO/EGC) + priority-tier grouping, or the full Shingikai → EGC-division → WG hierarchy (static config to build)?
- **Real-time expectations:** is near-daily refresh acceptable for every surface (esp. spot price), or is intraday freshness needed anywhere (new intraday collection)?
- **Export parity:** must the web app retain the Streamlit app's Excel/PDF export, and at what fidelity?
- **NotebookLM audio overviews:** wire audio-overview generation into the pipeline later (new step + artifact storage + HF sync), or keep the audio player (§7.6.6) a permanent labelled-empty placeholder?

Every locked-**deferred** item sits in **Phase 2** of the phasing note below, so **Phase 1 (buildable now) is unaffected**; the prototypes render all deferred surfaces as clearly-labelled empty/awaiting states.

### (e) Phasing note

**Phase 1 — buildable now from existing data (no new integrations):**
Wholesale grid (price + generation mix + demand), Balancing grid (7 products, volumes, clearing prices), Interconnector panel (DCM/DAM), Drivers (Brent/NG/FX + JEPX correlation), Policy Observer read surfaces (committee list, priorities, meeting states, JP briefings + EN digests, running docs, quality-flag chips, "generate now" queue), Native/Daily/Weekly/Monthly aggregation, period comparison, KPI cards, and a **client-side global search** over the finite known entities. The Committee Radar ships **immediately with `w_V=0`** using only DB-derived signals (priority, recency, activity, decision density, summary freshness).

**Phase 2 — depends on PROPOSED sources / integrations:**

- Committee Radar **attention weight** → YouTube Data API v3 (view counts + video mapping).
- **METI live-recording link** and **audio overview** → recording resolver + NotebookLM audio pipeline step + artifact storage.
- **Analyses daily narrative** (AI Daily Brief) → LLM generation job populating `AnalysisRecord.narrative_md`.
- **Notifications / alert bell** → alert-rules engine on top of existing `notify/webhook.py` (rules per 3.5).
- **User/avatar/personalized search, watchlist & saved views** → SaaS auth/identity layer (none exists today).
- **Full-text policy search** → SQLite FTS5 index over existing summary text columns.
- **News "AI summaries"** → LLM summarization of `NewsItem` (today `summary` is raw RSS text only).

Mockups should render Phase-2 surfaces in a clearly-labelled **empty/awaiting state** so the client never mistakes proposed capability for shipped data.

---

*Relevant grounding files (absolute paths): `C:\Users\SehunNakama\Projects\Remote Energy Market Status\src\repower\db.py` (table schemas), `...\src\repower\dashboard\read.py` (aggregation/derived metrics), `...\src\repower\dashboard\theme.py` (color hex), `...\src\repower\dashboard\i18n.py` (JA/EN labels, `metric_labels`), `...\src\repower\analysis\features.py` (confirms `features_json` written, `narrative_md` not), `...\src\repower\policy\{store.py, detect.py, pipeline.py, discover.py, committees.py, notebook.py}`, `...\src\repower\notify\webhook.py` (webhook plumbing, no rule engine).*
