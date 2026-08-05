import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from './app'
import type { JobRun, JobStage, Screen, WatchEntry } from './app'
import { getSnapshot, refreshSnapshots, useManifest } from './data'
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
}

const ORGS: Array<'METI' | 'OCCTO' | 'EGC'> = ['METI', 'OCCTO', 'EGC']

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

  useEffect(() => {
    let alive = true
    setLoading(true)
    loadCatalog().finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.interactive])

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
          // (crosscheck/discover add discovered committees; detect updates latest).
          loadCatalog()
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

  return (
    <Modal onClose={app.closeOverlay}>
      <div style={s(PANEL_WIDE)}>
        <div style={s('display:flex;align-items:center;padding:16px 20px;border-bottom:1px solid var(--bd)')}>
          {icon(I_LIST, 17, 'var(--ac)')}
          <span style={s('font-size:16px;font-weight:700;color:var(--tx);margin-left:9px')}>{pick('Committees', '委員会管理')}</span>
          <span style={s('font-size:12px;color:var(--mut);margin-left:8px')}>
            · {app.interactive ? pick('editable', '編集可能') : pick('read-only', '閲覧のみ')}
          </span>
          <Hoverable
            base="margin-left:auto;width:30px;height:30px;border-radius:999px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--mut)"
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

        <div style={s('max-height:64vh;overflow-y:auto;padding:4px 16px 16px')}>
          {loading && (
            <div style={s('padding:26px;text-align:center;color:var(--mut);font-size:13px')}>{pick('Loading…', '読み込み中…')}</div>
          )}
          {!loading && (
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
