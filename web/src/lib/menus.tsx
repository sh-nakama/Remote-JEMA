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
    for (const c of committees)
      out.push({
        id: `com:${c.key}`,
        en: c.en,
        ja: c.ja,
        group: 'Committees',
        groupJa: '委員会',
        run: () => go('policy'),
      })
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committees, app.theme, app.lang])

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
// Mount points
// ---------------------------------------------------------------------------

/** All global overlays; renders whichever `overlay` is active. */
export function Overlays() {
  const { overlay } = useApp()
  if (overlay === 'search') return <CommandPalette />
  if (overlay === 'settings') return <SettingsPanel />
  if (overlay === 'watchlist') return <WatchlistPanel />
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
