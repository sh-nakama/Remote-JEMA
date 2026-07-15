import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from './app'
import type { Screen, WatchEntry } from './app'
import { getSnapshot } from './data'
import type { AreaKey, Level, Manifest } from './types'
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
  const [meta, setMeta] = useState<Manifest | null>(null)
  useEffect(() => {
    let alive = true
    getSnapshot<Manifest>('manifest.json')
      .then((m) => alive && setMeta(m))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

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
  'width:720px;max-width:95vw;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shPop);overflow:hidden'
const I_LIST =
  '<line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line>'
const I_STAR_O =
  '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon>'
const I_CHECK = '<polyline points="20 6 9 17 4 12"></polyline>'
const I_PLAY = '<polygon points="5 3 19 12 5 21 5 3"></polygon>'
const I_REWIND = '<polyline points="11 19 2 12 11 5"></polyline><polyline points="22 19 13 12 22 5"></polyline>'

interface CatalogCommittee {
  key: string
  org: 'METI' | 'OCCTO' | 'EGC'
  en: string
  ja: string
  tier: string
  tracked: boolean
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
  // Reused after a job finishes, since detect/discover/crosscheck can add or change
  // rows (e.g. crosscheck accumulates newly-found committees as discovered).
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
      .then(() =>
        app.toast(
          enabled
            ? pick('Now tracking — included in the next catch-up', '追跡開始 — 次回の差分取得に含まれます')
            : pick('Untracked — skipped by the catch-up', '追跡解除 — 差分取得の対象外'),
        ),
      )
      .catch(() => {
        setRows((rs) => rs.map((r) => (r.key === key ? { ...r, tracked: !enabled } : r))) // revert
        app.toast(pick('Could not update tracking', '追跡を更新できませんでした'))
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
  const [job, setJob] = useState<Record<string, any> | null>(null)
  const jobTimer = useRef<number | null>(null)

  const pollJob = () => {
    fetch('/api/policy/job')
      .then((r) => r.json())
      .then((j) => {
        setJob(j)
        if (j && j.state === 'running') {
          jobTimer.current = window.setTimeout(pollJob, 1500)
        } else {
          // Job finished: refresh the catalog so any rows it added/changed show up
          // (crosscheck/discover add discovered committees; detect updates latest).
          loadCatalog()
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
        const j = await r.json().catch(() => ({}))
        if (r.status === 202) {
          setJob(j)
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
      .then((j) => {
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
            <span onClick={() => setQ('')} style={s('font-size:11px;color:var(--mut);cursor:pointer;flex-shrink:0')}>✕</span>
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
            {([['detect', 'Detect'], ['discover', 'Discover'], ['crosscheck', 'Cross-check']] as const).map(([cmd, label]) => (
              <Hoverable
                as="span"
                key={cmd}
                base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:4px 11px;white-space:nowrap;border:1px solid var(--bd2);background:var(--bg1);color:${running ? 'var(--fnt3)' : 'var(--acT)'};cursor:${running ? 'default' : 'pointer'}`}
                hover={running ? '' : 'border-color:var(--ac);background:var(--acTint)'}
                onClick={() => !running && postJob(cmd)}
              >
                {label}
              </Hoverable>
            ))}
            <span style={s('width:1px;height:18px;background:var(--dv);margin:0 2px')}></span>
            <span style={s('font-size:10px;font-weight:700;letter-spacing:.06em;color:var(--mut)')} title={pick('Needs `notebooklm login`', '`notebooklm login`が必要')}>{pick('SUMMARISE ⚿', '要約 ⚿')}</span>
            {([['run', pick('Summarise all', '全件要約'), {}, 'run all'], ['resume', pick('Resume', '再開'), {}, 'resume']] as const).map(([cmd, label, params, lbl]) => (
              <Hoverable
                as="span"
                key={cmd}
                base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:4px 11px;white-space:nowrap;border:1px solid var(--bd2);background:var(--bg1);color:${running ? 'var(--fnt3)' : 'var(--warnTx)'};cursor:${running ? 'default' : 'pointer'}`}
                hover={running ? '' : 'border-color:var(--warnTx);background:var(--warnBg)'}
                onClick={() => !running && postJob(cmd, params, lbl)}
                title={pick('NotebookLM — needs `notebooklm login`', 'NotebookLM — `notebooklm login`が必要')}
              >
                {label}
              </Hoverable>
            ))}
          </div>
        )}

        <div style={s('max-height:52vh;overflow-y:auto;padding:4px 12px 14px')}>
          {loading && (
            <div style={s('padding:26px;text-align:center;color:var(--mut);font-size:13px')}>{pick('Loading…', '読み込み中…')}</div>
          )}
          {!loading &&
            ORGS.map((org) => {
              const items = rows
                .filter((c) => c.org === org && match(c))
                .sort(
                  (a, b) =>
                    Number(b.tracked) - Number(a.tracked) ||
                    (b.source_count || 0) - (a.source_count || 0) ||
                    a.key.localeCompare(b.key),
                )
              if (!items.length) return null
              const inOrg = rows.filter((c) => c.org === org)
              const nTracked = inOrg.filter((c) => c.tracked).length
              return (
                <div key={org} style={s('margin-top:12px')}>
                  <div style={s('display:flex;align-items:center;gap:7px;margin:0 4px 6px')}>
                    <span style={s(`width:8px;height:8px;border-radius:999px;background:${orgColor(org)};flex-shrink:0`)}></span>
                    <span style={s('font-size:12px;font-weight:700;letter-spacing:.05em;color:var(--tx2)')}>{org}</span>
                    <span style={s("font-size:11px;color:var(--mut);margin-left:2px;font-feature-settings:'tnum' 1")}>
                      · {pick(`tracking ${nTracked} of ${inOrg.length}`, `${inOrg.length}件中${nTracked}件を追跡`)}
                    </span>
                  </div>
                  <div style={s('display:flex;flex-direction:column;gap:2px')}>
                    {items.map((c) => {
                      const following = app.isFollowing(c.key)
                      return (
                        <div
                          key={c.key}
                          style={s('display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:11px;border-bottom:1px solid var(--dv)')}
                        >
                          <Hoverable
                            as="span"
                            base={`display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;cursor:pointer;flex-shrink:0;color:${following ? 'var(--ac)' : 'var(--fnt3)'}`}
                            hover="background:var(--acTint2);color:var(--ac)"
                            onClick={() => app.toggleFollow(c.key)}
                            title={following ? pick('Following — click to unfollow', 'フォロー中 — クリックで解除') : pick('Follow', 'フォロー')}
                          >
                            {icon(following ? I_STAR : I_STAR_O, 15, 'currentColor')}
                          </Hoverable>
                          <div style={s('min-width:0;flex:1')}>
                            <div style={s('display:flex;align-items:center;gap:7px')}>
                              <span style={s('font-size:13px;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>
                                {L === 'ja' ? c.ja : c.en}
                              </span>
                              {c.discovered && (
                                <span style={s('font-size:9.5px;font-weight:600;color:var(--mut);border:1px dashed var(--fnt2);border-radius:6px;padding:0 6px;flex-shrink:0')}>
                                  {pick('discovered', '未追跡発見')}
                                </span>
                              )}
                            </div>
                            <div style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                              {c.tier} · {c.last}
                            </div>
                          </div>
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
                          {app.interactive && c.tracked && (
                            <>
                              <Hoverable
                                as="span"
                                base={`display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;flex-shrink:0;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--warnTx)'};cursor:${running ? 'default' : 'pointer'}`}
                                hover={running ? '' : 'border-color:var(--warnTx);background:var(--warnBg)'}
                                onClick={() => !running && postJob('run', { committee: c.key }, `run ${c.key}`)}
                                title={pick('Summarise pending meetings only (policy run) — needs notebooklm login', '未要約の会合のみ要約（policy run）— notebooklm loginが必要')}
                              >
                                {icon(I_PLAY, 12, 'currentColor')}
                              </Hoverable>
                              <Hoverable
                                as="span"
                                base={`display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;flex-shrink:0;border:1px solid var(--bd2);color:${running ? 'var(--fnt3)' : 'var(--acT)'};cursor:${running ? 'default' : 'pointer'}`}
                                hover={running ? '' : 'border-color:var(--ac);background:var(--acTint)'}
                                onClick={() => !running && backfill(c)}
                                title={pick('Scrape older meetings back to a chosen number, then summarise (policy backfill)', '指定した回まで過去の会合を取得してから要約（policy backfill）')}
                              >
                                {icon(I_REWIND, 12, 'currentColor')}
                              </Hoverable>
                            </>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
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
                <span onClick={() => setJob(null)} style={s('cursor:pointer;color:var(--mut);font-size:12px')}>✕</span>
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
    >
      {icon(I_CHEV_RR, 16, 'currentColor')}
      <span style={s('font-size:12.5px;font-weight:600')}>JEMA</span>
    </Hoverable>
  )
}
