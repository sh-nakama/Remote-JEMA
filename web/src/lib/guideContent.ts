// Content of the in-app "i" guide: three tabs — Screens, Policy Deep Dive, and (local backend only) Commands.
//
// Pure data, no React, so it sits apart from the panel in menus.tsx. It is a SIMPLIFIED mirror of
// docs/USER-GUIDE.md: update the doc first, then mirror the short copy here. The Commands tab's
// per-command text is NOT here — it comes from the same registry the server runs
// (repower/commands.py via GET /api/commands), so it cannot go stale.

export interface GuideItem { en: string; ja: string }
export interface GuideSection { hEn: string; hJa: string; items: GuideItem[] }

export const SCREENS_GUIDE: GuideSection[] = [
  {
    hEn: 'What JEMA is', hJa: 'JEMAとは',
    items: [
      { en: 'Japan Energy Market Analytics: Japanese power-market data (JEPX prices, supply/demand per area, balancing and capacity markets) plus the government policy committees that shape it.',
        ja: 'Japan Energy Market Analytics: 日本の電力市場データ（JEPX価格、エリア別需給、需給調整・容量市場）と、それを動かす政策委員会を扱います。' },
    ],
  },
  {
    hEn: 'The four screens', hJa: '4つの画面',
    items: [
      { en: 'Market Overview — the landing page: headline prices, the generation mix and overall data status.',
        ja: 'マーケット概況 — 最初の画面。主要価格、電源構成、データの状態。' },
      { en: 'Market Data — wholesale spot prices and per-area supply/demand, with area focus, time range and granularity (Native / Daily / Weekly / Monthly).',
        ja: 'マーケットデータ — 卸スポット価格とエリア別需給。エリア・期間・粒度（ネイティブ/日次/週次/月次）を選べます。' },
      { en: 'Capacity & Auctions — capacity-market auction results and their latest publication.',
        ja: '容量市場・オークション — 容量市場の入札結果と最新の公表。' },
      { en: 'Policy Deep Dive — METI/OCCTO/EGC committees: their meetings, source documents, AI briefings and bilingual digests. See the Policy Deep Dive tab.',
        ja: '政策ディープダイブ — METI/OCCTO/EGCの委員会の会合、元資料、AIによる要約とバイリンガルのダイジェスト。「政策ディープダイブ」タブをご覧ください。' },
    ],
  },
  {
    hEn: 'On every screen', hJa: '全画面共通',
    items: [
      { en: '⌘K (Ctrl-K) opens search; the top bar has the theme toggle, this guide, notifications, the language toggle (English / 日本語) and your profile.',
        ja: '⌘K（Ctrl-K）で検索。トップバーにテーマ切替、このガイド、通知、言語切替（English / 日本語）、プロフィールがあります。' },
      { en: 'The left pane holds navigation, the Watchlist, Notifications, Settings and the data-freshness card. Collapse it with “Collapse”; reopen it from the JEMA pill.',
        ja: '左ペインにはナビゲーション、ウォッチリスト、通知、設定、データ鮮度カードがあります。「折りたたむ」で閉じ、JEMAのピルから開き直せます。' },
      { en: 'Your preferences (theme, language, watchlist, followed committees, home screen) are saved in this browser only.',
        ja: 'テーマ、言語、ウォッチリスト、フォロー中の委員会、起動画面などの設定は、このブラウザにのみ保存されます。' },
    ],
  },
  {
    hEn: 'Data freshness & the daily runs', hJa: 'データ鮮度と日次実行',
    items: [
      { en: 'GitHub Actions refresh the data every day (market data around 05:30 JST, policy summaries around 06:30 JST), sync it to a private Hugging Face dataset and rebuild the public site. GitHub can start scheduled jobs hours late, so a slightly late update is normal.',
        ja: 'GitHub Actionsが毎日データを更新します（市場データは約05:30 JST、政策要約は約06:30 JST）。更新は非公開のHugging Faceデータセットに同期され、公開サイトが再構築されます。GitHubは定期ジョブの開始が数時間遅れることがあるため、多少の遅れは通常です。' },
      { en: 'The Refresh button on the freshness card re-reads the latest published snapshots. Run locally, it does a real refresh instead: recover gaps, scrape every source, re-export.',
        ja: 'データ鮮度カードの「更新」は、最新の公開スナップショットを再読み込みします。ローカルで実行している場合は、欠損の補完、全ソースの取得、再エクスポートまでを実行します。' },
    ],
  },
  {
    hEn: 'Local vs public', hJa: 'ローカルと公開サイト',
    items: [
      { en: 'The public site is read-only: it shows the last published snapshots and has no write controls.',
        ja: '公開サイトは閲覧専用です。最後に公開されたスナップショットを表示し、書き込み操作はありません。' },
      { en: 'Run locally with `repower web-api` alongside the web app and the write controls appear: Track, Check for updates, Run catch-up, and the Commands pane on the right. The master copy of the data is the one on your machine.',
        ja: '`repower web-api` をWebアプリと一緒にローカルで起動すると、追跡、差分取得、右側の「コマンド」パネルなどの書き込み操作が現れます。データの正本はお手元のコピーです。' },
    ],
  },
]

export const POLICY_GUIDE: GuideSection[] = [
  {
    hEn: 'What this screen is', hJa: 'この画面について',
    items: [
      { en: 'Tracks Japanese energy-policy committees (METI/OCCTO/EGC): their meetings, the documents published for each, and AI briefings & bilingual digests of what was discussed.',
        ja: '日本のエネルギー政策委員会（METI/OCCTO/EGC）の会合、公開資料、AIによる要約・バイリンガルのダイジェストを追跡します。' },
    ],
  },
  {
    hEn: 'The three panes', hJa: '3つのペイン',
    items: [
      { en: 'Explorer (left): the full committee catalog — tracked ones and ones the tool discovered (tagged UNTRACKED). Search and follow committees here.',
        ja: 'エクスプローラー（左）: 委員会カタログ全体。追跡中と、発見済みで未追跡（UNTRACKED）の委員会。検索・フォローができます。' },
      { en: 'Feed (center): meetings as cards, newest first, with a search box, date filters, and a Tracked/All toggle.',
        ja: 'フィード（中央）: 会合をカード表示（新しい順）。検索、日付フィルタ、追跡/全体トグルがあります。' },
      { en: 'Detail (right): pick a committee to see its rolling synthesis, or a meeting to see that session’s digest and source PDFs.',
        ja: '詳細（右）: 委員会を選ぶと総括、会合を選ぶとその回のダイジェストと元資料PDFを表示します。' },
    ],
  },
  {
    hEn: 'Topic filter', hJa: 'トピックフィルタ',
    items: [
      { en: 'Topic ▾ in the filter bar narrows everything to subjects such as offshore wind, grid-scale batteries or grid connection (pick several: it matches any of them).',
        ja: 'フィルタバーの「トピック ▾」で、洋上風力・系統用蓄電池・系統接続などの話題に絞り込めます（複数選択可、いずれかに一致）。' },
      { en: 'A committee’s tags are its standing mandate; a meeting’s tags are what that meeting actually discussed — they are not inherited.',
        ja: '委員会のタグはその恒常的な所掌、会合のタグはその回の議題そのもの。委員会から引き継ぐことはありません。' },
      { en: 'With a topic selected, committees are ranked by how much of their recent work it is (e.g. “Offshore wind 74%”). A committee’s detail shows a coverage bar per topic.',
        ja: 'トピックを選ぶと、その話題が各委員会の直近の活動に占める割合（例:「洋上風力 74%」）の高い順に並びます。委員会の詳細にはトピックごとの網羅度バーが表示されます。' },
    ],
  },
  {
    hEn: 'Follow vs. Track (they differ)', hJa: 'フォローと追跡の違い',
    items: [
      { en: 'Follow is a personal filter saved in your browser — it highlights committees and drives the Followed filter only.',
        ja: 'フォローはブラウザに保存される個人設定。ハイライトと「フォロー中」フィルタにのみ影響します。' },
      { en: 'Track is a backend setting (in Manage committees). Only tracked committees get AI summaries generated.',
        ja: '追跡はバックエンド設定（「委員会の管理」内）。追跡中の委員会のみがAI要約されます。' },
    ],
  },
  {
    hEn: 'Meeting status', hJa: '会合のステータス',
    items: [
      { en: 'Pending: known and has materials, waiting for its AI digest.',
        ja: 'ペンディング: 資料あり、AIダイジェスト待ち。' },
      { en: 'Done: summarised — has a digest and feeds the committee synthesis.',
        ja: '完了: 要約済み。ダイジェストがあり、委員会の総括に反映されます。' },
      { en: 'Error: summarisation failed; retried a few times, then dropped.',
        ja: 'エラー: 要約に失敗。数回再試行後に除外されます。' },
      { en: 'A meeting with no materials yet is hidden — materials are what make it appear.',
        ja: '資料がまだ無い会合は非表示です。資料が揃うと表示されます。' },
      { en: 'Manage → Status: one row per committee (tracked first, most recently updated first) — what the pipeline last did, how long ago, and whether the pages could be fetched. Expand a row for each meeting’s state and the error it failed with.',
        ja: '「管理」→「状態」: 委員会ごとに1行（追跡中が先頭、更新の新しい順）。直近の処理内容・経過時間・ページ取得の可否を表示。行を展開すると会合ごとの状態と失敗理由が見られます。' },
      { en: 'One meeting at a time: LATEST summarises a committee’s newest pending meeting and stops; ▶ on a single meeting runs just that one (and can re-run a summarised one); ↑ moves it to the front of the queue.',
        ja: '1件ずつ処理: 「最新」は最新の未要約会合のみを要約。会合行の▶はその1件だけを実行（要約済みの再実行も可）、↑はキューの先頭へ移動します。' },
      { en: 'A meeting is only summarised when every one of its documents was fetched — the DOCS IN column shows how many reached the AI. A summarised meeting showing 3/12 saw only part of the papers; re-run it with ▶.',
        ja: '全ての資料を取得できた場合のみ要約します。「取込資料」列はAIに渡された件数です。要約済みで3/12などの場合は一部しか参照していないため、▶で再実行してください。' },
    ],
  },
  {
    hEn: 'Citations & source documents', hJa: '引用と元資料',
    items: [
      { en: 'Each digest ends with citation chips such as “[3] 資料1 · p.18”. Click one to open that PDF at the cited page (“pp.18–19” when the passage runs across a page break). Hover for the quoted passage.',
        ja: 'ダイジェストの末尾に「[3] 資料1 · p.18」のような引用チップがあります。クリックすると該当PDFをそのページで開きます（ページをまたぐ場合は「pp.18–19」）。ホバーすると引用文を表示します。' },
      { en: 'Meetings summarised from now on have their pages found automatically. For earlier meetings, the first click in the local app fetches the meeting’s PDFs and finds the pages (up to a minute; a blank tab opens at once and fills in) — after that it is remembered.',
        ja: '今後要約される会合は、ページが自動で特定されます。過去の会合は、ローカルアプリで最初にクリックした際にPDFを取得してページを探します（最大1分。空のタブがすぐに開き、完了後に表示）。以降は記憶されます。' },
      { en: 'A citation that cannot be placed on a page is left unlinked rather than guessed. On the public site only citations already resolved are links.',
        ja: 'ページを特定できない引用は、推測せずリンクなしのままにします。公開サイトでは、解決済みの引用のみリンクになります。' },
      { en: 'SOURCE MATERIALS lists every PDF published for the meeting; click one to open the original.',
        ja: '「配布資料」には会合で公開された全PDFが並びます。クリックすると原本を開きます。' },
    ],
  },
  {
    hEn: 'Check for updates (catch-up)', hJa: '更新の確認（差分取得）',
    items: [
      { en: 'Runs five stages, shown live in the progress panel (bottom-left):',
        ja: '5つのステージを実行し、進捗パネル（左下）にライブ表示します:' },
      { en: '1. detect — find new meetings across every committee.',
        ja: '1. detect — 全委員会の新規会合を検出。' },
      { en: '2. materials — fetch documents for meetings that had none yet (self-heal).',
        ja: '2. materials — 資料が無かった会合の資料を取得（自動修復）。' },
      { en: '3. dates — fill in missing meeting dates.',
        ja: '3. dates — 欠けている会合日を補完。' },
      { en: '4. schedule — refresh upcoming meetings (skipped if the METI feed is down).',
        ja: '4. schedule — 今後の会合を更新（METIのフィード停止時はスキップ）。' },
      { en: '5. discover — find new committees you don’t track yet.',
        ja: '5. discover — 未追跡の新しい委員会を発見。' },
      { en: 'The button needs a local backend running; the public site is read-only.',
        ja: 'このボタンはローカルのバックエンドが必要です。公開サイトは閲覧専用です。' },
    ],
  },
  {
    hEn: 'Summaries', hJa: '要約',
    items: [
      { en: 'For tracked committees, pending meetings are summarised into a bilingual digest, then folded into the committee synthesis.',
        ja: '追跡中の委員会では、ペンディングの会合がバイリンガルのダイジェストに要約され、委員会の総括に統合されます。' },
      { en: 'Use Generate summary on a meeting to push it to the front of the queue.',
        ja: '会合の「要約を生成」で、その会合をキューの先頭に移動できます。' },
      { en: 'Summarise all ⚿: starts new work — summarises pending meetings breadth-first (the newest of each tracked committee, in priority order), up to 8 per run, then refreshes each committee synthesis.',
        ja: '全件要約 ⚿: 新規分を開始 — ペンディングの会合を幅優先（各追跡委員会の最新会合を優先順に）で最大8件/回まで要約し、各委員会の総括を更新します。' },
      { en: 'Resume ⚿: only drains meetings left mid-flight (stuck after an interrupted or rate-limited run) — it continues where it left off, and does nothing if none are stuck.',
        ja: '再開 ⚿: 途中で止まった会合のみを処理（中断・レート制限後に残ったもの）。中断地点から再開し、対象が無ければ何もしません。' },
      { en: 'Both Summarise buttons need a NotebookLM login. In the local app use Sign in to NotebookLM in the Commands pane (or `notebooklm login` in a terminal).',
        ja: 'いずれの要約ボタンもNotebookLMへのログインが必要です。ローカルアプリでは「コマンド」パネルの「NotebookLMにログイン」を使います（またはターミナルで `notebooklm login`）。' },
      { en: 'On the hosted setup summarising runs in the daily policy job (about 06:30 JST; GitHub can start scheduled jobs hours late). Locally you can run it on demand.',
        ja: 'ホスト環境では日次のポリシージョブ（約06:30 JST。GitHubは定期ジョブの開始が数時間遅れることがあります）で要約されます。ローカルではいつでも実行できます。' },
    ],
  },
  {
    hEn: 'Search & filters', hJa: '検索とフィルタ',
    items: [
      { en: 'Feed search covers titles, committees, and digests — including untracked committees.',
        ja: 'フィード検索は、未追跡の委員会を含め、タイトル・委員会・ダイジェストを対象とします。' },
      { en: 'Combine the Tracked/All toggle, the date filter, and Followed-only to narrow the feed.',
        ja: '追跡/全体トグル、日付フィルタ、フォロー中のみを組み合わせて絞り込めます。' },
    ],
  },
  {
    hEn: 'Good to know', hJa: '補足',
    items: [
      { en: 'More tools — backfilling older meetings, resolving citation pages, syncing with Hugging Face — are in the Commands pane on the right of the screen (local backend only). See the Commands tab of this guide.',
        ja: '過去の会合の遡及要約、引用ページの解決、Hugging Faceとの同期などは、画面右の「コマンド」パネルにあります（ローカルのバックエンドのみ）。このガイドの「コマンド」タブをご覧ください。' },
      { en: 'The Upcoming list is empty whenever the METI calendar feed is unavailable.',
        ja: 'METIのカレンダーフィードが利用できない間、「今後の会合」は空になります。' },
      { en: 'The source site throttles bursts, so material backfill heals gradually over several runs.',
        ja: '配信元はアクセス集中を制限するため、資料の補完は複数回の実行で徐々に進みます。' },
    ],
  },
]

// What the GitHub Actions run on their own — the short form of the table in docs/USER-GUIDE.md
// ("What runs automatically"). One entry per file in .github/workflows/; tests/test_workflow_docs.py
// fails when a workflow is added, removed or rescheduled without this list following. `cron` is the
// UTC expression exactly as written in the workflow, `jst` the same moment in Japan time.
export interface AutoRun {
  file: string
  cron: string | null
  jst: string | null
  nameEn: string; nameJa: string
  whenEn: string; whenJa: string
  doesEn: string; doesJa: string
  writes: boolean
}

export const AUTOMATED_RUNS: AutoRun[] = [
  {
    file: 'daily.yml', cron: '30 20 * * *', jst: '05:30',
    nameEn: 'Market data', nameJa: '市場データ',
    whenEn: 'Every day, 05:30 JST', whenJa: '毎日 05:30 JST',
    doesEn: 'Scrapes every source, analyses, then detects policy meetings, fills dates and tags, refreshes the schedule and discovers committees. Pushes the dataset and checks nothing has gone stale.',
    doesJa: '全ソースを取得して分析し、政策会合の検出、日付・タグの補完、予定の更新、委員会の発見を実行。データセットを送信し、古いデータが無いか確認します。',
    writes: true,
  },
  {
    file: 'policy.yml', cron: '30 21 * * *', jst: '06:30',
    nameEn: 'Policy summaries', nameJa: '政策の要約',
    whenEn: 'Every day, 06:30 JST', whenJa: '毎日 06:30 JST',
    doesEn: 'Detects new meetings, then — only if the NotebookLM login is valid — resumes stuck meetings, summarises up to 8 and builds the digest. Then, login or not, it resolves the source pages behind citations for up to 5 earlier meetings. A stale login skips the summaries and raises an alert.',
    doesJa: '新規会合を検出し、NotebookLMのログインが有効な場合のみ、中断分の再開、最大8件の要約、ダイジェスト作成を実行。その後、ログインの有無にかかわらず、過去の会合最大5件の引用元ページを特定します。ログインが切れていると要約を省略してアラートを出します。',
    writes: true,
  },
  {
    file: 'weekly-backfill.yml', cron: '30 19 * * 0', jst: '04:30',
    nameEn: 'Weekly re-check', nameJa: '週次の再検証',
    whenEn: 'Mondays, 04:30 JST', whenJa: '毎週月曜 04:30 JST',
    doesEn: 'Re-fetches a deeper window of market data (about 6 months of TSO data, JEPX from last year, EPRX from FY2025) to catch late upstream revisions.',
    doesJa: '市場データをより深い期間（TSOは約6か月、JEPXは前年から、EPRXは2025年度から）で再取得し、公表後の修正を拾います。',
    writes: true,
  },
  {
    file: 'policy-crosscheck.yml', cron: '0 22 1 * *', jst: '07:00',
    nameEn: 'Committee cross-check', nameJa: '委員会の突き合わせ',
    whenEn: 'Monthly, 07:00 JST on the 2nd', whenJa: '毎月2日 07:00 JST',
    doesEn: 'Adds energy committees that the energy-board feed lists and we do not, as untracked.',
    doesJa: 'energy-boardのフィードにあって未登録のエネルギー関連委員会を、未追跡として追加します。',
    writes: true,
  },
  {
    file: 'backfill.yml', cron: null, jst: null,
    nameEn: 'Historical backfill', nameJa: '過去データの遡及取得',
    whenEn: 'Manual only', whenJa: '手動のみ',
    doesEn: 'Fetches market data from a chosen month onward, for one area or all of them.',
    doesJa: '指定した月以降の市場データを、エリアを選んで（または全エリア）取得します。',
    writes: true,
  },
  {
    file: 'web-deploy.yml', cron: '30 21 * * *', jst: '06:30',
    nameEn: 'Public site', nameJa: '公開サイト',
    whenEn: 'After each dataset run; daily 06:30 JST backstop; code changes', whenJa: 'データ更新ごと、毎日 06:30 JST（予備）、コード変更時',
    doesEn: 'Exports snapshots from the dataset and republishes the read-only site. Skipped when nothing changed.',
    doesJa: 'データセットからスナップショットを書き出し、閲覧専用サイトを再公開します。変更が無ければ省略されます。',
    writes: false,
  },
  {
    file: 'sync-space.yml', cron: null, jst: null,
    nameEn: 'Hugging Face Space', nameJa: 'Hugging Face Space',
    whenEn: 'Code changes on main', whenJa: 'mainのコード変更時',
    doesEn: 'Uploads the Streamlit Space and waits for it to rebuild.',
    doesJa: 'Streamlit Spaceをアップロードし、再構築の完了を待ちます。',
    writes: false,
  },
  {
    file: 'ci.yml', cron: null, jst: null,
    nameEn: 'Checks', nameJa: '検査',
    whenEn: 'Every pull request and push to main', whenJa: 'プルリクエストとmainへのpushごと',
    doesEn: 'Lint, type checks and tests for the Python package and the web app.',
    doesJa: 'Pythonパッケージとwebアプリのlint、型チェック、テスト。',
    writes: false,
  },
]

// The Commands tab's fixed text. The per-command descriptions and the ordered flows are rendered from
// the registry; these sections explain how to read them.
export const COMMANDS_GUIDE: GuideSection[] = [
  {
    hEn: 'What the Commands pane is', hJa: 'コマンドパネルとは',
    items: [
      { en: 'The panel on the right (a terminal icon on the right edge when collapsed) runs the same commands as the `repower` CLI, on this machine, through the local backend. Each shows what it does and when to use it; “repower …” under a button is the equivalent terminal command (click to copy).',
        ja: '右側のパネル（折りたたみ時は右端のターミナルアイコン）は、この端末で `repower` CLIと同じコマンドをローカルのバックエンド経由で実行します。各コマンドに説明と使いどころを表示します。ボタン下の「repower …」は同等のターミナルコマンドです（クリックでコピー）。' },
      { en: 'One command runs at a time. Progress and output appear in the progress panel (bottom-left); a finished command refreshes the screen behind it.',
        ja: '同時に実行できるコマンドは1つです。進捗と出力は進捗パネル（左下）に表示され、完了すると背後の画面も更新されます。' },
    ],
  },
  {
    hEn: 'Safety labels', hJa: '安全性ラベル',
    items: [
      { en: 'SAFE — only reads, or signs you in. Run it as often as you like.',
        ja: '安全 — 読み取りまたはログインのみ。何度でも実行できます。' },
      { en: 'WRITES LOCAL DATA — changes the database or files on this machine. Safe to repeat, but the change stays here until you push it.',
        ja: 'ローカル更新 — この端末のDBやファイルを変更します。繰り返しても安全ですが、pushするまで反映は端末内に留まります。' },
      { en: 'DANGEROUS — replaces a whole database. Only “Pull from Hugging Face” and “Push to Hugging Face” are marked this way; each asks you to confirm and tells you what it would overwrite.',
        ja: '危険 — DB全体を置き換えます。「Hugging Faceから取得」と「Hugging Faceへ送信」のみが該当し、実行前に確認と、何が上書きされるかの説明が表示されます。' },
    ],
  },
  {
    hEn: 'Order matters: pull → work → push', hJa: '順序が重要: pull → 作業 → push',
    items: [
      { en: 'Pull and push each replace an entire database, last write wins, with no merging — and the daily GitHub Actions write to the same dataset. So: pull first, do your work, push last.',
        ja: 'pullもpushもDB全体を置き換え、後勝ちでマージはされません。日次のGitHub Actionsも同じデータセットに書き込みます。そのため、最初にpull、作業、最後にpushの順です。' },
      { en: 'Pulling while you hold un-pushed work discards that work. Pushing from a copy older than the daily runs’ latest write erases their update. The app remembers pulls and pushes made from it and warns in the confirmation; commands typed in a terminal are not tracked, so the warning only covers what was done here.',
        ja: '未pushの作業がある状態でpullすると、その作業は失われます。日次実行の最新の書き込みより古いコピーをpushすると、その更新を消してしまいます。このアプリから行ったpull/pushは記録され、確認画面で警告されます。ターミナルで実行したコマンドは記録されないため、警告の対象はここで実行した分のみです。' },
      { en: 'The “Citations only” flow is pull → resolve citations → push. The pull can be skipped only if this copy was pulled recently; the push confirmation still warns when it was not.',
        ja: '「引用の解決のみ」は pull → 引用ページの解決 → push の流れです。このコピーが最近pull済みの場合に限りpullを省略できます。そうでない場合、pushの確認画面で警告されます。' },
    ],
  },
  {
    hEn: 'NotebookLM login', hJa: 'NotebookLMのログイン',
    items: [
      { en: 'Summarising (Backfill, Resume, Summarise) and the notebook audit need a signed-in NotebookLM session. Run “Check NotebookLM login” first; if it fails, run “Sign in to NotebookLM”.',
        ja: '要約（遡及要約・再開・要約）とノートブック監査にはNotebookLMのログインが必要です。まず「NotebookLMのログイン確認」を実行し、失敗したら「NotebookLMにログイン」を実行します。' },
      { en: 'Sign in opens a browser window on this machine. Finish signing in to Google within 5 minutes; no terminal input is needed and the session is saved automatically. Other commands are blocked while it waits.',
        ja: 'ログインはこの端末でブラウザを開きます。5分以内にGoogleへのログインを完了してください。ターミナル入力は不要で、セッションは自動保存されます。待機中は他のコマンドは実行できません。' },
      { en: 'This refreshes the LOCAL session only. The daily GitHub Action uses the NOTEBOOKLM_AUTH_JSON secret, which you update separately when the cron reports a stale session.',
        ja: '更新されるのはローカルのセッションのみです。日次のGitHub Actionが使うNOTEBOOKLM_AUTH_JSONシークレットは、cronがセッション期限切れを通知したときに別途更新します。' },
    ],
  },
  {
    hEn: 'Backflow, inspect and automated', hJa: '遡及・確認・自動実行',
    items: [
      { en: 'Backflow is the back-catalogue workflow, listed in the order to run it. Optional steps can be skipped. Pick a flow at the top of the group.',
        ja: '遡及フローは過去分を処理する手順で、実行すべき順に並んでいます。任意のステップは省略できます。グループ上部でフローを選べます。' },
      { en: 'Inspect holds read-only diagnostics — start with Committee status and Diagnose fetch failures when something looks wrong.',
        ja: '確認は読み取り専用の診断です。問題があるときは「委員会の状態」と「取得失敗を診断」から始めます。' },
      { en: 'Automated lists what the daily runs already do. You normally never need these; they are there for catching up after an outage.',
        ja: '自動実行は日次実行で対応済みの処理です。通常は不要で、障害後の追い上げ用です。' },
    ],
  },
  {
    hEn: 'If something looks off', hJa: '困ったときは',
    items: [
      { en: 'The list does not load, or a new command is missing: `repower web-api` is long-running and keeps its old code — restart it after updating.',
        ja: '一覧が読み込めない、または新しいコマンドが無い場合: `repower web-api` は起動し続けるため古いコードのままです。更新後は再起動してください。' },
      { en: 'A command says another job is running: wait for the progress panel to finish, then try again.',
        ja: '別のジョブが実行中と表示される場合: 進捗パネルの完了を待ってから再度お試しください。' },
    ],
  },
]
