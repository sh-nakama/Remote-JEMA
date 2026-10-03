// Page chrome shared by the four screens: the nav sidebar (and Policy's icon rail),
// the top bar and the page header. Markup matches the hi-fi exports exactly.
import type { ReactNode } from 'react'
import { s, Hoverable, RawSvg, press } from './style'
import { useApp, type Screen } from './app'
import { FreshnessChip } from './freshness'
import { PolicyNavBadge } from './policyActivity'
import { segBase } from './chartkit'

const svg = (body: string, style: string, width = '1.8') =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" style="${style}">${body}</svg>`

const P = {
  bolt: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>',
  overview: '<rect x="3" y="3" width="7" height="9" rx="1"></rect><rect x="14" y="3" width="7" height="5" rx="1"></rect><rect x="14" y="12" width="7" height="9" rx="1"></rect><rect x="3" y="16" width="7" height="5" rx="1"></rect>',
  market: '<path d="M3 3v18h18"></path><path d="M8 17v-3"></path><path d="M13 17V9"></path><path d="M18 17V5"></path>',
  capacity: '<polygon points="12 2 22 8.5 12 15 2 8.5 12 2"></polygon><polyline points="2 14 12 20.5 22 14"></polyline>',
  policy: '<line x1="3" y1="22" x2="21" y2="22"></line><line x1="6" y1="18" x2="6" y2="11"></line><line x1="10" y1="18" x2="10" y2="11"></line><line x1="14" y1="18" x2="14" y2="11"></line><line x1="18" y1="18" x2="18" y2="11"></line><polygon points="12 2 20 7 4 7"></polygon>',
  star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon>',
  bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path>',
  gear: '<circle cx="12" cy="12" r="3"></circle><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>',
  collapse: '<path d="M11 17l-5-5 5-5"></path><path d="M18 17l-5-5 5-5"></path>',
  expand: '<path d="M13 17l5-5-5-5"></path><path d="M6 17l5-5-5-5"></path>',
  chevron: '<path d="M9 18l6-6-6-6"></path>',
  db: '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14a9 3 0 0 0 18 0V5"></path><path d="M3 12a9 3 0 0 0 18 0"></path>',
  refresh: '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path>',
  search: '<circle cx="11" cy="11" r="8"></circle><path d="M21 21l-4.35-4.35"></path>',
  sun: '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>',
  moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>',
  info: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line>',
}

const TITLES: Record<Screen, [string, string]> = {
  overview: ['Market Overview', 'マーケット概況'],
  market: ['Market Data', 'マーケットデータ'],
  capacity: ['Capacity & Auctions', '容量市場・オークション'],
  policy: ['Policy Deep Dive', '政策ディープダイブ'],
}

// `trail` is what an inactive sidebar item shows at its right edge.
const NAV: { key: Screen; en: string; ja: string; railJa: string; aria: string; icon: string; trail: 'label' | 'chevron' | 'badge' }[] = [
  { key: 'overview', en: 'Market Overview', ja: '概況', railJa: '概況', aria: 'Market Overview', icon: P.overview, trail: 'label' },
  { key: 'market', en: 'Market Data', ja: 'データ', railJa: 'データ', aria: 'Market Data', icon: P.market, trail: 'chevron' },
  { key: 'capacity', en: 'Capacity & Auctions', ja: '容量', railJa: '容量市場', aria: 'Capacity and Auctions', icon: P.capacity, trail: 'chevron' },
  { key: 'policy', en: 'Policy Deep Dive', ja: '政策', railJa: '政策', aria: 'Policy Deep Dive', icon: P.policy, trail: 'badge' },
]

const NAV_ITEM = 'display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer'
const NAV_HOVER = 'background:var(--acTint2);color:var(--tx)'
const NAV_ICON = 'width:18px;height:18px;flex-shrink:0'
const COUNT_BADGE = 'margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px'
const RAIL_ITEM = 'width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer'
const ROUND_BTN = 'width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;flex-shrink:0'

/** Re-run the data refresh and confirm it with a toast. */
export function useReload(): () => void {
  const { refreshData, toast } = useApp()
  return () => {
    refreshData()
    toast('Reloaded latest data · 最新データを再取得しました')
  }
}

/** The full nav sidebar. Capacity passes its own freshness lines (OCCTO publishes per auction, not daily). */
export function Sidebar({ active, unread, onToggleNotif, lastPublication, source = 'Hugging Face sync · GitHub Actions daily' }: {
  active: Screen
  unread: number
  onToggleNotif: () => void
  lastPublication?: string
  source?: string
}) {
  const { setScreen, openOverlay, collapsed, toggleCollapsed, watch, refreshing } = useApp()
  const reload = useReload()
  return (
    <div style={s(`width:264px;flex-shrink:0;background:var(--bg1);border-right:1px solid var(--bd);flex-direction:column;padding:22px 16px 16px;overflow-y:auto;${collapsed ? 'display:none' : 'display:flex'}`)}>
      <div style={s('padding:0 8px')}>
        <div style={s('display:flex;align-items:center;gap:7px')}>
          <RawSvg html={svg(P.bolt, 'width:23px;height:23px;color:var(--ac);flex-shrink:0', '2')} />
          <span style={s('font-size:21px;font-weight:700;letter-spacing:.01em')}>JEMA</span>
        </div>
        <div style={s('font-size:9px;font-weight:600;letter-spacing:.14em;color:var(--mut);margin-top:3px;text-transform:uppercase')}>Japan Energy Market Analytics</div>
      </div>

      <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:26px 8px 8px')}>MENU · メニュー</div>
      <div style={s('display:flex;flex-direction:column;gap:3px')}>
        {NAV.map((n) =>
          n.key === active ? (
            <div key={n.key} style={s('display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:600;color:var(--acT);background:var(--acTint);cursor:pointer;position:relative')}>
              <span style={s('position:absolute;left:-16px;top:8px;bottom:8px;width:3px;background:var(--ac);border-radius:0 2px 2px 0')}></span>
              <RawSvg html={svg(n.icon, NAV_ICON)} /><span>{n.en}</span>
              <span style={s('margin-left:auto;font-size:10.5px;font-weight:500;color:var(--acHi)')}>{n.ja}</span>
            </div>
          ) : (
            <Hoverable key={n.key} base={NAV_ITEM} hover={NAV_HOVER} onClick={() => setScreen(n.key)}>
              <RawSvg html={svg(n.icon, NAV_ICON)} /><span>{n.en}</span>
              {n.trail === 'label' && <span style={s('margin-left:auto;font-size:10.5px;font-weight:500;color:var(--mut)')}>{n.ja}</span>}
              {n.trail === 'chevron' && <RawSvg html={svg(P.chevron, 'width:14px;height:14px;margin-left:auto;color:var(--mut);flex-shrink:0')} />}
              {n.trail === 'badge' && <PolicyNavBadge />}
            </Hoverable>
          ),
        )}
      </div>

      <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:22px 8px 8px')}>GENERAL · 全般</div>
      <div style={s('display:flex;flex-direction:column;gap:3px')}>
        <Hoverable base={NAV_ITEM} hover={NAV_HOVER} onClick={() => openOverlay('watchlist')}>
          <RawSvg html={svg(P.star, NAV_ICON)} /><span>Watchlist</span>
          {watch.length > 0 && <span style={s(COUNT_BADGE)}>{watch.length}</span>}
        </Hoverable>
        <Hoverable base={NAV_ITEM} hover={NAV_HOVER} onClick={onToggleNotif}>
          <RawSvg html={svg(P.bell, NAV_ICON)} /><span>Notifications</span>
          {unread > 0 && <span style={s(COUNT_BADGE)}>{unread}</span>}
        </Hoverable>
        <Hoverable base={NAV_ITEM} hover={NAV_HOVER} onClick={() => openOverlay('settings')}>
          <RawSvg html={svg(P.gear, NAV_ICON)} /><span>Settings</span>
        </Hoverable>
      </div>

      <div style={s('flex:1')}></div>

      <Hoverable base="display:flex;align-items:center;gap:8px;padding:6px 12px;color:var(--mut);font-size:12px;cursor:pointer;border-radius:10px" hover="background:var(--bg2);color:var(--tx2)" onClick={toggleCollapsed}>
        <RawSvg html={svg(P.collapse, 'width:16px;height:16px;flex-shrink:0')} /><span>Collapse · 折りたたむ</span>
      </Hoverable>

      <div style={s('background:linear-gradient(135deg,var(--navyA),var(--navyB));border-radius:16px;padding:15px 15px 13px;color:#FFFFFF;margin-top:12px')}>
        <div style={s('display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600')}><RawSvg html={svg(P.db, 'width:15px;height:15px;color:#7FD4E8;flex-shrink:0')} />Data freshness · データ鮮度</div>
        {lastPublication && (
          <div style={s('font-size:12px;color:rgba(255,255,255,.78);margin-top:6px')}>Last publication <span style={s("font-weight:600;color:#FFFFFF;font-feature-settings:'tnum' 1")}>{lastPublication}</span></div>
        )}
        <FreshnessChip inverse style={{ marginTop: lastPublication ? 2 : 6 }} />
        <div style={s('font-size:10.5px;color:rgba(255,255,255,.55);margin-top:2px')}>{source}</div>
        <Hoverable base="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.35);color:#FFFFFF;border-radius:999px;padding:5px 13px;font-size:12px;font-weight:500;cursor:pointer;margin-top:10px" hover="background:rgba(255,255,255,.10)" onClick={reload}>
          <span style={s(refreshing ? 'display:inline-flex;animation:jema-spin .7s linear infinite' : 'display:inline-flex')}><RawSvg html={svg(P.refresh, 'width:13px;height:13px;flex-shrink:0')} /></span>Refresh · 更新
        </Hoverable>
      </div>
    </div>
  )
}

/** The collapsed icon rail the three-pane Policy screen uses instead of the sidebar. */
export function IconRail({ active }: { active: Screen }) {
  const { setScreen, openOverlay, toast } = useApp()
  const icon = (body: string) => <RawSvg html={svg(body, 'width:19px;height:19px')} />
  return (
    <div style={s('width:68px;flex-shrink:0;background:var(--bg1);border-right:1px solid var(--bd);display:flex;flex-direction:column;align-items:center;padding:22px 0 16px;gap:4px')}>
      <RawSvg html={svg(P.bolt, 'width:24px;height:24px;color:var(--ac);flex-shrink:0;margin-bottom:18px', '2')} />
      {NAV.map((n) =>
        n.key === active ? (
          <div key={n.key} style={s('width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#FFFFFF;background:var(--acBadge);cursor:pointer;position:relative')} title={`${n.en} · ${n.railJa}`}>
            <span style={s('position:absolute;left:-13px;top:8px;bottom:8px;width:3px;background:var(--ac);border-radius:0 2px 2px 0')}></span>
            {icon(n.icon)}
          </div>
        ) : (
          <Hoverable key={n.key} base={RAIL_ITEM} hover={NAV_HOVER} onClick={() => setScreen(n.key)} title={`${n.en} · ${n.railJa}`} aria-label={n.aria}>
            {icon(n.icon)}
          </Hoverable>
        ),
      )}
      <div style={s('width:28px;height:1px;background:var(--dv);margin:6px 0')}></div>
      <Hoverable base={RAIL_ITEM} hover={NAV_HOVER} onClick={() => openOverlay('watchlist')} title="Watchlist · ウォッチリスト" aria-label="Watchlist">
        {icon(P.star)}
      </Hoverable>
      <Hoverable base={RAIL_ITEM} hover={NAV_HOVER} onClick={() => openOverlay('settings')} title="Settings · 設定" aria-label="Settings">
        {icon(P.gear)}
      </Hoverable>
      <div style={s('flex:1')}></div>
      <Hoverable base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--mut);cursor:pointer" hover="background:var(--bg2);color:var(--tx2)" onClick={() => toast('Nav rail auto-collapses on this screen to fit three panes · 3ペイン表示のためナビは自動折りたたみ')} title="Expand nav · ナビを展開" aria-label="Expand navigation">
        <RawSvg html={svg(P.expand, 'width:17px;height:17px')} />
      </Hoverable>
    </div>
  )
}

/** Breadcrumb, search, theme / guide / notification buttons, language and profile. `children` is the notifications popover.
 * The guide button opens the tab for the current screen. */
export function TopBar({ screen, unread, onToggleNotif, children }: {
  screen: Screen
  unread: number
  onToggleNotif: () => void
  children: ReactNode
}) {
  const { lang, setLang, theme, toggleTheme, openOverlay, setGuideTab } = useApp()
  const [title, titleJa] = TITLES[screen]
  return (
    <div style={s('height:72px;flex-shrink:0;background:var(--bg1);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:18px;padding:0 28px;position:relative;z-index:30')}>
      <div style={s('font-size:13px;color:var(--mut);min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{title} <span style={s('color:var(--fnt3)')}>·</span> {titleJa}</div>
      <div {...press(() => openOverlay('search'))} style={s('flex:1;min-width:0;max-width:520px;display:flex;align-items:center;gap:9px;background:var(--bg0);border:1px solid var(--bd);border-radius:12px;padding:8px 14px;color:var(--mut);cursor:text')}>
        <RawSvg html={svg(P.search, 'width:16px;height:16px;flex-shrink:0')} />
        <input readOnly onFocus={() => openOverlay('search')} placeholder="Search markets, areas, committees… 市場・エリア・委員会を検索…" style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:13px;background:transparent;color:var(--tx);min-width:0;cursor:text')} />
        <span style={s('border:1px solid var(--bd2);background:var(--bg1);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--mut);flex-shrink:0')}>⌘K</span>
      </div>
      <div style={s('flex:1')}></div>
      <Hoverable base={ROUND_BTN} hover="background:var(--bg2)" onClick={toggleTheme} title="Toggle theme · テーマ切替" aria-label="Toggle theme">
        {theme === 'dark' ? <RawSvg html={svg(P.sun, 'width:19px;height:19px')} /> : <RawSvg html={svg(P.moon, 'width:18px;height:18px')} />}
      </Hoverable>
      <Hoverable base={ROUND_BTN} hover="background:var(--bg2)" onClick={() => { setGuideTab(screen === 'policy' ? 'policy' : 'screens'); openOverlay('guide') }} title="User guide · 使い方" aria-label="User guide">
        <RawSvg html={svg(P.info, 'width:19px;height:19px')} />
      </Hoverable>
      <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;position:relative;flex-shrink:0" hover="background:var(--bg2)" onClick={onToggleNotif} aria-label="Notifications">
        <RawSvg html={svg(P.bell, 'width:19px;height:19px')} />
        {unread > 0 && (
          <span style={s('position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:999px;background:var(--ac);border:1.5px solid var(--bg1)')}></span>
        )}
      </Hoverable>
      <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;flex-shrink:0')}>
        <span style={segBase(lang === 'ja')} {...press(() => setLang('ja'), lang === 'ja')}>日本語</span>
        <span style={segBase(lang === 'en')} {...press(() => setLang('en'), lang === 'en')}>English</span>
      </div>
      <div style={s('display:flex;align-items:center;gap:10px;flex-shrink:0')}>
        <div style={s('width:34px;height:34px;border-radius:999px;background:var(--avatar);color:#FFFFFF;display:flex;align-items:center;justify-content:center;font-size:11.5px;font-weight:600')}>AN</div>
        <div style={s('line-height:1.25')}>
          <div style={s('font-size:13px;font-weight:600')}>Analyst</div>
          <div style={s('font-size:11px;color:var(--mut)')}>analyst@example.jp</div>
        </div>
      </div>
      {children}
    </div>
  )
}

/** Title, subtitle and optional extra line on the left; `children` (the action buttons) on the right. */
export function PageHeader({ screen, subtitle, extra, children }: {
  screen: Screen
  subtitle: string
  extra?: ReactNode
  children: ReactNode
}) {
  const [title, titleJa] = TITLES[screen]
  return (
    <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:16px')}>
      <div>
        <div style={s('display:flex;align-items:baseline;gap:10px')}>
          <span style={s('font-size:26px;font-weight:700;letter-spacing:-.01em')}>{title}</span>
          <span style={s('font-size:15px;font-weight:500;color:var(--mut)')}>{titleJa}</span>
        </div>
        <div style={s('font-size:13.5px;color:var(--tx2);margin-top:2px')}>{subtitle}</div>
        {extra}
      </div>
      <div style={s('display:flex;gap:10px;flex-shrink:0;padding-top:4px')}>{children}</div>
    </div>
  )
}

export function ExportButton({ onClick }: { onClick: () => void }) {
  return (
    <Hoverable base="display:inline-flex;align-items:center;gap:7px;background:var(--bg1);border:1px solid var(--fnt3);color:var(--tx);border-radius:999px;padding:9px 20px;font-size:13.5px;font-weight:600;cursor:pointer" hover="background:var(--acTint2);border-color:var(--ac)" onClick={onClick}>
      <RawSvg html={svg(P.download, 'width:15px;height:15px;flex-shrink:0')} />Export CSV · 出力
    </Hoverable>
  )
}
