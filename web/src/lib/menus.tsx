import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from './app'
import type { JobRun, JobStage, Screen, WatchEntry } from './app'
import { getSnapshot, refreshSnapshots, useManifest } from './data'
import { parseDbTs } from './policyActivity'
import type { AreaKey, Level, PolicyJob } from './types'
import { Hoverable, RawSvg, s } from './style'

/**
 * Phase 4 — the working global menus (client-side, localStorage-backed):
 *   ⌘K command palette, Settings panel, Watchlist panel, plus the floating
 *   "expand" affordance shown when the sidebar is collapsed. All are mounted
 *   once (App.tsx) and driven by AppProvider's `overlay` switch, so every
 *   screen's sidebar/topbar just calls openOverlay(...) — no per-screen UI.
 */

// ---- static entity metadata (bilingual labels) ----
export const AREA_META: { key: AreaKey; en: string; ja: string }[] = [
  { key: 'hokkaido', en: 'Hokkaido', ja: '北海道' },
  { key: 'tohoku', en: 'Tohoku', ja: '東北' },
  { key: 'tepco', en: 'Tokyo', ja: '東京' },
  { key: 'chubu', en: 'Chubu', ja: '中部' },
  { key: 'hokuriku', en: 'Hokuriku', ja: '北陸' },
  { key: 'kansai', en: 'Kansai', ja: '関西' },
  { key: 'chugoku', en: 'Chugoku', ja: '中国' },
  { key: 'shikoku', en: 'Shikoku', ja: '四国' },
  { key: 'kyushu', en: 'Kyushu', ja: '九州' },
]

const SCREEN_META: { key: Screen; en: string; ja: string }[] = [
  { key: 'overview', en: 'Market Overview', ja: 'マーケット概況' },
  { key: 'market', en: 'Market Data', ja: 'マーケットデータ' },
  { key: 'capacity', en: 'Capacity & Auctions', ja: '容量・オークション' },
  { key: 'policy', en: 'Policy Deep Dive', ja: '政策ディープダイブ' },
]

interface CommitteeIx {
  key: string
  en: string
  ja: string
}

interface Cmd {
  id: string
  en: string
  ja: string
  group: string
  groupJa: string
  run: () => void
}

// ---------------------------------------------------------------------------
// Shared modal shell
// ---------------------------------------------------------------------------
const BACKDROP =
  'position:fixed;inset:0;background:rgba(13,20,32,.42);z-index:200;display:flex;flex-direction:column;align-items:center;padding:11vh 16px 16px'

function Modal({ children, onClose, top }: { children: React.ReactNode; onClose: () => void; top?: boolean }) {
  return (
    <div
      style={{ ...s(BACKDROP), justifyContent: top ? 'flex-start' : 'center' }}
      onMouseDown={onClose}
    >
      <div onMouseDown={(e) => e.stopPropagation()} style={{ display: 'contents' }}>
        {children}
      </div>
    </div>
  )
}

const PANEL =
  'width:560px;max-width:94vw;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shPop);overflow:hidden'
const CHIP =
  'font-size:10px;font-weight:600;color:var(--mut);border:1px solid var(--bd2);border-radius:6px;padding:1px 7px;flex-shrink:0'

function icon(html: string, size = 16, color = 'var(--mut)') {
  return (
    <RawSvg
      html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:${size}px;height:${size}px;color:${color};flex-shrink:0">${html}</svg>`}
    />
  )
}
const I_SEARCH = '<circle cx="11" cy="11" r="8"></circle><path d="M21 21l-4.35-4.35"></path>'
const I_STAR =
  '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon>'
const I_X = '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>'
const I_CHEV_RR = '<path d="M13 17l5-5-5-5"></path><path d="M6 17l5-5-5-5"></path>'

// ---------------------------------------------------------------------------
// ⌘K command palette
// ---------------------------------------------------------------------------
function CommandPalette() {
  const app = useApp()
  const L = app.lang
  const [q, setQ] = useState('')
  const [ix, setIx] = useState(0)
  const [committees, setCommittees] = useState<CommitteeIx[]>([])
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])
  useEffect(() => {
    let alive = true
    getSnapshot<{ committees: CommitteeIx[] }>('policy/committees.json')
      .then((d) => alive && setCommittees(d.committees || []))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  const go = (screen: Screen, area?: AreaKey) => {
    if (area) app.requestArea(area)
    app.setScreen(screen)
    app.closeOverlay()
  }

  const cmds = useMemo<Cmd[]>(() => {
    const out: Cmd[] = []
    for (const sc of SCREEN_META)
      out.push({ id: `screen:${sc.key}`, en: sc.en, ja: sc.ja, group: 'Go to', groupJa: '移動', run: () => go(sc.key) })
    for (const a of AREA_META)
      out.push({
        id: `area:${a.key}`,
        en: `${a.en} — wholesale & balancing`,
        ja: `${a.ja} — 卸・調整力`,
        group: 'Areas',
        groupJa: 'エリア',
        run: () => go('market', a.key),
      })
    out.push({
      id: 'act:settings',
      en: 'Open Settings',
      ja: '設定を開く',
      group: 'Actions',
      groupJa: '操作',
      run: () => app.openOverlay('settings'),
    })
    out.push({
      id: 'act:watchlist',
      en: 'Open Watchlist',
      ja: 'ウォッチリストを開く',
      group: 'Actions',
      groupJa: '操作',
      run: () => app.openOverlay('watchlist'),
    })
    out.push({
      id: 'act:theme',
      en: app.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme',
      ja: app.theme === 'dark' ? 'ライトテーマに切替' : 'ダークテーマに切替',
      group: 'Actions',
      groupJa: '操作',
      run: () => {
        app.toggleTheme()
        app.closeOverlay()
      },
    })
    out.push({
      id: 'act:lang',
      en: app.lang === 'ja' ? 'Switch to English' : '日本語に切替',
      ja: app.lang === 'ja' ? 'Switch to English' : '日本語に切替',
      group: 'Actions',
      groupJa: '操作',
      run: () => {
        app.setLang(app.lang === 'ja' ? 'en' : 'ja')
        app.closeOverlay()
      },
    })
    for (const c of committees) {
      out.push({
        id: `com:${c.key}`,
        en: c.en,
        ja: c.ja,
        group: 'Committees',
        groupJa: '委員会',
        run: () => go('policy'),
      })
      const fw = app.isFollowing(c.key)
      out.push({
        id: `follow:${c.key}`,
        en: (fw ? 'Unfollow: ' : 'Follow: ') + c.en,
        ja: (fw ? 'フォロー解除: ' : 'フォロー: ') + c.ja,
        group: 'Committees',
        groupJa: '委員会',
        run: () => {
          app.toggleFollow(c.key)
          app.closeOverlay()
        },
      })
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committees, app.theme, app.lang, app.followed])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return cmds
    return cmds.filter((c) =>
      (c.en + ' ' + c.ja + ' ' + c.group + ' ' + c.groupJa).toLowerCase().includes(needle),
    )
  }, [q, cmds])

  useEffect(() => {
    setIx(0)
  }, [q])

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setIx((i) => Math.min(filtered.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setIx((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      filtered[ix]?.run()
    }
  }

  return (
    <Modal onClose={app.closeOverlay} top>
      <div style={s(PANEL)}>
        <div style={s('display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--bd)')}>
          {icon(I_SEARCH, 18)}
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder={L === 'ja' ? '画面・エリア・委員会を検索…' : 'Search screens, areas, committees…'}
            style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:15px;background:transparent;color:var(--tx);min-width:0')}
          />
          <span style={s(CHIP)}>ESC</span>
        </div>
        <div style={s('max-height:52vh;overflow-y:auto;padding:6px')}>
          {filtered.length === 0 && (
            <div style={s('padding:26px;text-align:center;color:var(--mut);font-size:13px')}>
              {L === 'ja' ? '該当なし' : 'No matches'}
            </div>
          )}
          {filtered.map((c, i) => (
            <div
              key={c.id}
              onMouseMove={() => setIx(i)}
              onMouseDown={(e) => {
                e.preventDefault()
                c.run()
              }}
              style={s(
                `display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;cursor:pointer;${
                  i === ix ? 'background:var(--acTint)' : ''
                }`,
              )}
            >
              <span style={s(`width:6px;height:6px;border-radius:999px;background:${i === ix ? 'var(--ac)' : 'var(--fnt3)'};flex-shrink:0`)}></span>
              <span style={s('font-size:13.5px;color:var(--tx);font-weight:500')}>{L === 'ja' ? c.ja : c.en}</span>
              <span style={s('margin-left:auto;font-size:10.5px;color:var(--mut)')}>{L === 'ja' ? c.groupJa : c.group}</span>
            </div>
          ))}
        </div>
        <div style={s('display:flex;gap:16px;padding:9px 18px;border-top:1px solid var(--bd);font-size:11px;color:var(--mut)')}>
          <span>↑↓ {L === 'ja' ? '選択' : 'navigate'}</span>
          <span>↵ {L === 'ja' ? '開く' : 'open'}</span>
          <span>esc {L === 'ja' ? '閉じる' : 'close'}</span>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Settings panel
// ---------------------------------------------------------------------------
const seg = (on: boolean) =>
  s(
    `padding:5px 14px;border-radius:999px;font-size:12.5px;font-weight:600;cursor:pointer;${
      on ? 'background:var(--bg1);color:var(--tx);box-shadow:var(--sh1)' : 'color:var(--mut)'
    }`,
  )
const SEG_WRAP = 'display:inline-flex;background:var(--bg2);border-radius:999px;padding:3px'
const ROW = 'display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid var(--dv)'
const LABEL = 'font-size:13.5px;font-weight:600;color:var(--tx)'
const SUB = 'font-size:11.5px;color:var(--mut);margin-top:2px'

function SettingsPanel() {
  const app = useApp()
  const L = app.lang
  const { data: meta } = useManifest()

  const pick = (en: string, ja: string) => (L === 'ja' ? ja : en)

  return (
    <Modal onClose={app.closeOverlay}>
      <div style={s(PANEL)}>
        <div style={s('display:flex;align-items:center;padding:16px 20px;border-bottom:1px solid var(--bd)')}>
          <span style={s('font-size:16px;font-weight:700;color:var(--tx)')}>{pick('Settings', '設定')}</span>
          <span style={s('font-size:12px;color:var(--mut);margin-left:8px')}>· {pick('saved locally', 'ローカル保存')}</span>
          <Hoverable
            base="margin-left:auto;width:30px;height:30px;border-radius:999px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--mut)"
            hover="background:var(--bg2);color:var(--tx)"
            onClick={app.closeOverlay}
            aria-label="Close"
          >
            {icon(I_X, 16)}
          </Hoverable>
        </div>
        <div style={s('padding:6px 20px 18px')}>
          <div style={s(ROW)}>
            <div>
              <div style={s(LABEL)}>{pick('Theme', 'テーマ')}</div>
              <div style={s(SUB)}>{pick('Light or dark appearance', '外観の明暗')}</div>
            </div>
            <div style={s(SEG_WRAP)}>
              <span style={seg(app.theme === 'light')} onClick={() => app.setTheme('light')}>{pick('Light', 'ライト')}</span>
              <span style={seg(app.theme === 'dark')} onClick={() => app.setTheme('dark')}>{pick('Dark', 'ダーク')}</span>
            </div>
          </div>
          <div style={s(ROW)}>
            <div>
              <div style={s(LABEL)}>{pick('Language', '言語')}</div>
              <div style={s(SUB)}>{pick('Interface language', '表示言語')}</div>
            </div>
            <div style={s(SEG_WRAP)}>
              <span style={seg(app.lang === 'en')} onClick={() => app.setLang('en')}>English</span>
              <span style={seg(app.lang === 'ja')} onClick={() => app.setLang('ja')}>日本語</span>
            </div>
          </div>
          <div style={s(ROW)}>
            <div>
              <div style={s(LABEL)}>{pick('Default screen', '初期画面')}</div>
              <div style={s(SUB)}>{pick('Where JEMA opens on launch', '起動時に開く画面')}</div>
            </div>
            <select
              value={app.homeScreen}
              onChange={(e) => app.setHomeScreen(e.target.value as Screen)}
              style={s('font-family:inherit;font-size:13px;color:var(--tx);background:var(--bg1);border:1px solid var(--bd2);border-radius:10px;padding:7px 10px;cursor:pointer')}
            >
              {SCREEN_META.map((sc) => (
                <option key={sc.key} value={sc.key}>
                  {pick(sc.en, sc.ja)}
                </option>
              ))}
            </select>
          </div>
          <div style={s(ROW)}>
            <div>
              <div style={s(LABEL)}>{pick('Default granularity', '初期粒度')}</div>
              <div style={s(SUB)}>{pick('Aggregation Market Data opens with', 'マーケットデータの初期集計')}</div>
            </div>
            <select
              value={app.defaultGran}
              onChange={(e) => app.setDefaultGran(e.target.value as Level)}
              style={s('font-family:inherit;font-size:13px;color:var(--tx);background:var(--bg1);border:1px solid var(--bd2);border-radius:10px;padding:7px 10px;cursor:pointer')}
            >
              {(['Native', 'Daily', 'Weekly', 'Monthly'] as Level[]).map((lv) => (
                <option key={lv} value={lv}>
                  {lv}
                </option>
              ))}
            </select>
          </div>
          <div style={{ ...s(ROW), borderBottom: 'none' }}>
            <div>
              <div style={s(LABEL)}>{pick('Watchlist', 'ウォッチリスト')}</div>
              <div style={s(SUB)}>
                {app.watch.length} {pick('starred item(s)', '件を登録中')}
              </div>
            </div>
            <Hoverable
              base="font-size:12.5px;font-weight:600;color:var(--dn);border:1px solid var(--bd2);border-radius:10px;padding:7px 13px;cursor:pointer"
              hover="background:var(--dnBg)"
              onClick={app.clearWatch}
            >
              {pick('Clear all', 'すべて削除')}
            </Hoverable>
          </div>
          <div style={s('font-size:11px;color:var(--mut);margin-top:14px;line-height:1.5')}>
            {pick('Data last generated', 'データ生成')}:{' '}
            <span style={s("font-weight:600;color:var(--tx2);font-feature-settings:'tnum' 1")}>
              {meta?.generated_at ? meta.generated_at.slice(0, 16).replace('T', ' ') : '—'}
            </span>
            {' · '}
            {pick('Preferences are stored in this browser only.', '設定はこのブラウザにのみ保存されます。')}
          </div>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Guide panel — the in-app "i" user guide
// ---------------------------------------------------------------------------
// A SIMPLIFIED mirror of the "Policy Deep Dive" section of docs/USER-GUIDE.md.
// Keep the two in sync: update the doc first, then mirror the short copy here.
const I_INFO =
  '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>'
const GUIDE_PANEL =
  'width:760px;max-width:94vw;max-height:80vh;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shPop);overflow:hidden;display:flex;flex-direction:column'

interface GuideItem { en: string; ja: string }
interface GuideSection { hEn: string; hJa: string; items: GuideItem[] }

const GUIDE: GuideSection[] = [
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
      { en: 'Both Summarise buttons need `notebooklm login`.',
        ja: 'いずれの要約ボタンも `notebooklm login` が必要です。' },
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
      { en: 'The Upcoming list is empty whenever the METI calendar feed is unavailable.',
        ja: 'METIのカレンダーフィードが利用できない間、「今後の会合」は空になります。' },
      { en: 'The source site throttles bursts, so material backfill heals gradually over several runs.',
        ja: '配信元はアクセス集中を制限するため、資料の補完は複数回の実行で徐々に進みます。' },
    ],
  },
]

function GuidePanel() {
  const app = useApp()
  const L = app.lang
  const pick = (en: string, ja: string) => (L === 'ja' ? ja : en)
  return (
    <Modal onClose={app.closeOverlay} top>
      <div style={s(GUIDE_PANEL)}>
        <div style={s('display:flex;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid var(--bd);flex-shrink:0')}>
          {icon(I_INFO, 18, 'var(--ac)')}
          <span style={s('font-size:16px;font-weight:700;color:var(--tx)')}>{pick('Policy Deep Dive — Guide', '政策ディープダイブ — ガイド')}</span>
          <span style={s('font-size:12px;color:var(--mut)')}>· {pick('how it works', '使い方')}</span>
          <Hoverable
            base="margin-left:auto;width:30px;height:30px;border-radius:999px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--mut)"
            hover="background:var(--bg2);color:var(--tx)"
            onClick={app.closeOverlay}
            aria-label="Close"
          >
            {icon(I_X, 16)}
          </Hoverable>
        </div>
        <div style={s('padding:4px 20px 18px;overflow-y:auto')}>
          {GUIDE.map((sec) => (
            <div key={sec.hEn} style={s('padding:12px 0;border-bottom:1px solid var(--bd)')}>
              <div style={s('font-size:13px;font-weight:700;color:var(--tx);margin-bottom:7px')}>{pick(sec.hEn, sec.hJa)}</div>
              <div style={s('display:flex;flex-direction:column;gap:6px')}>
                {sec.items.map((it, i) => (
                  <div key={i} style={s('font-size:12.5px;color:var(--tx2);line-height:1.55')}>{pick(it.en, it.ja)}</div>
                ))}
              </div>
            </div>
          ))}
          <div style={s('font-size:11px;color:var(--mut);margin-top:14px;line-height:1.5')}>
            {pick('Full reference for developers:', '開発者向けの詳細:')}{' '}
            <span style={s('font-weight:600;color:var(--tx2)')}>docs/USER-GUIDE.md</span>
          </div>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Watchlist panel
// ---------------------------------------------------------------------------
function WatchlistPanel() {
  const app = useApp()
  const L = app.lang
  const pick = (en: string, ja: string) => (L === 'ja' ? ja : en)

  const open = (e: WatchEntry) => {
    if (e.kind === 'area') app.requestArea(e.id.replace('area:', '') as AreaKey)
    app.setScreen(e.screen)
    app.closeOverlay()
  }

  return (
    <Modal onClose={app.closeOverlay}>
      <div style={s(PANEL)}>
        <div style={s('display:flex;align-items:center;padding:16px 20px;border-bottom:1px solid var(--bd)')}>
          {icon(I_STAR, 17, 'var(--ac)')}
          <span style={s('font-size:16px;font-weight:700;color:var(--tx);margin-left:9px')}>{pick('Watchlist', 'ウォッチリスト')}</span>
          <span style={s('font-size:12px;color:var(--mut);margin-left:8px')}>· {app.watch.length}</span>
          <Hoverable
            base="margin-left:auto;width:30px;height:30px;border-radius:999px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--mut)"
            hover="background:var(--bg2);color:var(--tx)"
            onClick={app.closeOverlay}
            aria-label="Close"
          >
            {icon(I_X, 16)}
          </Hoverable>
        </div>
        <div style={s('max-height:56vh;overflow-y:auto;padding:8px')}>
          {app.watch.length === 0 && (
            <div style={s('padding:30px 20px;text-align:center;color:var(--mut);font-size:13px;line-height:1.6')}>
              {pick(
                'No starred items yet. Star an area on Market Overview or Market Data to pin it here.',
                '登録がありません。マーケット概況やデータ画面でエリアをスターすると、ここに固定されます。',
              )}
            </div>
          )}
          {app.watch.map((w) => (
            <Hoverable
              key={w.id}
              base="display:flex;align-items:center;gap:11px;padding:11px 12px;border-radius:11px;cursor:pointer"
              hover="background:var(--acTint2)"
              onClick={() => open(w)}
            >
              {icon(I_STAR, 15, 'var(--ac)')}
              <div style={{ minWidth: 0 }}>
                <div style={s('font-size:13.5px;font-weight:600;color:var(--tx)')}>{L === 'ja' ? w.ja : w.en}</div>
                <div style={s('font-size:11px;color:var(--mut)')}>
                  {w.kind === 'area' ? pick('Area', 'エリア') : pick('Committee', '委員会')}
                </div>
              </div>
              <Hoverable
                as="span"
                base="margin-left:auto;width:28px;height:28px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--mut);cursor:pointer;flex-shrink:0"
                hover="background:var(--bg2);color:var(--dn)"
                onClick={(e) => {
                  e.stopPropagation()
                  app.toggleWatch(w)
                }}
                title={pick('Remove', '削除')}
                aria-label="Remove from watchlist"
              >
                {icon(I_X, 15)}
              </Hoverable>
            </Hoverable>
          ))}
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Committees — manage the tracked set + browse the full energy catalog
// ---------------------------------------------------------------------------
const PANEL_WIDE =
  'width:1120px;max-width:96vw;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shPop);overflow:hidden'
// The status table carries nine columns; at the card width they'd all be ellipsis.
const PANEL_TABLE =
  'width:1340px;max-width:97vw;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shPop);overflow:hidden'
const VIEW_KEY = 'jema-manage-view'
const I_LIST =
  '<line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line>'
const I_STAR_O =
  '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon>'
const I_CHECK = '<polyline points="20 6 9 17 4 12"></polyline>'
const I_PLAY = '<polygon points="5 3 19 12 5 21 5 3"></polygon>'
const I_REWIND = '<polyline points="11 19 2 12 11 5"></polyline><polyline points="22 19 13 12 22 5"></polyline>'
// Archive box: a lid over a body with a pull slot.
const I_ARCHIVE =
  '<rect x="2" y="4" width="20" height="5" rx="1"></rect><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"></path><line x1="10" y1="13" x2="14" y2="13"></line>'

interface CatalogCommittee {
  key: string
  org: 'METI' | 'OCCTO' | 'EGC'
  en: string
  ja: string
  tier: string
  tracked: boolean
  /** Concluded: every fetch pass skips it. Orthogonal to `tracked`. */
  archived?: boolean
  discovered?: boolean
  priority?: number
  last: string
  url?: string
  source_count?: number
  meetings?: number
  /** Meeting-state rollup (see build_committees_payload). */
  done?: number
  pending?: number
  error?: number
  /** Fetch health — whether the committee's own pages could be reached at all. */
  fetchStatus?: string | null
  fetchKind?: string | null
  fetchDetail?: string | null
  fetchAt?: string | null
  lastOkAt?: string | null
  fetchFailures?: number
  /** Newest meeting-level pipeline event: when, which meeting, how it went. */
  lastUpdateAt?: string | null
  lastUpdateNum?: number | null
  lastUpdateState?: string | null
  lastUpdateFlag?: string | null
  lastUpdateError?: string | null
}

const ORGS: Array<'METI' | 'OCCTO' | 'EGC'> = ['METI', 'OCCTO', 'EGC']

// ---------------------------------------------------------------------------
// Manage → Status table
// ---------------------------------------------------------------------------
// The card grid answers "what do we track?". It cannot answer "what happened to
// this committee last night, and if it failed, why?" — the cards show a tier and
// a meeting number, and the per-meeting lifecycle isn't there at all. This view
// is that second question: one row per committee ordered tracked-first then most
// recently touched, expanding into its individual meetings with the raw pipeline
// state, the failure message and how long ago each was last written.
const I_CHEV_R = '<polyline points="9 18 15 12 9 6"></polyline>'
const I_CHEV_D = '<polyline points="6 9 12 15 18 9"></polyline>'
// Move-to-front-of-queue: an arrow up to a line.
const I_TO_TOP =
  '<line x1="5" y1="4" x2="19" y2="4"></line><line x1="12" y1="20" x2="12" y2="9"></line><polyline points="7 14 12 9 17 14"></polyline>'

/** One meeting's raw pipeline state (GET /api/policy/status · policy/status.json). */
interface MeetingStatus {
  com: string
  num: number
  date: string | null
  /** detected | downloading | ingesting | generating | done | error — NOT the
   *  Deep Dive's 3-way rollup; a meeting stuck mid-pipeline is visible here. */
  state: string
  flag: string | null
  error: string | null
  errorAt: string | null
  retries: number
  requested: boolean
  minutes: boolean
  tori: boolean
  docs: number
  /** How many of them the pipeline intends to ingest (excludes 委員名簿-style files). */
  docsPlanned?: number
  /** How many the last attempt actually got into NotebookLM. */
  docsIngested?: number
  genSeconds: number | null
  updatedAt: string | null
  detectedAt: string | null
}

interface StatusPayload {
  meetings: MeetingStatus[]
  /** committee_key → meetings trimmed from its list (quiet backlog only). */
  truncated?: Record<string, number>
}

const MSTATE: Record<string, { en: string; ja: string; color: string }> = {
  done: { en: 'Summarised', ja: '要約済み', color: 'var(--up)' },
  detected: { en: 'Pending', ja: '要約待ち', color: 'var(--mut)' },
  downloading: { en: 'Downloading', ja: '取得中', color: 'var(--warnTx)' },
  ingesting: { en: 'Ingesting', ja: '取込中', color: 'var(--warnTx)' },
  generating: { en: 'Generating', ja: '生成中', color: 'var(--warnTx)' },
  error: { en: 'Error', ja: 'エラー', color: 'var(--dn)' },
}
const mstate = (st?: string | null) =>
  MSTATE[st || ''] || { en: st || '—', ja: st || '—', color: 'var(--mut)' }

// `quality_flag` slugs. The first three mark a failure; the last two ride a
// *successful* meeting as a quality warning, so they must not read as errors.
const FLAG_TEXT: Record<string, [string, string]> = {
  no_sources: ['no usable source documents were found', '利用可能な資料が見つかりません'],
  download_failed: ['the source documents could not be downloaded', '資料をダウンロードできません'],
  download_blocked: ['the source site blocked the download — will be retried', '配信元にブロックされました（再試行されます）'],
  ocr_suspect: ['sources look image-only — the briefing may be thin', '画像PDFの可能性 — 要約が薄い場合があります'],
  short_output: ['the briefing came back unusually short', '要約が異常に短いです'],
}

// http_cache FETCH_KINDS, condensed from `repower policy doctor`'s remedies.
const FETCH_TEXT: Record<string, [string, string]> = {
  blocked_403: ['403 — the host refused the client', '403 — 接続を拒否されました'],
  challenge_unresolved: ['the WAF challenge never cleared — the host clears on its own; re-run later', 'WAFチャレンジ未通過 — 時間をおいて再実行'],
  circuit_open: ['collateral: another committee on this host tripped the breaker', '波及：同一ホストの別委員会の失敗によるもの'],
  deadline_exceeded: ['the per-call time budget ran out', '時間予算切れ'],
  not_found: ['404 — the page moved or was retired; fix the URL or archive it', '404 — ページ移転／終了。URL修正かアーカイブを'],
  server_error: ['5xx/429 from the host — usually temporary', 'サーバエラー（5xx/429）— 通常は一時的'],
  network_error: ['DNS/TLS/connection failure', 'DNS/TLS/接続の失敗'],
  unexpected_status: ['an HTTP status this layer does not handle', '未対応のHTTPステータス'],
  parse_error: ['fetched fine but unparseable — the page layout likely changed', '取得はできたが解析不可 — ページ構成の変更'],
}

/** Timestamp for ordering; unparseable/absent sorts last (never first). */
const tsOf = (v?: string | null): number => {
  const t = parseDbTs(v)
  return Number.isNaN(t) ? 0 : t
}
/** "3h ago", with the raw stamp kept for the tooltip. */
const ago = (v: string | null | undefined, ja: boolean): string => {
  const t = tsOf(v)
  return t ? relTime(t, ja) : '—'
}

// Committee row / meeting sub-row column tracks, shared by header and body so
// the two can't drift.
const T_COLS = '20px minmax(190px,1.8fr) 108px 84px 78px 104px 112px 92px 108px'
const M_COLS = '62px 88px 104px 62px minmax(150px,1fr) 66px 58px'
const TH =
  "font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);white-space:nowrap;overflow:hidden;font-feature-settings:'tnum' 1"
const TD = "font-size:11.5px;color:var(--tx2);min-width:0;font-feature-settings:'tnum' 1"

function StateChip({ state, lang }: { state: string; lang: string }) {
  const m = mstate(state)
  return (
    <span style={s('display:inline-flex;align-items:center;gap:5px;min-width:0')}>
      <span style={s(`width:7px;height:7px;border-radius:999px;flex-shrink:0;background:${m.color}`)}></span>
      <span style={s(`font-size:11.5px;font-weight:600;color:${m.color};white-space:nowrap;overflow:hidden;text-overflow:ellipsis`)}>
        {lang === 'ja' ? m.ja : m.en}
      </span>
    </span>
  )
}

/** Expanded committee → its individual meetings, newest activity first. */
function MeetingRows({
  meetings,
  trimmed,
  lang,
  committee,
  interactive,
  running,
  onRunMeeting,
  onQueueMeeting,
}: {
  meetings: MeetingStatus[]
  trimmed: number
  lang: string
  committee: string
  interactive: boolean
  running: boolean
  onRunMeeting: (key: string, num: number) => void
  onQueueMeeting: (key: string, num: number, queued: boolean) => void
}) {
  const L = lang
  const pick = (en: string, ja: string) => (L === 'ja' ? ja : en)
  if (!meetings.length) {
    return (
      <div style={s('padding:9px 12px 11px 34px;font-size:11.5px;color:var(--mut)')}>
        {pick('No meetings recorded yet — run “Check for updates” to detect them.',
              '会合の記録がありません — 「更新を確認」で検出してください')}
      </div>
    )
  }
  return (
    <div style={s('padding:4px 12px 9px 34px;background:var(--bg0)')}>
      <div style={s(`display:grid;grid-template-columns:${M_COLS};gap:8px;padding:4px 6px`)}>
        {[
          pick('MEETING', '会合'),
          pick('DATE', '開催日'),
          pick('STATE', '状態'),
          pick('DOCS IN', '取込資料'),
          pick('DETAIL / ERROR', '詳細・エラー'),
          pick('UPDATED', '更新'),
          '',
        ].map((h, i) => (
          <span key={h || `sp${i}`} style={s(TH)}>{h}</span>
        ))}
      </div>
      {meetings.map((m) => {
        const flag = m.flag ? FLAG_TEXT[m.flag] : null
        // Prefer the recorded message; fall back to the slug's canned text, then
        // to a bare "errored" so an old row (logged before last_error existed)
        // still reads as a failure rather than as blank.
        const detail =
          m.error ||
          (flag ? (L === 'ja' ? flag[1] : flag[0]) : null) ||
          (m.state === 'error' ? pick('failed — no reason recorded', '失敗（理由の記録なし）') : '')
        const isErr = m.state === 'error'
        const warn = !isErr && !!m.flag
        return (
          <div
            key={m.num}
            style={s(`display:grid;grid-template-columns:${M_COLS};gap:8px;align-items:center;padding:5px 6px;border-top:1px solid var(--dv)`)}
          >
            <span style={s('font-size:11.5px;font-weight:600;color:var(--tx)')}>第{m.num}回</span>
            <span style={s(TD)} title={m.date ? '' : pick('Meeting date not backfilled yet', '開催日は未取得')}>
              {m.date || '—'}
            </span>
            <StateChip state={m.state} lang={L} />
            {(() => {
              // A summarised meeting whose notebook saw fewer documents than the
              // page lists is the failure this column exists for — the briefing
              // reads complete and isn't.
              const got = m.docsIngested ?? 0
              // Denominator is what the pipeline *meant* to ingest, not every PDF on
              // the page — a meeting listing a 委員名簿 would otherwise read as short
              // when it was complete.
              const want = m.docsPlanned ?? m.docs
              const short = m.state === 'done' && want > 0 && got < want
              return (
                <span
                  style={s(`${TD}${short ? ';color:var(--warnTx);font-weight:600' : ''}`)}
                  title={
                    m.state === 'done'
                      ? pick(
                          `${got} of ${want} ingestable document(s) reached NotebookLM` +
                            (m.docs > want ? ` (${m.docs} on the page)` : '') +
                            (short ? ' — this briefing did not see them all; re-run it' : ''),
                          `取込対象${want}件中${got}件をNotebookLMに取込` +
                            (m.docs > want ? `（ページ上は${m.docs}件）` : '') +
                            (short ? ' — 全資料を参照していません。再実行を推奨' : ''),
                        )
                      : pick(`${m.docs} source document(s) detected`, `資料 ${m.docs}件を検出`)
                  }
                >
                  {m.state === 'done' ? `${got}/${want}` : m.docs}
                  {m.tori ? ' ◆' : ''}
                </span>
              )
            })()}
            <span
              style={s(`font-size:11px;color:${isErr ? 'var(--dn)' : warn ? 'var(--warnTx)' : 'var(--mut)'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis`)}
              title={detail + (m.retries ? pick(` · ${m.retries} retries`, ` · 再試行 ${m.retries}回`) : '')}
            >
              {detail || (m.requested ? pick('queued by request', 'リクエスト済み') : '—')}
              {m.retries ? ` (${m.retries}×)` : ''}
            </span>
            <span style={s(TD)} title={m.updatedAt || ''}>{ago(m.updatedAt, L === 'ja')}</span>
            <span style={s('display:flex;align-items:center;gap:4px')}>
              {interactive && (
                <>
                  <Hoverable
                    as="span"
                    base={`display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;flex-shrink:0;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--warnTx)'};cursor:${running ? 'default' : 'pointer'}`}
                    hover={running ? '' : 'border-color:var(--warnTx);background:var(--warnBg)'}
                    onClick={() => !running && onRunMeeting(committee, m.num)}
                    title={
                      m.state === 'done'
                        ? pick(
                            'Re-summarise this meeting now — replaces the existing briefing and re-folds it into the synthesis',
                            'この会合を再要約 — 既存の要約を置き換え、総括にも反映します',
                          )
                        : pick('Summarise this meeting now — nothing else', 'この会合のみを今すぐ要約')
                    }
                    aria-label="Summarise this meeting now"
                  >
                    {icon(I_PLAY, 10, 'currentColor')}
                  </Hoverable>
                  <Hoverable
                    as="span"
                    base={`display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;flex-shrink:0;cursor:pointer;${
                      m.requested
                        ? 'border:1px solid var(--ac);background:var(--acTint);color:var(--acT)'
                        : 'border:1px solid var(--bd2);color:var(--mut)'
                    }`}
                    hover={m.requested ? 'background:var(--bg1)' : 'border-color:var(--ac);color:var(--acT)'}
                    onClick={() => onQueueMeeting(committee, m.num, !m.requested)}
                    title={
                      m.requested
                        ? pick('Queued first — click to take it off the front', '最優先キュー中 — クリックで解除')
                        : pick('Move to the front of the queue — the next run takes it first', 'キューの先頭へ — 次回の要約で最初に処理')
                    }
                    aria-label={m.requested ? 'Remove from the front of the queue' : 'Move to the front of the queue'}
                  >
                    {icon(I_TO_TOP, 10, 'currentColor')}
                  </Hoverable>
                </>
              )}
              {!interactive && m.requested && (
                <span style={s('font-size:10px;font-weight:600;color:var(--acT)')} title={pick('Queued first', '最優先キュー中')}>
                  {pick('QUEUED', 'キュー')}
                </span>
              )}
            </span>
          </div>
        )
      })}
      {trimmed > 0 && (
        <div style={s('padding:6px 6px 0;font-size:10.5px;color:var(--mut);border-top:1px solid var(--dv)')}>
          {pick(`+${trimmed} older pending meeting(s) not shown`, `他 ${trimmed}件の要約待ち会合は非表示`)}
        </div>
      )}
    </div>
  )
}

function StatusTable({
  rows,
  status,
  statusLoading,
  interactive,
  running,
  onTrack,
  onArchive,
  onPriority,
  onRun,
  onRunLatest,
  onBackfill,
  onRunMeeting,
  onQueueMeeting,
}: {
  rows: CatalogCommittee[]
  status: StatusPayload | null
  statusLoading: boolean
  interactive: boolean
  running: boolean
  onTrack: (key: string, enabled: boolean) => void
  onArchive: (key: string, archived: boolean) => void
  onPriority: (key: string, raw: string, prev: number) => void
  onRun: (c: CatalogCommittee) => void
  onRunLatest: (c: CatalogCommittee) => void
  onBackfill: (c: CatalogCommittee) => void
  onRunMeeting: (key: string, num: number) => void
  onQueueMeeting: (key: string, num: number, queued: boolean) => void
}) {
  const app = useApp()
  const L = app.lang
  const dark = app.theme === 'dark'
  const pick = (en: string, ja: string) => (L === 'ja' ? ja : en)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const orgColor = (org: string) =>
    org === 'OCCTO' ? (dark ? '#7C9CD1' : '#4A6FA5') : org === 'EGC' ? (dark ? '#C77BD8' : '#7B2D8E') : 'var(--ac)'

  // Meetings grouped per committee, each already newest-activity-first from the
  // backend. Built once per payload rather than per expanded row.
  const byCom = useMemo(() => {
    const out: Record<string, MeetingStatus[]> = {}
    for (const m of status?.meetings || []) (out[m.com] ||= []).push(m)
    return out
  }, [status])

  if (!rows.length) {
    return <div style={s('padding:26px;text-align:center;color:var(--mut);font-size:13px')}>{pick('No matches', '該当なし')}</div>
  }

  return (
    <div style={s('min-width:900px')}>
      <div
        style={s(
          `display:grid;grid-template-columns:${T_COLS};gap:8px;align-items:center;padding:6px 10px;position:sticky;top:0;z-index:2;background:var(--bg1);border-bottom:1px solid var(--bd)`,
        )}
      >
        <span></span>
        {(
          [
            [pick('COMMITTEE', '委員会'), ''],
            [pick('LAST UPDATE', '最終更新'), pick('The newest meeting the pipeline touched, and how it went', '直近に処理した会合とその結果')],
            [pick('WHEN', '経過'), pick('How long ago that was', 'その処理からの経過時間')],
            // NOT "latest meeting": `latest_meeting` is the highest number that
            // reached `done`, so a committee whose newest meetings all failed
            // shows an older number here — or none at all.
            [pick('SUMMARISED TO', '要約済み'), pick('Highest meeting number that reached “done”', '要約が完了した最新の会合番号')],
            [pick('DONE / PEND / ERR', '完了・待ち・失敗'), pick('Meetings summarised / awaiting summary / errored', '要約済み・要約待ち・失敗した会合数')],
            [pick('FETCH', '取得'), pick('Whether the committee’s own pages could be reached on the last pass', '前回パスで委員会ページを取得できたか')],
            [pick('TRACK', '追跡'), pick('Tracked committees are summarised, lowest queue number first', '追跡中の委員会を#の小さい順に要約')],
            [pick('ACTIONS', '操作'), ''],
          ] as const
        ).map(([h, tip]) => (
          <span key={h} style={s(TH)} title={tip}>{h}</span>
        ))}
      </div>

      {rows.map((c) => {
        const expanded = !!open[c.key]
        const meetings = byCom[c.key] || []
        const trimmed = status?.truncated?.[c.key] || 0
        const fetchErr = c.fetchStatus === 'error'
        const fk = c.fetchKind ? FETCH_TEXT[c.fetchKind] : null
        const fetchTip = [
          c.fetchKind || c.fetchStatus || pick('never fetched', '未取得'),
          fk ? (L === 'ja' ? fk[1] : fk[0]) : null,
          c.fetchDetail,
          c.fetchAt ? pick(`last try ${c.fetchAt}`, `最終試行 ${c.fetchAt}`) : null,
          c.lastOkAt
            ? pick(`last success ${c.lastOkAt}`, `最終成功 ${c.lastOkAt}`)
            : pick('never fetched successfully', '成功した取得なし'),
          c.fetchFailures ? pick(`${c.fetchFailures} consecutive failures`, `連続失敗 ${c.fetchFailures}回`) : null,
        ]
          .filter(Boolean)
          .join('\n')
        // What the pipeline last did here: the newest meeting event, or — when a
        // committee has no meetings at all — why it has none (a dead fetch is the
        // usual answer, and saying "no meetings" alone would hide that).
        const lastErr = c.lastUpdateError || (c.lastUpdateFlag ? (FLAG_TEXT[c.lastUpdateFlag] || [])[L === 'ja' ? 1 : 0] : null)
        return (
          <div key={c.key} style={s('border-bottom:1px solid var(--dv)')}>
            <Hoverable
              base={`display:grid;grid-template-columns:${T_COLS};gap:8px;align-items:center;padding:7px 10px;cursor:pointer`}
              hover="background:var(--bg2)"
              onClick={() => setOpen((o) => ({ ...o, [c.key]: !o[c.key] }))}
              aria-expanded={expanded}
              title={pick('Click to show this committee’s individual meetings', 'クリックで会合ごとの状態を表示')}
            >
              <span style={s('display:flex;color:var(--mut)')}>{icon(expanded ? I_CHEV_D : I_CHEV_R, 13, 'currentColor')}</span>

              <div style={s('min-width:0')}>
                <div style={s('display:flex;align-items:center;gap:6px;min-width:0')}>
                  <span style={s(`width:7px;height:7px;border-radius:999px;flex-shrink:0;background:${orgColor(c.org)}`)}></span>
                  <span style={s('font-size:12.5px;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>
                    {L === 'ja' ? c.ja : c.en}
                  </span>
                  {c.archived && (
                    <span style={s('font-size:9px;font-weight:700;color:var(--warnTx);background:var(--warnBg);border-radius:5px;padding:0 5px;flex-shrink:0')}>
                      {pick('ARCHIVED', 'アーカイブ')}
                    </span>
                  )}
                </div>
                <div style={s('font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>
                  {c.key} · {c.org}
                </div>
              </div>

              <div style={s('min-width:0')}>
                {c.lastUpdateAt ? (
                  <>
                    <StateChip state={c.lastUpdateState || ''} lang={L} />
                    <div style={s('font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}
                         title={lastErr || ''}>
                      {c.lastUpdateNum ? `第${c.lastUpdateNum}回` : ''}
                      {lastErr ? ` · ${lastErr}` : ''}
                    </div>
                  </>
                ) : (
                  <span style={s('font-size:11.5px;color:var(--mut)')}>{pick('never run', '実行なし')}</span>
                )}
              </div>

              <span style={s(TD)} title={c.lastUpdateAt || pick('no meeting has been processed yet', 'まだ処理された会合はありません')}>
                {ago(c.lastUpdateAt, L === 'ja')}
              </span>

              <span style={s(TD)}>{c.last || '—'}</span>

              <span style={s(TD)} title={pick(
                `${c.done || 0} summarised · ${c.pending || 0} pending · ${c.error || 0} errored`,
                `要約済み ${c.done || 0} · 要約待ち ${c.pending || 0} · 失敗 ${c.error || 0}`,
              )}>
                <span style={s('color:var(--up);font-weight:600')}>{c.done || 0}</span>
                <span style={s('color:var(--fnt3)')}> / </span>
                <span>{c.pending || 0}</span>
                <span style={s('color:var(--fnt3)')}> / </span>
                <span style={s(`font-weight:600;color:${c.error ? 'var(--dn)' : 'var(--mut)'}`)}>{c.error || 0}</span>
              </span>

              <span
                style={s(
                  `font-size:10.5px;font-weight:600;border-radius:999px;padding:2px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;justify-self:start;max-width:100%;${
                    fetchErr
                      ? 'background:var(--dnBg);color:var(--dn)'
                      : c.fetchStatus
                        ? 'background:var(--upBg);color:var(--up)'
                        : 'border:1px solid var(--bd2);color:var(--mut)'
                  }`,
                )}
                title={fetchTip}
              >
                {fetchErr
                  ? `${c.fetchKind || 'error'}${c.fetchFailures ? ` ×${c.fetchFailures}` : ''}`
                  : c.fetchStatus || pick('none', '未取得')}
              </span>

              <span
                style={s('display:flex;align-items:center;gap:5px;min-width:0')}
                onClick={(e) => e.stopPropagation()}
              >
                {interactive ? (
                  <Hoverable
                    as="span"
                    base={`font-size:10.5px;font-weight:600;border-radius:999px;padding:2px 9px;cursor:pointer;white-space:nowrap;${
                      c.tracked ? 'background:var(--acBadge);color:#FFFFFF' : 'border:1px solid var(--bd2);color:var(--acT)'
                    }`}
                    hover={c.tracked ? 'background:var(--dn)' : 'border-color:var(--ac);background:var(--acTint)'}
                    onClick={() => onTrack(c.key, !c.tracked)}
                    title={c.tracked ? pick('Click to untrack', 'クリックで追跡解除') : pick('Click to track', 'クリックで追跡')}
                  >
                    {c.tracked ? pick('ON', '追跡') : pick('OFF', '未追跡')}
                  </Hoverable>
                ) : (
                  <span style={s(`font-size:10.5px;font-weight:600;color:${c.tracked ? 'var(--up)' : 'var(--mut)'}`)}>
                    {c.tracked ? pick('ON', '追跡') : pick('OFF', '未追跡')}
                  </span>
                )}
                {c.tracked &&
                  (interactive ? (
                    <input
                      type="number"
                      min={1}
                      defaultValue={c.priority ?? 100}
                      onBlur={(e) => onPriority(c.key, e.currentTarget.value, c.priority ?? 100)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur()
                      }}
                      title={pick('Queue priority — lower is summarised first', 'キュー優先度 — 小さいほど先に処理')}
                      style={s("width:40px;font-family:inherit;font-size:11px;font-weight:600;text-align:center;color:var(--tx);background:var(--bg0);border:1px solid var(--bd2);border-radius:7px;padding:2px 3px;font-feature-settings:'tnum' 1")}
                    />
                  ) : (
                    <span style={s("font-size:10.5px;color:var(--mut);font-feature-settings:'tnum' 1")}>#{c.priority ?? 100}</span>
                  ))}
              </span>

              <span style={s('display:flex;align-items:center;gap:4px')} onClick={(e) => e.stopPropagation()}>
                {interactive && c.tracked && (
                  <>
                    <Hoverable
                      as="span"
                      base={`display:inline-flex;align-items:center;justify-content:center;height:22px;padding:0 8px;border-radius:999px;flex-shrink:0;font-size:10.5px;font-weight:700;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--warnTx)'};cursor:${running ? 'default' : 'pointer'}`}
                      hover={running ? '' : 'border-color:var(--warnTx);background:var(--warnBg)'}
                      onClick={() => !running && onRunLatest(c)}
                      title={pick(
                        'Summarise the newest pending meeting only — one meeting, then stop',
                        '最新の未要約会合のみを要約 — 1件で終了',
                      )}
                      aria-label="Summarise the latest pending meeting only"
                    >
                      {pick('LATEST', '最新')}
                    </Hoverable>
                    <Hoverable
                      as="span"
                      base={`display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;flex-shrink:0;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--warnTx)'};cursor:${running ? 'default' : 'pointer'}`}
                      hover={running ? '' : 'border-color:var(--warnTx);background:var(--warnBg)'}
                      onClick={() => !running && onRun(c)}
                      title={pick('Summarise pending meetings — needs notebooklm login', '未要約の会合を要約 — notebooklm loginが必要')}
                      aria-label="Summarise pending meetings"
                    >
                      {icon(I_PLAY, 11, 'currentColor')}
                    </Hoverable>
                    <Hoverable
                      as="span"
                      base={`display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;flex-shrink:0;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--acT)'};cursor:${running ? 'default' : 'pointer'}`}
                      hover={running ? '' : 'border-color:var(--ac);background:var(--acTint)'}
                      onClick={() => !running && onBackfill(c)}
                      title={pick('Backfill older meetings, then summarise', '過去の会合を取得して要約')}
                      aria-label="Backfill older meetings"
                    >
                      {icon(I_REWIND, 11, 'currentColor')}
                    </Hoverable>
                  </>
                )}
                {interactive && (
                  <Hoverable
                    as="span"
                    base={`display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;flex-shrink:0;cursor:pointer;${
                      c.archived
                        ? 'border:1px solid var(--warnTx);background:var(--warnBg);color:var(--warnTx)'
                        : 'border:1px solid var(--bd2);color:var(--mut)'
                    }`}
                    hover={c.archived ? 'background:var(--bg1)' : 'border-color:var(--warnTx);color:var(--warnTx)'}
                    onClick={() => onArchive(c.key, !c.archived)}
                    title={
                      c.archived
                        ? pick('Archived — every fetch pass skips it. Click to resume fetching.', 'アーカイブ済み — 取得対象外。クリックで再開')
                        : pick('Archive: stop fetching this concluded committee.', 'アーカイブ：終了した委員会の取得を停止')
                    }
                    aria-label={c.archived ? 'Un-archive committee' : 'Archive committee'}
                  >
                    {icon(I_ARCHIVE, 11, 'currentColor')}
                  </Hoverable>
                )}
              </span>
            </Hoverable>

            {expanded &&
              (statusLoading && !meetings.length ? (
                <div style={s('padding:9px 12px 11px 34px;font-size:11.5px;color:var(--mut)')}>{pick('Loading…', '読み込み中…')}</div>
              ) : (
                <MeetingRows
                  meetings={meetings}
                  trimmed={trimmed}
                  lang={L}
                  committee={c.key}
                  interactive={interactive}
                  running={running}
                  onRunMeeting={onRunMeeting}
                  onQueueMeeting={onQueueMeeting}
                />
              ))}
          </div>
        )
      })}
    </div>
  )
}

function CommitteesManage() {
  const app = useApp()
  const L = app.lang
  const dark = app.theme === 'dark'
  const pick = (en: string, ja: string) => (L === 'ja' ? ja : en)
  const [rows, setRows] = useState<CatalogCommittee[]>([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState<Record<string, boolean>>({})
  const [adding, setAdding] = useState(false)
  // Cards (manage the tracked set) vs Status table (what the pipeline did, and
  // what broke). Remembered per browser: whichever one you work in is the one
  // you keep coming back to.
  const [view, setView] = useState<'cards' | 'table'>(() => {
    try {
      return localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'cards'
    } catch {
      return 'cards'
    }
  })
  const [scope, setScope] = useState<'all' | 'tracked' | 'failing'>('all')
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)

  // Load the catalog: the live DB (interactive) or the static snapshot (read-only).
  // Reused after a job finishes (Check for updates / catch-up, or a Summarise run),
  // since discovery can add or change rows (the energy-board backup accumulates
  // newly-found committees as discovered).
  const loadCatalog = () => {
    const p = app.interactive
      ? fetch('/api/policy/catalog').then((r) => r.json())
      : getSnapshot<{ committees: CatalogCommittee[] }>('policy/committees.json')
    return p.then((d) => setRows(d.committees || [])).catch(() => {})
  }

  // Per-meeting pipeline status. Only the table view needs it, so it is fetched
  // on first switch rather than on open — the payload is every committee's recent
  // meetings, which the card grid would never show.
  const loadStatus = () => {
    setStatusLoading(true)
    const p = app.interactive
      ? fetch('/api/policy/status').then((r) => r.json())
      : getSnapshot<StatusPayload>('policy/status.json')
    return p
      .then((d: StatusPayload) => setStatus({ meetings: d.meetings || [], truncated: d.truncated || {} }))
      .catch(() => setStatus({ meetings: [], truncated: {} }))
      .finally(() => setStatusLoading(false))
  }

  useEffect(() => {
    let alive = true
    setLoading(true)
    // The status payload comes from a different source per mode (live API vs
    // static snapshot), so drop it when the mode flips and let the effect below
    // refetch from the right one.
    setStatus(null)
    loadCatalog().finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.interactive])

  useEffect(() => {
    if (view === 'table' && !status && !statusLoading) loadStatus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, app.interactive])

  const orgColor = (org: string) =>
    org === 'OCCTO' ? (dark ? '#7C9CD1' : '#4A6FA5') : org === 'EGC' ? (dark ? '#C77BD8' : '#7B2D8E') : 'var(--ac)'

  const setTracked = (key: string, enabled: boolean) => {
    if (!app.interactive || busy[key]) return
    setBusy((b) => ({ ...b, [key]: true }))
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, tracked: enabled } : r))) // optimistic
    fetch('/api/policy/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, enabled }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('http'))))
      .then(() => {
        app.toast(
          enabled
            ? pick('Now tracking — included in the next catch-up', '追跡開始 — 次回の差分取得に含まれます')
            : pick('Untracked — skipped by the catch-up', '追跡解除 — 差分取得の対象外'),
        )
        // The Policy Deep Dive screen behind this modal shows only tracked
        // committees — refetch so a track/untrack here is reflected there too.
        refreshSnapshots()
      })
      .catch(() => {
        setRows((rs) => rs.map((r) => (r.key === key ? { ...r, tracked: !enabled } : r))) // revert
        app.toast(pick('Could not update tracking', '追跡を更新できませんでした'))
      })
      .finally(() => setBusy((b) => ({ ...b, [key]: false })))
  }

  // Archiving is a *fetch* exclusion: detection and both backfills stop crawling a
  // concluded committee's index. Separate from tracking, which gates summarisation
  // only — untracking never stops detection.
  const setArchived = (key: string, archived: boolean) => {
    if (!app.interactive || busy[key]) return
    setBusy((b) => ({ ...b, [key]: true }))
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, archived } : r))) // optimistic
    fetch('/api/policy/archive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, archived }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('http'))))
      .then(() => {
        app.toast(
          archived
            ? pick('Archived — skipped by every fetch pass', 'アーカイブ済み — 取得対象外')
            : pick('Un-archived — fetched again from the next run', 'アーカイブ解除 — 次回から取得再開'),
        )
      })
      .catch(() => {
        setRows((rs) => rs.map((r) => (r.key === key ? { ...r, archived: !archived } : r))) // revert
        app.toast(pick('Could not update archive state', 'アーカイブ状態を更新できませんでした'))
      })
      .finally(() => setBusy((b) => ({ ...b, [key]: false })))
  }

  // Manual add-by-URL: the escape hatch for committees the org indexes never list
  // (e.g. WGs nested under a 小委員会). Shown when the search text is a METI
  // /shingikai/ committee URL; the backend fetches the page name and auto-tracks.
  const urlToAdd = /^https?:\/\/www\.meti\.go\.jp\/shingikai\/[a-z0-9_/]+\/?(?:index\.html)?$/i.test(q.trim())
    ? q.trim()
    : null
  const addByUrl = () => {
    if (!app.interactive || adding || !urlToAdd) return
    setAdding(true)
    fetch('/api/policy/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: urlToAdd }),
    })
      .then(async (r) => {
        const j = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error((j && j.error) || 'http')
        app.toast(
          j.existing
            ? pick('Already in the catalog — see its row below', '既にカタログにあります — 下の行をご確認ください')
            : pick('Added & tracking — included in the next catch-up', '追加して追跡開始 — 次回の差分取得に含まれます'),
        )
        setQ(j.key || '')
        // A newly-added committee is auto-tracked, so refetch the Policy Deep
        // Dive screen behind the modal to surface it in the tracked list.
        refreshSnapshots()
        return loadCatalog()
      })
      .catch(() => app.toast(pick('Could not add committee', '委員会を追加できませんでした')))
      .finally(() => setAdding(false))
  }

  // Edit the catch-up queue position (lower = summarised first). Persisted to the
  // DB, so it survives sync — the way to make a committee jump the queue for good.
  const setPriority = (key: string, raw: string, prev: number) => {
    if (!app.interactive) return
    const p = parseInt(raw, 10)
    if (!Number.isFinite(p) || p < 1 || p === prev) return
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, priority: p } : r)))
    fetch('/api/policy/priority', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, priority: p }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('http'))))
      .then(() => app.toast(pick(`Priority ${p} — lower runs first`, `優先度 ${p} — 小さいほど先に処理`)))
      .catch(() => {
        setRows((rs) => rs.map((r) => (r.key === key ? { ...r, priority: prev } : r))) // revert
        app.toast(pick('Could not set priority', '優先度を更新できませんでした'))
      })
  }

  // ---- policy CLI jobs (local master only): run the same commands as the cron/skill ----
  const [job, setJob] = useState<PolicyJob | null>(null)
  const jobTimer = useRef<number | null>(null)
  // Catch-up ("Check for updates") runs through the global progress panel rather
  // than the modal-local `job` poller, so it needs its own in-flight flag.
  const [checking, setChecking] = useState(false)

  const pollJob = () => {
    fetch('/api/policy/job')
      .then((r) => r.json())
      .then((j: PolicyJob) => {
        setJob(j)
        if (j && j.state === 'running') {
          jobTimer.current = window.setTimeout(pollJob, 1500)
        } else {
          // Job finished: refresh the catalog so any rows it added/changed show up
          // (crosscheck/discover add discovered committees; detect updates latest)
          // — and the per-meeting status, which is what the job just rewrote.
          loadCatalog()
          if (view === 'table') loadStatus()
          // …and refetch the Policy Deep Dive screen behind this modal: the same
          // job wrote new meetings/dates/summaries to the DB that the screen's
          // usePolicyLive must pick up (it subscribes to this refresh signal).
          refreshSnapshots()
        }
      })
      .catch(() => {})
  }

  const postJob = (cmd: string, params: Record<string, unknown> = {}, label?: string) => {
    if (!app.interactive) return
    fetch('/api/policy/job', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cmd, ...params }),
    })
      .then(async (r) => {
        // 202 bodies are the job snapshot; 400/409 bodies only carry `error`.
        const j = (await r.json().catch(() => null)) as PolicyJob | null
        if (r.status === 202) {
          if (j) setJob(j)
          if (jobTimer.current) window.clearTimeout(jobTimer.current)
          jobTimer.current = window.setTimeout(pollJob, 1200)
          app.toast(pick(`Started: ${label || cmd}`, `実行開始: ${label || cmd}`))
        } else if (r.status === 409) {
          app.toast(pick('A job is already running — wait for it to finish', '実行中のジョブがあります。完了までお待ちください'))
        } else {
          app.toast(j && j.error ? j.error : pick('Could not start job', 'ジョブを開始できませんでした'))
        }
      })
      .catch(() => app.toast(pick('Could not start job', 'ジョブを開始できませんでした')))
  }

  // Summarise exactly one meeting. `policy run --meeting N` bypasses the pending
  // queue, so this also re-runs an already-summarised meeting — the repair path
  // for a briefing written from an incomplete source set.
  const runMeeting = (key: string, num: number) =>
    postJob('run', { committee: key, meeting: num }, `run ${key} 第${num}回`)

  // Newest pending meeting of one committee, then stop. No meeting number needed:
  // a single-committee run is depth-first (newest first), so a budget of 1 is
  // exactly "the latest one".
  const runLatest = (c: CatalogCommittee) =>
    postJob('run', { committee: c.key, max_per_run: 1 }, `run ${c.key} (latest)`)

  // Move a meeting to the front of the summarisation queue. Ordering only — it
  // changes nothing about what gets summarised, so unlike the job actions it stays
  // available while a job is running.
  const queueMeeting = (key: string, num: number, queued: boolean) => {
    if (!app.interactive) return
    fetch('/api/policy/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, meeting_num: num, queued }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('http'))))
      .then(() => {
        app.toast(
          queued
            ? pick(`第${num}回 queued — the next run takes it first`, `第${num}回 をキュー先頭に追加 — 次回の要約で最初に処理`)
            : pick(`第${num}回 removed from the front of the queue`, `第${num}回 をキュー先頭から解除`),
        )
        loadStatus()
      })
      .catch(() => app.toast(pick('Could not update the queue', 'キューを更新できませんでした')))
  }

  const backfill = (c: CatalogCommittee) => {
    const nm = L === 'ja' ? c.ja : c.en
    const raw = window.prompt(
      pick(`Backfill "${nm}" — earliest meeting number to summarise:`, `「${nm}」の要約開始回（最古の会合番号）:`),
      '',
    )
    if (raw == null) return
    const n = parseInt(raw, 10)
    if (!Number.isFinite(n) || n < 1) {
      app.toast(pick('Enter a meeting number', '会合番号を入力してください'))
      return
    }
    postJob('backfill', { committee: c.key, since_meeting: n }, `backfill ${c.key} ≥#${n}`)
  }

  // Surface an in-flight job (e.g. started before the modal opened) + clean up.
  useEffect(() => {
    if (!app.interactive) return
    fetch('/api/policy/job')
      .then((r) => r.json())
      .then((j: PolicyJob) => {
        if (j && j.state && j.state !== 'idle') {
          setJob(j)
          if (j.state === 'running') jobTimer.current = window.setTimeout(pollJob, 1200)
        }
      })
      .catch(() => {})
    return () => {
      if (jobTimer.current) window.clearTimeout(jobTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.interactive])

  const running = !!job && job.state === 'running'
  // Command jobs (Summarise/backfill) are polled locally via `job`; catch-up runs
  // through the global tracker (`checking`). Either one busies every action button.
  const actionBusy = running || checking

  // "Check for updates" — the single consolidated discovery pathway. Kicks the
  // in-process catch-up (detect new meetings → backfill dates → refresh schedule →
  // discover new committees across every source) and hands it to the global
  // progress panel; refreshes this modal's catalog when it finishes.
  const checkForUpdates = () => {
    if (!app.interactive || actionBusy) return
    setChecking(true)
    fetch('/api/policy/catchup', { method: 'POST' })
      .then(() => {
        app.trackJob({
          kind: 'catchup',
          title: 'Catch-up',
          titleJa: '差分取得',
          endpoint: '/api/policy/catchup',
          onDone: () => {
            setChecking(false)
            loadCatalog()
            if (view === 'table') loadStatus()
          },
        })
        app.toast(pick('Checking for updates…', '更新を確認中…'))
      })
      .catch(() => {
        setChecking(false)
        app.toast(pick('Could not start catch-up', '差分取得を開始できませんでした'))
      })
  }

  const needle = q.trim().toLowerCase()
  const match = (c: CatalogCommittee) =>
    !needle || (c.en + ' ' + c.ja + ' ' + c.key).toLowerCase().includes(needle)

  // "Failing" spans both ways a committee can be broken, which are independent:
  // its pages can't be fetched, or its meetings can't be summarised. Filtering on
  // either alone would quietly hide half the problems.
  const failing = (c: CatalogCommittee) =>
    c.fetchStatus === 'error' || (c.error || 0) > 0 || c.lastUpdateState === 'error'
  const nTracked = rows.filter((c) => c.tracked).length
  const nFailing = rows.filter(failing).length

  // Tracked first, then most recently touched by the pipeline (never-run rows
  // sink to the bottom of their group), then key for a stable tie-break.
  const tableRows = useMemo(() => {
    const inScope = (c: CatalogCommittee) =>
      scope === 'all' ? true : scope === 'tracked' ? c.tracked : failing(c)
    return rows
      .filter((c) => match(c) && inScope(c))
      .slice()
      .sort(
        (a, b) =>
          Number(b.tracked) - Number(a.tracked) ||
          tsOf(b.lastUpdateAt) - tsOf(a.lastUpdateAt) ||
          a.key.localeCompare(b.key),
      )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, needle, scope])

  const setViewMode = (v: 'cards' | 'table') => {
    setView(v)
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      /* private mode — the choice just won't persist */
    }
  }

  return (
    <Modal onClose={app.closeOverlay}>
      <div style={s(view === 'table' ? PANEL_TABLE : PANEL_WIDE)}>
        <div style={s('display:flex;align-items:center;padding:16px 20px;border-bottom:1px solid var(--bd)')}>
          {icon(I_LIST, 17, 'var(--ac)')}
          <span style={s('font-size:16px;font-weight:700;color:var(--tx);margin-left:9px')}>{pick('Committees', '委員会管理')}</span>
          <span style={s('font-size:12px;color:var(--mut);margin-left:8px')}>
            · {app.interactive ? pick('editable', '編集可能') : pick('read-only', '閲覧のみ')}
          </span>
          <div style={s('margin-left:auto;display:flex;align-items:center;gap:2px;background:var(--bg0);border:1px solid var(--bd);border-radius:999px;padding:2px')}>
            {([
              ['cards', pick('Cards', 'カード'), pick('Manage the tracked set', '追跡対象の管理')],
              ['table', pick('Status', '状態'), pick('Per-meeting pipeline status, errors and recency', '会合ごとの処理状態・エラー・更新時刻')],
            ] as const).map(([v, label, tip]) => (
              <Hoverable
                as="span"
                key={v}
                base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:3px 12px;white-space:nowrap;cursor:pointer;${
                  view === v ? 'background:var(--bg1);color:var(--tx);box-shadow:var(--sh1)' : 'color:var(--mut)'
                }`}
                hover={view === v ? '' : 'color:var(--tx)'}
                onClick={() => setViewMode(v)}
                title={tip}
                aria-pressed={view === v}
              >
                {label}
              </Hoverable>
            ))}
          </div>
          <Hoverable
            base="margin-left:8px;width:30px;height:30px;border-radius:999px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--mut)"
            hover="background:var(--bg2);color:var(--tx)"
            onClick={app.closeOverlay}
            aria-label="Close"
          >
            {icon(I_X, 16)}
          </Hoverable>
        </div>

        <div style={s('display:flex;align-items:center;gap:9px;margin:12px 20px 4px;padding:7px 12px;background:var(--bg0);border:1px solid var(--bd);border-radius:10px;color:var(--mut)')}>
          {icon(I_SEARCH, 15)}
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={pick('Search energy committees…', 'エネルギー関連委員会を検索…')}
            style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:13px;background:transparent;color:var(--tx);min-width:0')}
          />
          {!!needle && (
            <span
              onClick={() => setQ('')}
              role="button"
              tabIndex={0}
              aria-label="Clear search"
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setQ('')
                }
              }}
              style={s('font-size:11px;color:var(--mut);cursor:pointer;flex-shrink:0')}
            >✕</span>
          )}
        </div>

        {app.interactive && urlToAdd && (
          <div style={s('display:flex;align-items:center;gap:9px;margin:6px 20px 0;padding:7px 12px;background:var(--acTint);border:1px dashed var(--ac);border-radius:10px')}>
            <span style={s('font-size:11.5px;color:var(--tx2);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1')}>
              {pick('METI committee page URL', 'METI委員会ページのURL')}
            </span>
            <Hoverable
              as="span"
              base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:4px 12px;white-space:nowrap;flex-shrink:0;border:1px solid var(--bd2);background:var(--bg1);color:${adding ? 'var(--fnt3)' : 'var(--acT)'};cursor:${adding ? 'default' : 'pointer'}`}
              hover={adding ? '' : 'border-color:var(--ac);background:var(--acTint)'}
              onClick={addByUrl}
            >
              {adding ? pick('Adding…', '追加中…') : pick('+ Add & track', '＋ 追加して追跡')}
            </Hoverable>
          </div>
        )}

        {app.interactive && (
          <div style={s('display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:2px 20px 4px')}>
            <span style={s('font-size:10px;font-weight:700;letter-spacing:.06em;color:var(--mut)')}>{pick('REFRESH', '取得')}</span>
            <Hoverable
              as="span"
              base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:4px 13px;white-space:nowrap;border:1px solid var(--bd2);background:var(--bg1);color:${actionBusy ? 'var(--fnt3)' : 'var(--acT)'};cursor:${actionBusy ? 'default' : 'pointer'}`}
              hover={actionBusy ? '' : 'border-color:var(--ac);background:var(--acTint)'}
              onClick={() => !actionBusy && checkForUpdates()}
              title={pick(
                'Detect new meetings + discover new committees (all sources) — progress shows in the panel',
                '新規会合を検出し、新規委員会を発見（全ソース） — 進捗はパネルに表示',
              )}
            >
              {checking ? pick('Checking…', '確認中…') : pick('Check for updates', '更新を確認')}
            </Hoverable>
            <span style={s('width:1px;height:18px;background:var(--dv);margin:0 2px')}></span>
            <span style={s('font-size:10px;font-weight:700;letter-spacing:.06em;color:var(--mut)')} title={pick('Needs `notebooklm login`', '`notebooklm login`が必要')}>{pick('SUMMARISE ⚿', '要約 ⚿')}</span>
            {([['run', pick('Summarise all', '全件要約'), { breadth: true, max_per_run: 8 }, 'run all'], ['resume', pick('Resume', '再開'), {}, 'resume']] as const).map(([cmd, label, params, lbl]) => (
              <Hoverable
                as="span"
                key={cmd}
                base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:4px 11px;white-space:nowrap;border:1px solid var(--bd2);background:var(--bg1);color:${actionBusy ? 'var(--fnt3)' : 'var(--warnTx)'};cursor:${actionBusy ? 'default' : 'pointer'}`}
                hover={actionBusy ? '' : 'border-color:var(--warnTx);background:var(--warnBg)'}
                onClick={() => !actionBusy && postJob(cmd, params, lbl)}
                title={pick('NotebookLM — needs `notebooklm login`', 'NotebookLM — `notebooklm login`が必要')}
              >
                {label}
              </Hoverable>
            ))}
          </div>
        )}

        {view === 'table' && (
          <div style={s('display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:6px 20px 6px')}>
            {([
              ['all', pick(`All ${rows.length}`, `全 ${rows.length}`)],
              ['tracked', pick(`Tracked ${nTracked}`, `追跡 ${nTracked}`)],
              ['failing', pick(`Needs attention ${nFailing}`, `要対応 ${nFailing}`)],
            ] as const).map(([v, label]) => (
              <Hoverable
                as="span"
                key={v}
                base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:3px 12px;white-space:nowrap;cursor:pointer;${
                  scope === v
                    ? 'background:var(--acTint);border:1px solid var(--ac);color:var(--acT)'
                    : 'border:1px solid var(--bd2);color:var(--mut)'
                }`}
                hover={scope === v ? '' : 'border-color:var(--ac);color:var(--acT)'}
                onClick={() => setScope(v)}
                aria-pressed={scope === v}
              >
                {label}
              </Hoverable>
            ))}
            <span style={s('font-size:11px;color:var(--mut);margin-left:auto')}>
              {pick(
                'Tracked first, most recently updated first · click a row for its meetings',
                '追跡中を先頭に、更新の新しい順 · 行をクリックで会合を表示',
              )}
            </span>
          </div>
        )}

        <div style={s(`max-height:64vh;overflow:auto;padding:${view === 'table' ? '0 16px 12px' : '4px 16px 16px'}`)}>
          {loading && (
            <div style={s('padding:26px;text-align:center;color:var(--mut);font-size:13px')}>{pick('Loading…', '読み込み中…')}</div>
          )}
          {!loading && view === 'table' && (
            <StatusTable
              rows={tableRows}
              status={status}
              statusLoading={statusLoading}
              interactive={app.interactive}
              running={actionBusy}
              onTrack={setTracked}
              onArchive={setArchived}
              onPriority={setPriority}
              onRun={(c) => postJob('run', { committee: c.key }, `run ${c.key}`)}
              onRunLatest={runLatest}
              onBackfill={backfill}
              onRunMeeting={runMeeting}
              onQueueMeeting={queueMeeting}
            />
          )}
          {!loading && view === 'cards' && (
            <div style={s('display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;align-items:start')}>
            {ORGS.map((org) => {
              // Tracked first, then by queue priority (lower = summarised first) so the
              // column live-reorders as priorities are edited, then source_count / key.
              const items = rows
                .filter((c) => c.org === org && match(c))
                .sort(
                  (a, b) =>
                    Number(b.tracked) - Number(a.tracked) ||
                    (a.priority ?? 100) - (b.priority ?? 100) ||
                    (b.source_count || 0) - (a.source_count || 0) ||
                    a.key.localeCompare(b.key),
                )
              const inOrg = rows.filter((c) => c.org === org)
              const nTracked = inOrg.filter((c) => c.tracked).length
              return (
                <div key={org} style={s('min-width:0')}>
                  <div style={s('display:flex;align-items:center;gap:7px;margin:0 2px 8px;position:sticky;top:0;z-index:2;background:var(--bg1);padding:4px 0')}>
                    <span style={s(`width:8px;height:8px;border-radius:999px;background:${orgColor(org)};flex-shrink:0`)}></span>
                    <span style={s('font-size:12px;font-weight:700;letter-spacing:.05em;color:var(--tx2)')}>{org}</span>
                    <span style={s("font-size:11px;color:var(--mut);margin-left:auto;white-space:nowrap;font-feature-settings:'tnum' 1")}>
                      {pick(`${nTracked}/${inOrg.length} tracked`, `${nTracked}/${inOrg.length} 追跡`)}
                    </span>
                  </div>
                  {!items.length ? (
                    <div style={s('font-size:11.5px;color:var(--mut);padding:10px 4px')}>{pick('No matches', '該当なし')}</div>
                  ) : (
                  <div style={s('display:flex;flex-direction:column;gap:6px')}>
                    {items.map((c) => {
                      const following = app.isFollowing(c.key)
                      return (
                        <div
                          key={c.key}
                          style={s('display:flex;flex-direction:column;gap:6px;padding:8px 9px;border-radius:11px;border:1px solid var(--dv);background:var(--bg0)')}
                        >
                          <div style={s('display:flex;align-items:center;gap:8px;min-width:0')}>
                          <Hoverable
                            as="span"
                            base={`display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;cursor:pointer;flex-shrink:0;color:${following ? 'var(--ac)' : 'var(--fnt3)'}`}
                            hover="background:var(--acTint2);color:var(--ac)"
                            onClick={() => app.toggleFollow(c.key)}
                            title={following ? pick('Following — click to unfollow', 'フォロー中 — クリックで解除') : pick('Follow', 'フォロー')}
                            aria-label={following ? 'Unfollow committee' : 'Follow committee'}
                          >
                            {icon(following ? I_STAR : I_STAR_O, 15, 'currentColor')}
                          </Hoverable>
                          <div style={s('min-width:0;flex:1')}>
                            <div style={s('display:flex;align-items:center;gap:7px')}>
                              <span style={s('font-size:12.5px;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>
                                {L === 'ja' ? c.ja : c.en}
                              </span>
                              {c.discovered && (
                                <span style={s('font-size:9.5px;font-weight:600;color:var(--mut);border:1px dashed var(--fnt2);border-radius:6px;padding:0 6px;flex-shrink:0')}>
                                  {pick('discovered', '未追跡発見')}
                                </span>
                              )}
                            </div>
                            <div style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis")}>
                              {c.tier} · {c.last}
                            </div>
                          </div>
                          </div>
                          <div style={s('display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding-left:34px')}>
                          {c.tracked &&
                            (app.interactive ? (
                              <span
                                title={pick('Queue priority — lower is summarised first', 'キュー優先度 — 小さいほど先に処理')}
                                style={s('display:inline-flex;align-items:center;gap:3px;flex-shrink:0')}
                              >
                                <span style={s('font-size:10px;color:var(--mut)')}>#</span>
                                <input
                                  type="number"
                                  min={1}
                                  defaultValue={c.priority ?? 100}
                                  onBlur={(e) => setPriority(c.key, e.currentTarget.value, c.priority ?? 100)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur()
                                  }}
                                  style={s("width:46px;font-family:inherit;font-size:12px;font-weight:600;text-align:center;color:var(--tx);background:var(--bg0);border:1px solid var(--bd2);border-radius:8px;padding:3px 4px;font-feature-settings:'tnum' 1")}
                                />
                              </span>
                            ) : (
                              <span
                                title={pick('Queue priority (lower first)', 'キュー優先度（小さいほど先）')}
                                style={s("font-size:10.5px;font-weight:600;color:var(--mut);border:1px solid var(--bd2);border-radius:999px;padding:2px 8px;flex-shrink:0;font-feature-settings:'tnum' 1")}
                              >
                                #{c.priority ?? 100}
                              </span>
                            ))}
                          {app.interactive ? (
                            <Hoverable
                              as="span"
                              base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:4px 12px;cursor:pointer;flex-shrink:0;white-space:nowrap;${
                                c.tracked
                                  ? 'background:var(--acBadge);color:#FFFFFF'
                                  : 'border:1px solid var(--bd2);color:var(--acT);background:var(--bg1)'
                              }`}
                              hover={c.tracked ? 'background:var(--dn)' : 'border-color:var(--ac);background:var(--acTint)'}
                              onClick={() => setTracked(c.key, !c.tracked)}
                              title={c.tracked ? pick('Click to untrack', 'クリックで追跡解除') : pick('Click to track', 'クリックで追跡')}
                            >
                              {c.tracked ? pick('Tracked', '追跡中') : pick('+ Track', '＋ 追跡')}
                            </Hoverable>
                          ) : (
                            <span
                              style={s(
                                `display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;border-radius:999px;padding:3px 10px;flex-shrink:0;white-space:nowrap;${
                                  c.tracked ? 'background:var(--upBg);color:var(--up)' : 'color:var(--mut)'
                                }`,
                              )}
                            >
                              {c.tracked && icon(I_CHECK, 12, 'currentColor')}
                              {c.tracked ? pick('Tracked', '追跡中') : pick('Not tracked', '未追跡')}
                            </span>
                          )}
                          {app.interactive && (
                            <Hoverable
                              as="span"
                              base={`display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;flex-shrink:0;cursor:pointer;${
                                c.archived
                                  ? 'border:1px solid var(--warnTx);background:var(--warnBg);color:var(--warnTx)'
                                  : 'border:1px solid var(--bd2);color:var(--mut)'
                              }`}
                              hover={c.archived ? 'background:var(--bg1)' : 'border-color:var(--warnTx);color:var(--warnTx)'}
                              onClick={() => setArchived(c.key, !c.archived)}
                              title={
                                c.archived
                                  ? pick(
                                      'Archived (concluded) — every fetch pass skips it. Click to resume fetching.',
                                      'アーカイブ済み（終了）— 取得対象外。クリックで取得再開',
                                    )
                                  : pick(
                                      'Archive: stop fetching this concluded committee. Existing meetings are kept.',
                                      'アーカイブ：終了した委員会の取得を停止。既存の会合は保持されます',
                                    )
                              }
                              aria-label={c.archived ? 'Un-archive committee' : 'Archive committee'}
                            >
                              {icon(I_ARCHIVE, 12, 'currentColor')}
                            </Hoverable>
                          )}
                          {!app.interactive && c.archived && (
                            <span
                              style={s(
                                "display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;border-radius:999px;padding:3px 10px;flex-shrink:0;white-space:nowrap;background:var(--warnBg);color:var(--warnTx)",
                              )}
                            >
                              {icon(I_ARCHIVE, 11, 'currentColor')}
                              {pick('Archived', 'アーカイブ済み')}
                            </span>
                          )}
                          {app.interactive && c.tracked && (
                            <>
                              <Hoverable
                                as="span"
                                base={`display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;flex-shrink:0;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--warnTx)'};cursor:${running ? 'default' : 'pointer'}`}
                                hover={running ? '' : 'border-color:var(--warnTx);background:var(--warnBg)'}
                                onClick={() => !running && postJob('run', { committee: c.key }, `run ${c.key}`)}
                                title={pick('Summarise pending meetings only (policy run) — needs notebooklm login', '未要約の会合のみ要約（policy run）— notebooklm loginが必要')}
                                aria-label="Summarise pending meetings"
                              >
                                {icon(I_PLAY, 12, 'currentColor')}
                              </Hoverable>
                              <Hoverable
                                as="span"
                                base={`display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;flex-shrink:0;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--acT)'};cursor:${running ? 'default' : 'pointer'}`}
                                hover={running ? '' : 'border-color:var(--ac);background:var(--acTint)'}
                                onClick={() => !running && backfill(c)}
                                title={pick('Scrape older meetings back to a chosen number, then summarise (policy backfill)', '指定した回まで過去の会合を取得してから要約（policy backfill）')}
                                aria-label="Backfill older meetings"
                              >
                                {icon(I_REWIND, 12, 'currentColor')}
                              </Hoverable>
                            </>
                          )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  )}
                </div>
              )
            })}
            </div>
          )}
        </div>

        {job && job.state !== 'idle' && (
          <div style={s('margin:0 20px 6px;border:1px solid var(--bd);border-radius:10px;overflow:hidden')}>
            <div style={s('display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--bg2);font-size:11.5px')}>
              <span style={s(`width:7px;height:7px;border-radius:999px;flex-shrink:0;background:${job.state === 'running' ? 'var(--okDot)' : job.state === 'error' ? 'var(--dn)' : 'var(--up)'}`)}></span>
              <span style={s('font-weight:600;color:var(--tx)')}>{job.cmd || 'job'}</span>
              <span style={s('color:var(--mut)')}>
                {job.state}
                {job.exit_code != null ? ` · exit ${job.exit_code}` : ''}
              </span>
              <span style={s('flex:1')}></span>
              {job.state !== 'running' && (
                <span
                  onClick={() => setJob(null)}
                  role="button"
                  tabIndex={0}
                  aria-label="Dismiss job status"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setJob(null)
                    }
                  }}
                  style={s('cursor:pointer;color:var(--mut);font-size:12px')}
                >✕</span>
              )}
            </div>
            {job.result && (
              <div style={s("padding:7px 10px;font-size:11px;color:var(--tx2);background:var(--bg0);font-feature-settings:'tnum' 1")}>
                {pick(
                  `new ${job.result.new_meetings} · dated ${job.result.dated} · discovered ${job.result.discovered} · pending ${job.result.pending}`,
                  `新規 ${job.result.new_meetings} · 日付 ${job.result.dated} · 発見 ${job.result.discovered} · 要約待ち ${job.result.pending}`,
                )}
              </div>
            )}
            {Array.isArray(job.output) && job.output.length > 0 && (
              <div style={s('max-height:120px;overflow-y:auto;padding:8px 10px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;color:var(--tx2);white-space:pre-wrap;line-height:1.45;background:var(--bg0)')}>
                {job.output.slice(-40).join('\n')}
              </div>
            )}
            {job.error && (
              <div style={s('padding:8px 10px;font-size:11px;color:var(--dn);background:var(--bg0)')}>{job.error}</div>
            )}
          </div>
        )}

        <div
          style={s(
            `padding:11px 20px;border-top:1px solid var(--bd);font-size:11px;line-height:1.5;color:${
              !app.interactive && import.meta.env.DEV ? 'var(--warnTx)' : 'var(--mut)'
            };${!app.interactive && import.meta.env.DEV ? 'background:var(--warnBg)' : ''}`,
          )}
        >
          {app.interactive
            ? pick(
                'Track & priority (#) changes are saved to the local database — the next catch-up scrapes & summarises tracked committees, lowest # first. Follow ★ is a personal view filter (this browser).',
                '追跡と優先度（#）の変更はローカルDBに保存され、次回の差分取得で追跡中の委員会が#の小さい順に取得・要約されます。フォロー★はこのブラウザのみの表示フィルタです。',
              )
            : import.meta.env.DEV
              ? pick(
                  'Read-only: the local API isn’t reachable, so tracking & priority can’t be edited here. Start it with  repower web-api  (default :8787), then reload or refocus this tab. Follow ★ still works (saved in this browser).',
                  '閲覧専用：ローカルAPIに接続できないため、追跡と優先度を編集できません。 repower web-api （既定:8787）を起動し、タブを再読み込み／再フォーカスしてください。フォロー★はこのブラウザで動作します。',
                )
              : pick(
                  'Read-only deployment. Tracking & priority are managed on the local app (repower web-api); Follow ★ is a personal view filter saved in this browser.',
                  '閲覧専用のデプロイです。追跡と優先度はローカルアプリ（repower web-api）で管理します。フォロー★はこのブラウザに保存される表示フィルタです。',
                )}
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Mount points
// ---------------------------------------------------------------------------

/** All global overlays; renders whichever `overlay` is active. */
export function Overlays() {
  const { overlay } = useApp()
  if (overlay === 'search') return <CommandPalette />
  if (overlay === 'settings') return <SettingsPanel />
  if (overlay === 'watchlist') return <WatchlistPanel />
  if (overlay === 'committees') return <CommitteesManage />
  if (overlay === 'guide') return <GuidePanel />
  return null
}

/** Floating affordance to re-open the sidebar when collapsed. */
export function SidebarExpander() {
  const { collapsed, toggleCollapsed, lang } = useApp()
  if (!collapsed) return null
  return (
    <Hoverable
      base="position:fixed;left:12px;top:16px;z-index:90;display:flex;align-items:center;gap:7px;background:var(--bg1);border:1px solid var(--bd);box-shadow:var(--sh1);border-radius:999px;padding:8px 13px;cursor:pointer;color:var(--tx2)"
      hover="background:var(--bg2);color:var(--tx)"
      onClick={toggleCollapsed}
      title={lang === 'ja' ? 'サイドバーを開く' : 'Expand sidebar'}
      aria-label="Expand sidebar"
    >
      {icon(I_CHEV_RR, 16, 'currentColor')}
      <span style={s('font-size:12.5px;font-weight:600')}>JEMA</span>
    </Hoverable>
  )
}

// ---------------------------------------------------------------------------
// Progress panel — a persistent, minimisable feed of background jobs
// ---------------------------------------------------------------------------
// Toasts are ephemeral (single-slot, auto-dismiss), so they're a poor fit for a
// multi-stage catch-up that runs for a while. This panel is the durable
// alternative: it shows the active job's live per-stage (and per-committee)
// progress plus a short history of recent runs, and it can collapse to a pill.
const I_CHEVDOWN = '<polyline points="6 9 12 15 18 9"></polyline>'
const I_CHEVUP = '<polyline points="18 15 12 9 6 15"></polyline>'
const I_ALERT =
  '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>'

function jobStateColor(state: string): string {
  return state === 'error' ? 'var(--dn)' : state === 'done' ? 'var(--up)' : 'var(--warnTx)'
}

/** Status glyph: check (done), alert (error), or a soft-glowing dot (running). */
function StatusDot({ state }: { state: string }) {
  const c = jobStateColor(state)
  if (state === 'done') return icon(I_CHECK, 13, c)
  if (state === 'error') return icon(I_ALERT, 13, c)
  return (
    <span
      style={s(
        `width:8px;height:8px;border-radius:999px;background:${c};box-shadow:0 0 0 3px color-mix(in srgb, ${c} 22%, transparent);flex-shrink:0`,
      )}
    />
  )
}

/** Compact relative time ("just now", "3m ago", "2h ago", "1d ago"). */
function relTime(ts: number, ja: boolean): string {
  const secs = Math.max(0, Math.round((Date.now() - ts) / 1000))
  if (secs < 45) return ja ? 'たった今' : 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return ja ? `${mins}分前` : `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return ja ? `${hrs}時間前` : `${hrs}h ago`
  const days = Math.round(hrs / 24)
  return ja ? `${days}日前` : `${days}d ago`
}

export function ProgressPanel() {
  const { jobRuns, panelMin, setPanelMinimized, dismissRun, clearRuns, interactive, lang } = useApp()
  const L = lang
  // Keep relative timestamps fresh while the panel is open.
  const [, tick] = useState(0)
  useEffect(() => {
    if (!jobRuns.length) return
    const t = window.setInterval(() => tick((n) => n + 1), 15000)
    return () => window.clearInterval(t)
  }, [jobRuns.length])

  if (!interactive || jobRuns.length === 0) return null

  const active = jobRuns.find((r) => r.state === 'running') || null
  const finished = jobRuns.filter((r) => r.state !== 'running')
  const title = (r: JobRun) => (L === 'ja' ? r.titleJa : r.title)

  // Minimised → a compact pill summarising the newest/active run; click to open.
  if (panelMin) {
    const head = active || jobRuns[0]
    const done = head.stages.filter((sg) => sg.state !== 'running').length
    const label = active
      ? `${title(head)} · ${head.stages.length ? `${done}/${head.stages.length}` : L === 'ja' ? '実行中' : 'running'}`
      : L === 'ja'
        ? 'アクティビティ'
        : 'Activity'
    return (
      <Hoverable
        base="position:fixed;left:16px;bottom:16px;z-index:150;display:flex;align-items:center;gap:9px;background:var(--bg1);border:1px solid var(--bd);box-shadow:var(--sh1);border-radius:999px;padding:8px 14px;cursor:pointer;color:var(--tx2)"
        hover="background:var(--bg2);color:var(--tx)"
        onClick={() => setPanelMinimized(false)}
        title={L === 'ja' ? 'パネルを開く' : 'Expand activity panel'}
        aria-label={L === 'ja' ? 'アクティビティパネルを開く' : 'Expand activity panel'}
      >
        <StatusDot state={active ? 'running' : jobRuns[0].state} />
        <span style={s('font-size:12px;font-weight:600;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>
          {label}
        </span>
        {icon(I_CHEVUP, 14, 'currentColor')}
      </Hoverable>
    )
  }

  const stageLine = (sg: JobStage) => {
    const lab = L === 'ja' ? sg.label_ja : sg.label
    const det = L === 'ja' ? sg.detail_ja : sg.detail
    const running = sg.state === 'running'
    return (
      <div key={sg.key} style={s('display:flex;align-items:center;gap:8px;padding:3px 0')}>
        <StatusDot state={sg.state} />
        <span style={s(`font-size:11.5px;color:${running ? 'var(--tx)' : 'var(--tx2)'};font-weight:${running ? 600 : 500}`)}>
          {lab}
        </span>
        {det ? (
          <span style={s('font-size:11px;color:var(--mut);margin-left:auto;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>
            {det}
          </span>
        ) : null}
      </div>
    )
  }

  const resultLine = (r: JobRun): string | null => {
    if (r.state === 'error') return r.error || (L === 'ja' ? '失敗しました' : 'failed')
    if (r.kind === 'catchup' && r.result) {
      const x = r.result
      if (!x.new_meetings && !x.discovered && !x.dated) {
        return x.pending
          ? L === 'ja'
            ? `新規なし · 要約待ち ${x.pending}`
            : `no new · ${x.pending} pending`
          : L === 'ja'
            ? '新規の更新なし'
            : 'no new updates'
      }
      return L === 'ja'
        ? `新規 ${x.new_meetings ?? 0} · 発見 ${x.discovered ?? 0} · 要約待ち ${x.pending ?? 0}`
        : `${x.new_meetings ?? 0} new · ${x.discovered ?? 0} discovered · ${x.pending ?? 0} pending`
    }
    if (r.state === 'done') return L === 'ja' ? '完了' : 'done'
    return null
  }

  return (
    <div style={s('position:fixed;left:16px;bottom:16px;z-index:150;width:340px;max-width:calc(100vw - 32px);background:var(--bg1);border:1px solid var(--bd);border-radius:14px;box-shadow:var(--shPop);overflow:hidden')}>
      {/* header */}
      <div style={s('display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--dv)')}>
        <StatusDot state={active ? 'running' : jobRuns[0].state} />
        <span style={s('font-size:12.5px;font-weight:700;color:var(--tx)')}>
          {active ? title(active) : L === 'ja' ? 'アクティビティ' : 'Activity'}
        </span>
        {active && active.stages.length ? (
          <span style={s('font-size:10px;font-weight:600;color:var(--warnTx);background:var(--warnBg);border-radius:6px;padding:1px 6px')}>
            {active.stages.filter((sg) => sg.state !== 'running').length}/{active.stages.length}
          </span>
        ) : null}
        <div style={s('margin-left:auto;display:flex;align-items:center;gap:2px')}>
          {finished.length ? (
            <Hoverable
              base="padding:4px 6px;border-radius:7px;cursor:pointer;color:var(--mut);font-size:10.5px;font-weight:600"
              hover="background:var(--bg2);color:var(--tx)"
              onClick={clearRuns}
              title={L === 'ja' ? '履歴を消去' : 'Clear history'}
            >
              {L === 'ja' ? '消去' : 'Clear'}
            </Hoverable>
          ) : null}
          <Hoverable
            base="display:flex;padding:4px;border-radius:7px;cursor:pointer;color:var(--mut)"
            hover="background:var(--bg2);color:var(--tx)"
            onClick={() => setPanelMinimized(true)}
            title={L === 'ja' ? '最小化' : 'Minimise'}
            aria-label={L === 'ja' ? 'パネルを最小化' : 'Minimise panel'}
          >
            {icon(I_CHEVDOWN, 15, 'currentColor')}
          </Hoverable>
        </div>
      </div>

      {/* active run detail */}
      {active ? (
        <div style={s('padding:8px 12px;border-bottom:1px solid var(--dv)')}>
          {active.stages.length ? (
            active.stages.map(stageLine)
          ) : (
            <div style={s('display:flex;align-items:center;gap:8px;padding:3px 0')}>
              <StatusDot state="running" />
              <span style={s('font-size:11.5px;color:var(--tx);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')}>
                {active.output.length ? active.output[active.output.length - 1] : L === 'ja' ? '処理中…' : 'Working…'}
              </span>
            </div>
          )}
        </div>
      ) : null}

      {/* history */}
      {finished.length ? (
        <div style={s('max-height:230px;overflow:auto')}>
          <div style={s('padding:7px 12px 3px')}>
            <span style={s('font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)')}>
              {L === 'ja' ? '履歴' : 'Recent'}
            </span>
          </div>
          {finished.map((r) => {
            const res = resultLine(r)
            return (
              <Hoverable key={r.id} base="display:flex;align-items:flex-start;gap:8px;padding:6px 12px" hover="background:var(--bg2)">
                <div style={s('margin-top:1px')}>
                  <StatusDot state={r.state} />
                </div>
                <div style={s('min-width:0;flex:1')}>
                  <div style={s('display:flex;align-items:baseline;gap:6px')}>
                    <span style={s('font-size:11.5px;font-weight:600;color:var(--tx)')}>{title(r)}</span>
                    <span style={s('font-size:10px;color:var(--mut);margin-left:auto;flex-shrink:0')}>
                      {r.finishedAt ? relTime(r.finishedAt, L === 'ja') : ''}
                    </span>
                  </div>
                  {res ? (
                    <div style={s(`font-size:10.5px;color:${r.state === 'error' ? 'var(--dn)' : 'var(--tx2)'};margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`)}>
                      {res}
                    </div>
                  ) : null}
                </div>
                <Hoverable
                  base="display:flex;padding:2px;border-radius:6px;cursor:pointer;color:var(--mut);opacity:.6"
                  hover="background:var(--bd2);color:var(--tx);opacity:1"
                  onClick={() => dismissRun(r.id)}
                  title={L === 'ja' ? '削除' : 'Dismiss'}
                  aria-label={L === 'ja' ? '履歴から削除' : 'Dismiss from history'}
                >
                  {icon(I_X, 12, 'currentColor')}
                </Hoverable>
              </Hoverable>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
