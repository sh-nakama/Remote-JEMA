// Ported from screens/capacity-auctions.html — 4th JEMA screen (Capacity & Auctions).
import { useState } from 'react'
import { s, Hoverable, RawSvg } from '../lib/style'
import { useApp } from '../lib/app'
import { FreshnessChip, fmtStamp } from '../lib/freshness'
import { useManifest } from '../lib/data'
import { NotificationsPopover, useNotifSeen, unreadCount } from '../lib/notifications'
import type { NotifItem, NotifSection } from '../lib/notifications'
import { PolicyNavBadge } from '../lib/policyActivity'
import { segBase } from '../lib/chartkit'
import { maData, ltdaData, polData, MONTHS } from './CapacityAuctions.data'
import { useCapacityLive } from './CapacityAuctions.live'
import { downloadCsv } from '../lib/download'

type View = 'main' | 'ltda'

export function CapacityAuctionsScreen() {
  const { lang, setLang, theme, toggleTheme, setScreen, toast, openOverlay, collapsed, toggleCollapsed, watch, refreshData, refreshing } = useApp()
  const [view, setView] = useState<View>('main')
  const [showNotif, setShowNotif] = useState(false)

  const L = lang
  const dark = theme === 'dark'

  // Navigation handlers
  const goOverview = () => setScreen('overview')
  const goMarket = () => setScreen('market')
  const goPolicy = () => setScreen('policy')

  // Placeholder / toast handlers
  const tRefresh = () => {
    refreshData()
    toast('Reloaded latest data · 最新データを再取得しました')
  }
  const tNotif = () => setShowNotif((n) => !n)
  const tExport = () => {
    const rows = maSrc.map((m) => ({
      'Delivery FY': m.fy,
      'Auction held': m.held,
      'National (¥/kW)': m.natl,
      'Hokkaido (¥/kW)': m.hok,
      'Kyushu (¥/kW)': m.kyu,
      Procured: m.proc,
      'Achievement %': m.ach,
      Source: m.source ?? '',
    }))
    downloadCsv('jema-capacity-main-auction.csv', rows)
    toast('Downloaded main-auction results (CSV) · 約定結果をCSVで保存しました')
  }
  const tRow = () => {
    // No per-project detail is published in-app; open OCCTO's official capacity-market
    // section (the auction-results publications live under market-board/market/).
    window.open('https://www.occto.or.jp/market-board/market/index.html', '_blank', 'noopener,noreferrer')
    toast(L === 'ja' ? 'OCCTO 容量市場の公式ページを開きました' : 'Opened OCCTO’s official capacity-market page')
  }

  // Live curated capacity data (fixtures as loading fallback).
  const cap = useCapacityLive()
  const maSrc = cap.ready ? cap.ma : maData
  const ltdaSrc = cap.ready ? cap.ltda : ltdaData

  // Derived row data
  const maRows = maSrc.map((m) => ({
    ...m,
    bar: {
      display: 'block',
      width: m.ach + '%',
      height: '100%',
      borderRadius: 3,
      background: m.ach >= 99 ? 'var(--ac)' : '#EF9F27',
    } as React.CSSProperties,
  }))

  // ---- Main-auction KPI + price-chart model, derived from the live rows so
  // the cards and bar chart always agree with the results table. ----
  const numOf = (v: string | number | undefined): number => {
    if (typeof v === 'number') return v
    // Strip ¥ / commas / units. A non-numeric placeholder like "—" must become
    // NaN (not 0) — Number("") is 0, which would draw spurious zero-height bars.
    const cleaned = String(v ?? '').replace(/[^0-9.]/g, '')
    if (cleaned === '') return NaN
    const n = Number(cleaned)
    return Number.isFinite(n) ? n : NaN
  }
  const CH_Y0 = 270
  const CH_TOP = 14
  // Y-axis ceiling derived from the plotted prices instead of a hardcoded 16,000.
  // The hi-fi geometry keeps gridlines at fixed y (190/110/30) worth 1·/2·/3·step,
  // with the axis topping out at 3.2·step — so step 5,000 reproduces the export's
  // vmax 16,000 exactly (FY2029's ¥15,112 zonal clears sit just under the top).
  // Recomputing the step keeps future higher-priced rounds on-axis; the ladder
  // fallback (and the empty-data default) still lands on the original 5,000/16,000.
  const CH_STEP_LADDER = [500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000]
  const chDataMax = Math.max(
    0,
    ...maSrc
      .slice(0, 6)
      .flatMap((m) => [numOf(m.natl), numOf(m.hok), numOf(m.kyu)])
      .filter((n) => Number.isFinite(n)),
  )
  const chStep =
    chDataMax > 0
      ? CH_STEP_LADDER.find((st) => st * 3.2 >= chDataMax) ?? Math.ceil(chDataMax / 3.2 / 5000) * 5000
      : 5000
  const CH_VMAX = chStep * 3.2
  const yOf = (v: number) => CH_TOP + ((CH_VMAX - v) / CH_VMAX) * (CH_Y0 - CH_TOP)
  // Fixed x-slots per delivery-year column. Zonal bars are drawn wherever the row
  // carries distinct Hokkaido/Kyushu prices (FY2025+); FY2024 priced uniformly
  // ("—") is excluded by the isFinite guard in maChart below.
  const chSlots = [
    { x: 100.8, zonal: true },
    { x: 250.5, zonal: true },
    { x: 400.2, zonal: true },
    { x: 523.8, zonal: true },
    { x: 673.5, zonal: true },
    { x: 823.2, zonal: true },
  ]
  const maChart = maSrc.slice(0, 6).map((m, i) => {
    const slot = chSlots[i] ?? { x: 100.8 + i * 149.7, zonal: false }
    const nat = numOf(m.natl)
    const hok = numOf(m.hok)
    const kyu = numOf(m.kyu)
    return {
      fy: m.fy,
      x: slot.x,
      zonal: slot.zonal && Number.isFinite(hok) && Number.isFinite(kyu),
      nat,
      hok,
      kyu,
      natY: yOf(nat),
      natH: CH_Y0 - yOf(nat),
      hokY: yOf(hok),
      hokH: CH_Y0 - yOf(hok),
      kyuY: yOf(kyu),
      kyuH: CH_Y0 - yOf(kyu),
      natLabel: Number.isFinite(nat) ? nat.toLocaleString('en-US') : '—',
    }
  })
  const maLast = maSrc[maSrc.length - 1]
  const maPrev = maSrc[maSrc.length - 2]
  const deltaChip = (cur: number, prev: number) => {
    const d = cur - prev
    const pct = prev ? (d / prev) * 100 : 0
    const up = d >= 0
    return {
      txt:
        (up ? '▲ +' : '▼ −') +
        Math.abs(Math.round(d)).toLocaleString('en-US') +
        ' (' + (up ? '+' : '−') + Math.abs(pct).toFixed(1) + '%)',
      style: (up
        ? { background: 'var(--upBg)', color: 'var(--up)' }
        : { background: 'var(--dnBg)', color: 'var(--dn)' }) as React.CSSProperties,
    }
  }
  const hdDelta = deltaChip(numOf(maLast?.natl), numOf(maPrev?.natl))
  const hokDelta = deltaChip(numOf(maLast?.hok), numOf(maPrev?.hok))
  const kyuDelta = deltaChip(numOf(maLast?.kyu), numOf(maPrev?.kyu))

  // ---- notifications (bell popover) ----
  // Capacity data is event-driven (OCCTO publishes once per auction), so the
  // honest signals are: the newest published main-auction result, the running
  // LTDA total, and how fresh the export itself is. Only the auction result and
  // the export carry a real timestamp, so only those can count as unread.
  const manifest = useManifest()
  const { seenAt: notifSeenAt, markSeen: notifMarkSeen } = useNotifSeen('jema-notif-seen-capacity')

  /** "Jan 2026" → ms (UTC, 1st of month), or NaN. */
  const heldTs = (held: string | undefined): number => {
    const m = /^([A-Za-z]{3})\s+(\d{4})$/.exec((held ?? '').trim())
    const mi = m ? MONTHS.indexOf(m[1]) : -1
    return m && mi > 0 ? Date.UTC(Number(m[2]), mi - 1, 1) : NaN
  }

  const auctionItems: NotifItem[] = []
  if (maLast) {
    const held = heldTs(maLast.held)
    auctionItems.push({
      key: 'ma:' + maLast.fy,
      kind: 'done',
      title:
        L === 'ja'
          ? `${maLast.fy} メインオークション約定`
          : `${maLast.fy} main auction cleared`,
      meta: [
        (L === 'ja' ? '全国 ' : 'National ') + maLast.natl + '/kW',
        maPrev ? hdDelta.txt : null,
        maLast.proc + (L === 'ja' ? ' 約定' : ' procured'),
        (L === 'ja' ? '目標達成 ' : '') + maLast.ach + '%' + (L === 'ja' ? '' : ' of target'),
      ]
        .filter(Boolean)
        .join(' · '),
      badge: L === 'ja' ? '新規' : 'New',
      ts: Number.isFinite(held) ? held : undefined,
      onClick: () => {
        setShowNotif(false)
        if (maLast.source) window.open(maLast.source, '_blank', 'noopener,noreferrer')
        else tRow()
      },
    })
  }

  // Running LTDA total across the published rounds — a standing fact, not an
  // event, so it has no timestamp and never marks the bell unread.
  const ltdaTotal = ltdaSrc.reduce((n, t) => {
    const g = Number(String(t.cum).replace(/[^0-9.]/g, ''))
    return n + (Number.isFinite(g) ? g : 0)
  }, 0)
  const ltdaItems: NotifItem[] =
    ltdaTotal > 0
      ? [
          {
            key: 'ltda:total',
            kind: 'info',
            title:
              L === 'ja'
                ? `長期脱炭素電源オークション 累計 ${ltdaTotal.toFixed(2)} GW`
                : `Long-term decarbonisation auction · ${ltdaTotal.toFixed(2)} GW awarded`,
            meta:
              L === 'ja'
                ? `${ltdaSrc.length}技術 · 3ラウンド累計`
                : `${ltdaSrc.length} technologies · cumulative over 3 rounds`,
            onClick: () => {
              setView('ltda')
              setShowNotif(false)
            },
          },
        ]
      : []

  const dataItems: NotifItem[] = []
  const mf = manifest.data
  if (mf?.generated_at) {
    const exported = Date.parse(mf.generated_at)
    dataItems.push({
      key: 'freshness',
      kind: 'new',
      title: L === 'ja' ? 'スナップショットを更新しました' : 'Snapshot refreshed',
      meta: L === 'ja' ? `書出 ${fmtStamp(mf.generated_at)}` : `exported ${fmtStamp(mf.generated_at)}`,
      ts: Number.isFinite(exported) ? exported : undefined,
      onClick: tRefresh,
    })
  }

  const notifSections: NotifSection[] = [
    { key: 'auction', label: L === 'ja' ? '約定結果' : 'AUCTION RESULTS', items: auctionItems },
    { key: 'ltda', label: L === 'ja' ? '長期脱炭素電源オークション' : 'LONG-TERM DECARBONISATION', items: ltdaItems },
    { key: 'data', label: L === 'ja' ? 'データ更新' : 'DATA UPDATES', items: dataItems },
  ]
  const notifUnread = unreadCount(notifSections, notifSeenAt)

  const ltdaRows = ltdaSrc.map((t) => ({
    n1: L === 'ja' ? t.ja : t.en,
    n2: L === 'ja' ? t.en : t.ja,
    r1: t.r1,
    r2: t.r2,
    r3: t.r3,
    cum: t.cum,
    share: t.share,
    dot: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: dark ? t.cd : t.c,
      flexShrink: 0,
    } as React.CSSProperties,
    bar: {
      display: 'block',
      width: t.share + '%',
      height: '100%',
      borderRadius: 3,
      background: dark ? t.cd : t.c,
    } as React.CSSProperties,
  }))

  const tierColors: Record<'METI' | 'OCCTO', string> = {
    METI: 'var(--ac)',
    OCCTO: dark ? '#7C9CD1' : '#4A6FA5',
  }
  const polRows = polData.map((p) => ({
    n1: L === 'ja' ? p.ja : p.en,
    meta:
      L === 'ja'
        ? '第' + p.no + '回 · 2026年' + p.m + '月' + p.day + '日 · ' + p.tier
        : 'No. ' + p.no + ' · ' + p.day + ' ' + MONTHS[p.m] + ' 2026 · ' + p.tier,
    summary: L === 'ja' ? p.sJa : p.sEn,
    sched: !!p.sched,
    cta: p.sched
      ? L === 'ja'
        ? '議題を見る →'
        : 'View agenda →'
      : L === 'ja'
        ? '詳細を見る →'
        : 'Deep dive →',
    tierDot: {
      width: 9,
      height: 9,
      borderRadius: 999,
      background: tierColors[p.tier],
      flexShrink: 0,
      marginTop: 6,
    } as React.CSSProperties,
  }))

  return (
    <>
      {/* ============ SIDEBAR ============ */}
      <div style={s(`width:264px;flex-shrink:0;background:var(--bg1);border-right:1px solid var(--bd);flex-direction:column;padding:22px 16px 16px;overflow-y:auto;${collapsed ? 'display:none' : 'display:flex'}`)}>
        <div style={s('padding:0 8px')}>
          <div style={s('display:flex;align-items:center;gap:7px')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:23px;height:23px;color:var(--ac);flex-shrink:0"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`} />
            <span style={s("font-size:21px;font-weight:700;letter-spacing:.01em")}>JEMA</span>
          </div>
          <div style={s('font-size:9px;font-weight:600;letter-spacing:.14em;color:var(--mut);margin-top:3px;text-transform:uppercase')}>Japan Energy Market Analytics</div>
        </div>

        <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:26px 8px 8px')}>MENU · メニュー</div>
        <div style={s('display:flex;flex-direction:column;gap:3px')}>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={goOverview}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><rect x="3" y="3" width="7" height="9" rx="1"></rect><rect x="14" y="3" width="7" height="5" rx="1"></rect><rect x="14" y="12" width="7" height="9" rx="1"></rect><rect x="3" y="16" width="7" height="5" rx="1"></rect></svg>`} />
            <span>Market Overview</span>
            <span style={s('margin-left:auto;font-size:10.5px;font-weight:500;color:var(--mut)')}>概況</span>
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={goMarket}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><path d="M3 3v18h18"></path><path d="M8 17v-3"></path><path d="M13 17V9"></path><path d="M18 17V5"></path></svg>`} />
            <span>Market Data</span>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;margin-left:auto;color:var(--mut);flex-shrink:0"><path d="M9 18l6-6-6-6"></path></svg>`} />
          </Hoverable>
          <div style={s('display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:600;color:var(--acT);background:var(--acTint);cursor:pointer;position:relative')}>
            <span style={s('position:absolute;left:-16px;top:8px;bottom:8px;width:3px;background:var(--ac);border-radius:0 2px 2px 0')}></span>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><polygon points="12 2 22 8.5 12 15 2 8.5 12 2"></polygon><polyline points="2 14 12 20.5 22 14"></polyline></svg>`} />
            <span>Capacity &amp; Auctions</span>
            <span style={s('margin-left:auto;font-size:10.5px;font-weight:500;color:var(--acHi)')}>容量</span>
          </div>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={goPolicy}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><line x1="3" y1="22" x2="21" y2="22"></line><line x1="6" y1="18" x2="6" y2="11"></line><line x1="10" y1="18" x2="10" y2="11"></line><line x1="14" y1="18" x2="14" y2="11"></line><line x1="18" y1="18" x2="18" y2="11"></line><polygon points="12 2 20 7 4 7"></polygon></svg>`} />
            <span>Policy Deep Dive</span>
            <PolicyNavBadge />
          </Hoverable>
        </div>

        <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:22px 8px 8px')}>GENERAL · 全般</div>
        <div style={s('display:flex;flex-direction:column;gap:3px')}>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('watchlist')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon></svg>`} />
            <span>Watchlist</span>
            {watch.length > 0 && (
              <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>{watch.length}</span>
            )}
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={tNotif}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} />
            <span>Notifications</span>
            {notifUnread > 0 && (
              <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>{notifUnread}</span>
            )}
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('settings')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><circle cx="12" cy="12" r="3"></circle><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path></svg>`} />
            <span>Settings</span>
          </Hoverable>
        </div>

        <div style={s('flex:1')}></div>

        <Hoverable base="display:flex;align-items:center;gap:8px;padding:6px 12px;color:var(--mut);font-size:12px;cursor:pointer;border-radius:10px" hover="background:var(--bg2);color:var(--tx2)" onClick={toggleCollapsed}>
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;flex-shrink:0"><path d="M11 17l-5-5 5-5"></path><path d="M18 17l-5-5 5-5"></path></svg>`} />
          <span>Collapse · 折りたたむ</span>
        </Hoverable>

        <div style={s('background:linear-gradient(135deg,var(--navyA),var(--navyB));border-radius:16px;padding:15px 15px 13px;color:#FFFFFF;margin-top:12px')}>
          <div style={s("display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600")}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;color:#7FD4E8;flex-shrink:0"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14a9 3 0 0 0 18 0V5"></path><path d="M3 12a9 3 0 0 0 18 0"></path></svg>`} />Data freshness · データ鮮度
          </div>
          <div style={s("font-size:12px;color:rgba(255,255,255,.78);margin-top:6px")}>Last publication <span style={s("font-weight:600;color:#FFFFFF;font-feature-settings:'tnum' 1")}>2026-06-27</span></div>
          <FreshnessChip inverse style={{ marginTop: 2 }} />
          <div style={s('font-size:10.5px;color:rgba(255,255,255,.55);margin-top:2px')}>OCCTO auction results · event-driven, not daily</div>
          <Hoverable base="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.35);color:#FFFFFF;border-radius:999px;padding:5px 13px;font-size:12px;font-weight:500;cursor:pointer;margin-top:10px" hover="background:rgba(255,255,255,.10)" onClick={tRefresh}>
            <span style={s(refreshing ? 'display:inline-flex;animation:jema-spin .7s linear infinite' : 'display:inline-flex')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;flex-shrink:0"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>`} /></span>Refresh · 更新
          </Hoverable>
        </div>
      </div>

      {/* ============ MAIN COLUMN ============ */}
      <div style={s('flex:1;min-width:0;display:flex;flex-direction:column;position:relative')}>

        {/* Top bar */}
        <div style={s('height:72px;flex-shrink:0;background:var(--bg1);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:18px;padding:0 28px;position:relative;z-index:30')}>
          <div style={s('font-size:13px;color:var(--mut);flex-shrink:0')}>Capacity &amp; Auctions <span style={s('color:var(--fnt3)')}>·</span> 容量市場・オークション</div>
          <div onClick={() => openOverlay('search')} style={s('flex:1;max-width:520px;display:flex;align-items:center;gap:9px;background:var(--bg0);border:1px solid var(--bd);border-radius:12px;padding:8px 14px;color:var(--mut);cursor:text')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;flex-shrink:0"><circle cx="11" cy="11" r="8"></circle><path d="M21 21l-4.35-4.35"></path></svg>`} />
            <input readOnly onFocus={() => openOverlay('search')} placeholder="Search markets, areas, committees… 市場・エリア・委員会を検索…" style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:13px;background:transparent;color:var(--tx);min-width:0;cursor:text')} />
            <span style={s('border:1px solid var(--bd2);background:var(--bg1);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--mut);flex-shrink:0')}>⌘K</span>
          </div>
          <div style={s('flex:1')}></div>
          <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;flex-shrink:0" hover="background:var(--bg2)" onClick={toggleTheme} title="Toggle theme · テーマ切替" aria-label="Toggle theme">
            {dark && (
              <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`} />
            )}
            {!dark && (
              <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`} />
            )}
          </Hoverable>
          <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;position:relative;flex-shrink:0" hover="background:var(--bg2)" onClick={tNotif} aria-label="Notifications">
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} />
            {notifUnread > 0 && (
              <span style={s('position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:999px;background:var(--ac);border:1.5px solid var(--bg1)')}></span>
            )}
          </Hoverable>
          <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;flex-shrink:0')}>
            <span style={segBase(L === 'ja')} onClick={() => setLang('ja')}>日本語</span>
            <span style={segBase(L === 'en')} onClick={() => setLang('en')}>English</span>
          </div>
          <div style={s('display:flex;align-items:center;gap:10px;flex-shrink:0')}>
            <div style={s('width:34px;height:34px;border-radius:999px;background:var(--avatar);color:#FFFFFF;display:flex;align-items:center;justify-content:center;font-size:11.5px;font-weight:600')}>AN</div>
            <div style={s('line-height:1.25')}>
              <div style={s('font-size:13px;font-weight:600')}>Analyst</div>
              <div style={s('font-size:11px;color:var(--mut)')}>analyst@example.jp</div>
            </div>
          </div>

          {/* Notifications — newest auction result, LTDA total, snapshot freshness */}
          <NotificationsPopover
            open={showNotif}
            lang={L}
            sections={notifSections}
            seenAt={notifSeenAt}
            onClose={() => setShowNotif(false)}
            onMarkRead={notifMarkSeen}
            action={{
              label: L === 'ja' ? 'OCCTO 公式ページ →' : 'OCCTO results →',
              onClick: () => {
                setShowNotif(false)
                tRow()
              },
            }}
          />
        </div>

        {/* Scrollable content */}
        <div style={s('flex:1;overflow-y:auto;padding:26px 32px 40px')}>
          <div style={s('max-width:1500px;margin:0 auto;display:flex;flex-direction:column;gap:20px')}>

            {/* Page header */}
            <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:16px')}>
              <div>
                <div style={s('display:flex;align-items:baseline;gap:10px')}>
                  <span style={s('font-size:26px;font-weight:700;letter-spacing:-.01em')}>Capacity &amp; Auctions</span>
                  <span style={s('font-size:15px;font-weight:500;color:var(--mut)')}>容量市場・オークション</span>
                </div>
                <div style={s('font-size:13.5px;color:var(--tx2);margin-top:2px')}>Main auction results &amp; long-term decarbonization auctions (LTDA) · メインオークションと長期脱炭素電源オークション</div>
              </div>
              <div style={s('display:flex;gap:10px;flex-shrink:0;padding-top:4px')}>
                <Hoverable base="display:inline-flex;align-items:center;gap:7px;background:var(--bg1);border:1px solid var(--fnt3);color:var(--tx);border-radius:999px;padding:9px 20px;font-size:13.5px;font-weight:600;cursor:pointer" hover="background:var(--acTint2);border-color:var(--ac)" onClick={tExport}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;flex-shrink:0"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`} />Export CSV · 出力
                </Hoverable>
              </div>
            </div>

            {/* Sub-view switcher */}
            <div style={s('display:flex;align-items:center;gap:14px;flex-wrap:wrap')}>
              <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                <span style={segBase(view === 'main')} onClick={() => setView('main')}>Main Auction メインオークション</span>
                <span style={segBase(view === 'ltda')} onClick={() => setView('ltda')}>LTDA 長期脱炭素</span>
              </div>
              <span style={s('font-size:11.5px;color:var(--mut)')}>Event-driven OCCTO publications — not a daily feed · 公表ベース（日次更新ではありません）</span>
            </div>

            {/* ================= MAIN AUCTION VIEW ================= */}
            {view === 'main' && (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>{maLast?.fy} clearing price<br />約定価格（全国）</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{numOf(maLast?.natl).toLocaleString('en-US')} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>¥/kW·year</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>main auction {maLast?.held} · vs {maPrev?.fy}</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{hdDelta.txt}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Procured capacity<br />調達容量</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{numOf(maLast?.proc).toFixed(1)} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>GW</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{maLast?.ach}% of target · {maLast?.fy} delivery</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;font-feature-settings:'tnum' 1;background:rgba(138,147,163,.14);color:var(--mut)")}>{maLast?.ach}% of target 目標比</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Hokkaido zone<br />北海道エリア</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{numOf(maLast?.hok).toLocaleString('en-US')} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>separate zone · limited TTC north</div>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, fontWeight: 600, padding: '3px 9px', borderRadius: 999, marginTop: 9, fontFeatureSettings: "'tnum' 1", ...hokDelta.style }}>{hokDelta.txt}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Kyushu zone<br />九州エリア</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{numOf(maLast?.kyu).toLocaleString('en-US')} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>separate zone · solar-heavy south</div>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, fontWeight: 600, padding: '3px 9px', borderRadius: 999, marginTop: 9, fontFeatureSettings: "'tnum' 1", ...kyuDelta.style }}>{kyuDelta.txt}</span>
                  </div>
                </div>

                {/* Clearing price chart */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Clearing Price by Delivery Year <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>実需給年度別 約定価格</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Main auction · ¥/kW·year · Hokkaido &amp; Kyushu cleared as separate zones since FY2025 · 北海道・九州は別価格</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px;flex-shrink:0')}>auction held ~4 years ahead of delivery</span>
                  </div>
                  <svg viewBox="0 0 960 300" style={s('width:100%;height:auto;display:block;margin-top:10px')}>
                    <g style={s('color:var(--grid)')}>
                      <line x1="46" y1="30" x2="944" y2="30" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="110" x2="944" y2="110" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="190" x2="944" y2="190" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="270" x2="944" y2="270" stroke="currentColor" strokeWidth="1"></line>
                    </g>
                    <g style={s('color:var(--mut)')}>
                      <text x="38" y="34" textAnchor="end" fontSize="11" fill="currentColor">{(chStep * 3).toLocaleString('en-US')}</text>
                      <text x="38" y="114" textAnchor="end" fontSize="11" fill="currentColor">{(chStep * 2).toLocaleString('en-US')}</text>
                      <text x="38" y="194" textAnchor="end" fontSize="11" fill="currentColor">{chStep.toLocaleString('en-US')}</text>
                      <text x="120.8" y="292" textAnchor="middle" fontSize="11" fill="currentColor">FY2024</text>
                      <text x="270.5" y="292" textAnchor="middle" fontSize="11" fill="currentColor">FY2025</text>
                      <text x="420.2" y="292" textAnchor="middle" fontSize="11" fill="currentColor">FY2026</text>
                      <text x="569.8" y="292" textAnchor="middle" fontSize="11" fill="currentColor">FY2027</text>
                      <text x="719.5" y="292" textAnchor="middle" fontSize="11" fill="currentColor">FY2028</text>
                      <text x="869.2" y="292" textAnchor="middle" fontSize="11" fill="currentColor">FY2029</text>
                    </g>
                    {maChart.map((c) => (
                      <g key={c.fy}>
                        <rect x={c.x} y={c.natY} width="40" height={c.natH} rx="4" fill="#00A5CF">
                          <title>{`${c.fy} · National ¥${c.natLabel}/kW`}</title>
                        </rect>
                        {c.zonal && (
                          <>
                            <rect x={c.x + 46} y={c.hokY} width="18" height={c.hokH} rx="3" fill="#4A6FA5">
                              <title>{`${c.fy} · Hokkaido ¥${c.hok.toLocaleString('en-US')}/kW`}</title>
                            </rect>
                            <rect x={c.x + 68} y={c.kyuY} width="18" height={c.kyuH} rx="3" fill="#8AB17D">
                              <title>{`${c.fy} · Kyushu ¥${c.kyu.toLocaleString('en-US')}/kW`}</title>
                            </rect>
                          </>
                        )}
                        <text x={c.x + 20} y={c.natY - 6} fontSize="10.5" fontWeight="600" textAnchor="middle" style={{ fill: 'var(--tx2)' }}>{c.natLabel}</text>
                      </g>
                    ))}
                  </svg>
                  <div style={s('display:flex;align-items:center;gap:16px;margin-top:10px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap;font-size:11.5px;color:var(--tx2)')}>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#00A5CF')}></span>National 全国</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#4A6FA5')}></span>Hokkaido 北海道</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#8AB17D')}></span>Kyushu 九州</span>
                    <span style={s('margin-left:auto;color:var(--mut)')}>FY2024 cleared near the price cap · FY2024は上限価格近傍</span>
                  </div>
                </div>

                {/* Results table */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Auction Results <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>約定結果一覧</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Main auction by delivery year · prices before 経過措置 adjustments</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>¥/kW·year · GW</span>
                  </div>
                  <div style={s("display:grid;grid-template-columns:.8fr .8fr .9fr .9fr .9fr .9fr 1.3fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)")}>
                    <span>DELIVERY 年度</span><span>HELD 実施</span><span style={s('text-align:right')}>NATIONAL 全国</span><span style={s('text-align:right')}>HOKKAIDO</span><span style={s('text-align:right')}>KYUSHU</span><span style={s('text-align:right')}>PROCURED 調達</span><span style={s('text-align:right')}>ACHIEVEMENT 達成率</span>
                  </div>
                  {maRows.map((m) => (
                    <Hoverable key={m.fy} base="display:grid;grid-template-columns:.8fr .8fr .9fr .9fr .9fr .9fr 1.3fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer" hover="background:var(--hov)" onClick={() => (m.source ? window.open(m.source, '_blank', 'noopener') : tRow())}>
                      <span style={s("font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>{m.fy}</span>
                      <span style={s("font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{m.held}</span>
                      <span style={s("text-align:right;font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>{m.natl}</span>
                      <span style={s("text-align:right;font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{m.hok}</span>
                      <span style={s("text-align:right;font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{m.kyu}</span>
                      <span style={s("text-align:right;font-size:12.5px;font-feature-settings:'tnum' 1")}>{m.proc}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:72px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={m.bar}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{m.ach}%</span>
                      </span>
                    </Hoverable>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>Achievement = procured ÷ target capacity 調達容量÷目標調達量 · click a year for the full OCCTO publication</div>
                </div>
              </div>
            )}

            {/* ================= LTDA VIEW ================= */}
            {view === 'ltda' && (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>Round 3 awarded<br />第3回 落札容量</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>5.24 <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>GW</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>results Jun 2026 · 84 projects</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>▲ +0.39 GW vs Round 2</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Battery storage share<br />蓄電池シェア</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>32<span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>%</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>1.68 GW in R3 · largest single tech</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;font-feature-settings:'tnum' 1;background:rgba(138,147,163,.14);color:var(--mut)")}>R1: 27% · R2: 34%</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Cumulative awarded<br />累計落札</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>14.10 <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>GW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>3 rounds · COD FY2027–FY2034</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;font-feature-settings:'tnum' 1;background:var(--upBg);color:var(--up)")}>storage (battery + pumped) 40%</span>
                  </div>
                  <Hoverable base="background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);cursor:pointer;transition:box-shadow .15s" hover="box-shadow:var(--sh2)" onClick={goPolicy}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Round 4 window<br />第4回 応札期間</div>
                    <div style={s('font-size:33px;font-weight:700;margin-top:10px;line-height:1.15')}>Nov 2026</div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>requirements under committee review · 要件審議中</div>
                    <span style={s('display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;background:var(--acTint);color:var(--acT)')}>storage threshold open in committee →</span>
                  </Hoverable>
                </div>

                {/* Stacked tech chart */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Awarded Capacity by Technology <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>技術別落札容量</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>LTDA rounds 1–3 · GW · 20-year fixed revenue contracts · 20年間の固定収入契約</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px;flex-shrink:0')}>hover a segment for detail</span>
                  </div>
                  <svg viewBox="0 0 960 300" style={s('width:100%;height:auto;display:block;margin-top:10px')}>
                    <g style={s('color:var(--grid)')}>
                      <line x1="46" y1="14" x2="944" y2="14" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="99.3" x2="944" y2="99.3" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="184.7" x2="944" y2="184.7" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="270" x2="944" y2="270" stroke="currentColor" strokeWidth="1"></line>
                    </g>
                    <g style={s('color:var(--mut)')}>
                      <text x="38" y="18" textAnchor="end" fontSize="11" fill="currentColor">6 GW</text>
                      <text x="38" y="103" textAnchor="end" fontSize="11" fill="currentColor">4 GW</text>
                      <text x="38" y="188" textAnchor="end" fontSize="11" fill="currentColor">2 GW</text>
                      <text x="216" y="292" textAnchor="middle" fontSize="11" fill="currentColor">Round 1 · results 2024</text>
                      <text x="495" y="292" textAnchor="middle" fontSize="11" fill="currentColor">Round 2 · results 2025</text>
                      <text x="774" y="292" textAnchor="middle" fontSize="11" fill="currentColor">Round 3 · results 2026</text>
                    </g>
                    <rect x="161" y="223.1" width="110" height="46.9" fill="#00A5CF"><title>R1 · Battery 1.10 GW</title></rect>
                    <rect x="161" y="198.8" width="110" height="24.3" fill="#4A6FA5"><title>R1 · Pumped hydro 0.57 GW</title></rect>
                    <rect x="161" y="104.9" width="110" height="93.9" fill="#E9C46A"><title>R1 · LNG decarb-ready 2.20 GW</title></rect>
                    <rect x="161" y="98.9" width="110" height="6" fill="#2A9D8F"><title>R1 · H2/NH3 0.14 GW</title></rect>
                    <rect x="440" y="200" width="110" height="70" fill="#00A5CF"><title>R2 · Battery 1.64 GW</title></rect>
                    <rect x="440" y="187.2" width="110" height="12.8" fill="#4A6FA5"><title>R2 · Pumped hydro 0.30 GW</title></rect>
                    <rect x="440" y="78.4" width="110" height="108.8" fill="#E9C46A"><title>R2 · LNG decarb-ready 2.55 GW</title></rect>
                    <rect x="440" y="63" width="110" height="15.4" fill="#2A9D8F"><title>R2 · H2/NH3 0.36 GW</title></rect>
                    <rect x="719" y="198.3" width="110" height="71.7" fill="#00A5CF"><title>R3 · Battery 1.68 GW</title></rect>
                    <rect x="719" y="180.4" width="110" height="17.9" fill="#4A6FA5"><title>R3 · Pumped hydro 0.42 GW</title></rect>
                    <rect x="719" y="82.3" width="110" height="98.1" fill="#E9C46A"><title>R3 · LNG decarb-ready 2.30 GW</title></rect>
                    <rect x="719" y="55.8" width="110" height="26.5" fill="#2A9D8F"><title>R3 · H2/NH3 0.62 GW</title></rect>
                    <rect x="719" y="46.4" width="110" height="9.4" fill="#B4BCC9"><title>R3 · Other 0.22 GW</title></rect>
                    <g fontSize="11" fontWeight="600" textAnchor="middle" style={s('fill:var(--tx2)')}>
                      <text x="216" y="90">4.01 GW</text>
                      <text x="495" y="54">4.85 GW</text>
                      <text x="774" y="38">5.24 GW</text>
                    </g>
                  </svg>
                  <div style={s('display:flex;align-items:center;gap:16px;margin-top:10px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap;font-size:11.5px;color:var(--tx2)')}>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#00A5CF')}></span>Battery 蓄電池</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#4A6FA5')}></span>Pumped 揚水</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#E9C46A')}></span>LNG decarb-ready LNG（脱炭素化前提）</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#2A9D8F')}></span>H2 · NH3 水素・アンモニア</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:12px;height:12px;border-radius:4px;background:#B4BCC9')}></span>Other その他</span>
                  </div>
                </div>

                {/* Tech table */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Technology Breakdown <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>技術別内訳</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Awarded GW per round · cumulative share of all LTDA awards</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>GW</span>
                  </div>
                  <div style={s("display:grid;grid-template-columns:1.7fr .6fr .6fr .6fr .7fr 1.3fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)")}>
                    <span>TECHNOLOGY · 電源</span><span style={s('text-align:right')}>ROUND 1</span><span style={s('text-align:right')}>ROUND 2</span><span style={s('text-align:right')}>ROUND 3</span><span style={s('text-align:right')}>CUMULATIVE 累計</span><span style={s('text-align:right')}>SHARE シェア</span>
                  </div>
                  {ltdaRows.map((t, i) => (
                    <Hoverable key={i} base="display:grid;grid-template-columns:1.7fr .6fr .6fr .6fr .7fr 1.3fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer" hover="background:var(--hov)" onClick={tRow}>
                      <span style={s('display:flex;align-items:center;gap:9px;min-width:0')}>
                        <span style={t.dot}></span>
                        <span style={s('font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{t.n1} <span style={s('font-weight:400;color:var(--mut);font-size:11.5px')}>{t.n2}</span></span>
                      </span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{t.r1}</span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{t.r2}</span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{t.r3}</span>
                      <span style={s("text-align:right;font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>{t.cum}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:72px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={t.bar}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{t.share}%</span>
                      </span>
                    </Hoverable>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>Battery threshold lowered to 10 MW from Round 2 · 第2回から蓄電池の応札下限は10MWに引き下げ</div>
                </div>
              </div>
            )}

            {/* Policy thread (always visible) */}
            <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
              <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                <div>
                  <div style={s('display:flex;align-items:center;gap:9px')}>
                    <span style={s('font-size:16px;font-weight:600')}>Policy Thread — Storage × Capacity Market <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>政策スレッド：蓄電池×容量市場</span></span>
                  </div>
                  <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Committee decisions shaping the next auction rounds · 次回オークションに影響する審議</div>
                </div>
                <Hoverable as="span" base="font-size:12.5px;font-weight:600;color:var(--acT);cursor:pointer;white-space:nowrap;padding-top:4px" hover="color:var(--ac)" onClick={goPolicy}>Open Policy Deep Dive →</Hoverable>
              </div>
              <div style={s('display:flex;flex-direction:column;margin-top:8px')}>
                {polRows.map((p, i) => (
                  <Hoverable key={i} base="display:flex;gap:12px;align-items:flex-start;padding:12px 4px;border-top:1px solid var(--dv);cursor:pointer;border-radius:8px" hover="background:var(--hov)" onClick={goPolicy}>
                    <span style={p.tierDot}></span>
                    <div style={s('flex:1;min-width:0')}>
                      <div style={s('display:flex;align-items:center;gap:8px;min-width:0')}>
                        <span style={s('font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{p.n1}</span>
                        {p.sched && (
                          <span style={s('font-size:10.5px;font-weight:600;background:var(--upBg);color:var(--up);border-radius:6px;padding:1px 7px;flex-shrink:0')}>Scheduled 開催予定</span>
                        )}
                      </div>
                      <div style={s("font-size:11.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-feature-settings:'tnum' 1")}>{p.meta}</div>
                      <div style={s('font-size:12.5px;color:var(--tx2);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{p.summary}</div>
                    </div>
                    <span style={s('font-size:12.5px;font-weight:600;color:var(--acT);white-space:nowrap;flex-shrink:0;padding-top:2px')}>{p.cta}</span>
                  </Hoverable>
                ))}
              </div>
            </div>

            <div style={s('font-size:12px;color:var(--mut);text-align:center;padding:2px 0 6px')}>Published by OCCTO · 容量市場・長期脱炭素電源オークション約定結果 · event-driven · last publication 2026-06-27</div>

          </div>
        </div>
      </div>
    </>
  )
}
