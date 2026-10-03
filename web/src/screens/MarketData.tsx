// Ported from screens/market-data.html — the Market Data screen. The view model is in MarketData.view.ts.
import { Fragment, useEffect, useMemo, useState } from 'react'
import { s, Hoverable, RawSvg, press } from '../lib/style'
import { useApp } from '../lib/app'
import { fmtStamp, STALE_MS, SampleTag } from '../lib/freshness'
import { useManifest } from '../lib/data'
import { NotificationsPopover, useNotifSeen, unreadCount, tsOfDate } from '../lib/notifications'
import type { NotifItem, NotifSection } from '../lib/notifications'
import { Sidebar, TopBar, PageHeader, ExportButton, useReload } from '../lib/chrome'
import { ChartFrame } from '../lib/chart'
import { downloadCsv } from '../lib/download'
import { areas } from './MarketData.data'
import { BalancingAreaGrid } from './BalancingAreaGrid'
import { FUELS, useWholesaleLive, useDriversLive, useBalancingLive, useTielineLive, useAreaDayLive } from './MarketData.live'
import { buildMarketView, fmtDT, fmtEpoch } from './MarketData.view'
import type { Domain, DrRange, Gran, Range, View } from './MarketData.view'

export function MarketDataScreen() {
  const { lang, theme, setScreen, toast, focusArea, clearFocusArea, defaultGran, isWatched, toggleWatch } = useApp()
  const L = lang
  const dark = theme === 'dark'

  const [view, setView] = useState<View>('wholesale')
  const [range, setRange] = useState<Range>('60D')
  const [gran, setGran] = useState<Gran>(defaultGran)
  const [sel, setSel] = useState<Record<string, boolean>>(Object.fromEntries(areas.map((a) => [a.key, true])))
  const [closed, setClosed] = useState<Record<string, boolean>>({})
  // Per-area expanded view: adds a full-width combined generation-mix + price chart
  // underneath the side-by-side pair.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  // Per-area drag-selected zoom window (epoch ms). Each area zooms independently;
  // unzoomed areas keep the range-derived window.
  const [zoom, setZoom] = useState<Record<string, Domain>>({})
  const [drRange, setDrRange] = useState<DrRange>('90D')
  const [drOn, setDrOn] = useState<{ lng: boolean; brent: boolean; fx: boolean }>({ lng: true, brent: true, fx: true })
  // Compare overlay (period-over-period) + inline drill-down accordions.
  const [compare, setCompare] = useState(false)
  const [expandedLine, setExpandedLine] = useState<string | null>(null)
  const [expandedProduct, setExpandedProduct] = useState<string | null>(null)
  // Notifications popover (bell).
  const [showNotif, setShowNotif] = useState(false)

  const toggleArea = (key: string) =>
    setSel((prev) => {
      const next = { ...prev }
      if (next[key]) delete next[key]
      else next[key] = true
      return next
    })
  const toggleSec = (key: string) => setClosed((prev) => ({ ...prev, [key]: !prev[key] }))
  const toggleExpand = (key: string) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))
  const setAreaZoom = (key: string, d: Domain) => setZoom((prev) => ({ ...prev, [key]: d }))
  const clearZoom = (key: string) =>
    setZoom((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  const resetAll = () => {
    setRange('60D')
    setGran('Daily')
    setSel(Object.fromEntries(areas.map((a) => [a.key, true])))
    setClosed({})
    setExpanded({})
    setZoom({})
  }

  // A zoom window is expressed in absolute time, so it stops describing anything
  // the controls say once the range or granularity changes — drop it instead of
  // leaving charts on a window the chips contradict.
  useEffect(() => {
    setZoom({})
  }, [range, gran])

  // The ⌘K palette / Watchlist can ask us to focus a specific area: switch to
  // the wholesale view and ensure that area is selected, then clear the request.
  useEffect(() => {
    if (!focusArea) return
    setView('wholesale')
    setSel((prev) => ({ ...prev, [focusArea]: true }))
    clearFocusArea()
  }, [focusArea, clearFocusArea])

  // ---- handlers (toasts) ----
  const granN = () => setGran('Native')
  const granD = () => setGran('Daily')
  const granW = () => setGran('Weekly')
  const granM = () => setGran('Monthly')
  const tExport = () => {
    if (!live.ready) {
      toast('Data still loading — try again in a moment · データ読込中です')
      return
    }
    const rows: Record<string, unknown>[] = []
    // Window the export to the active Range (matches the on-screen chart), instead
    // of dumping the full history. dt is newest-first (index 0 = latest period).
    const days = { '7D': 7, '30D': 30, '60D': 60, '1Y': 365 }[range]
    const cutoffFrom = (latest: string): string => {
      const d = new Date(latest.slice(0, 10) + 'T00:00:00Z')
      d.setUTCDate(d.getUTCDate() - (days - 1))
      return d.toISOString().slice(0, 10)
    }
    for (const key of selectedKeys) {
      const a = live.areas[key]
      if (!a) continue
      const label = areas.find((x) => x.key === key)?.en || key
      const num = (x: number) => (Number.isFinite(x) ? x : '')
      const cutoff = a.dt.length ? cutoffFrom(a.dt[0]) : ''
      // avg/max/min are aligned to dt at the current granularity (dAvg/dMax are
      // the gran-independent Daily series used only for KPIs — not for export).
      for (let i = 0; i < a.dt.length; i++) {
        if (cutoff && a.dt[i].slice(0, 10) < cutoff) continue // outside the Range window
        rows.push({
          datetime: a.dt[i],
          area: label,
          avg_price_yen_kwh: num(a.avg[i]),
          max_price_yen_kwh: num(a.max[i]),
          min_price_yen_kwh: num(a.min[i]),
        })
      }
    }
    if (!rows.length) {
      toast('Nothing to export for the current selection · 対象データがありません')
      return
    }
    downloadCsv(`jema-wholesale-${gran}-${range}.csv`, rows)
    toast(`Downloaded ${rows.length.toLocaleString('en-US')} rows (CSV) · CSVで保存しました`)
  }
  const tCompare = () => setCompare((prev) => !prev)
  const tLine = (key: string) => setExpandedLine((prev) => (prev === key ? null : key))
  const tSystem = () => toast('System-weighted series = PROPOSED (data exists, aggregation not wired) · システム系列は提案中')
  const tProduct = (code: string) => setExpandedProduct((prev) => (prev === code ? null : code))
  const toggleNotif = () => setShowNotif((n) => !n)
  const tRefresh = useReload()
  const tLng = () => setDrOn((p) => ({ ...p, lng: !p.lng }))
  const tBrent = () => setDrOn((p) => ({ ...p, brent: !p.brent }))
  const tFx = () => setDrOn((p) => ({ ...p, fx: !p.fx }))

  const selectedKeys = areas.filter((a) => sel[a.key]).map((a) => a.key)
  const live = useWholesaleLive(selectedKeys, gran)
  const driversLive = useDriversLive()
  const balLive = useBalancingLive()
  const tielineLive = useTielineLive('DAM')
  const areaDayLive = useAreaDayLive()

  // ---- notifications (bell popover) ----
  // Derived from what this screen already holds: the export manifest (how fresh
  // the snapshot is) and the loaded area series (day-on-day moves). JEMA has no
  // alert service, so anything not derivable from a snapshot is deliberately
  // absent rather than faked.
  const manifest = useManifest()
  const { seenAt: notifSeenAt, markSeen: notifMarkSeen } = useNotifSeen('jema-notif-seen-market')
  const MOVE_PCT = 10 // day-on-day threshold for "notable" (JEPX daily averages swing a few % routinely)

  const dataItems: NotifItem[] = []
  const mf = manifest.data
  if (mf?.generated_at) {
    const priceDate = mf.sources?.area_price || mf.sources?.system_price || null
    const supplyDate = mf.sources?.supply || null
    const priceTs = tsOfDate(priceDate || mf.generated_at)
    const stale = Number.isFinite(priceTs) && Date.now() - priceTs > STALE_MS
    dataItems.push({
      key: 'freshness',
      kind: stale ? 'warn' : 'new',
      title: stale
        ? L === 'ja' ? '価格データが48時間以上更新されていません' : 'Prices are more than 48 hours old'
        : L === 'ja' ? `価格データ ${priceDate ?? '—'} まで` : `Prices through ${priceDate ?? '—'}`,
      meta: [
        supplyDate ? (L === 'ja' ? `需給 ${supplyDate} まで` : `supply through ${supplyDate}`) : null,
        L === 'ja' ? `書出 ${fmtStamp(mf.generated_at)}` : `exported ${fmtStamp(mf.generated_at)}`,
      ]
        .filter(Boolean)
        .join(' · '),
      ts: Date.parse(mf.generated_at),
      onClick: tRefresh,
    })
  }

  // Day-on-day move of each loaded area's daily average (index 0 = latest day).
  // Only selected areas are fetched, so this covers exactly what's on screen.
  type Move = { pct: number; item: NotifItem }
  const moveItems: NotifItem[] = selectedKeys
    .map((key): Move | null => {
      const a = live.areas[key]
      if (!a || a.dAvg.length < 2) return null
      const now = a.dAvg[0]
      const prev = a.dAvg[1]
      if (!Number.isFinite(now) || !Number.isFinite(prev) || prev === 0) return null
      const pct = ((now - prev) / Math.abs(prev)) * 100
      if (Math.abs(pct) < MOVE_PCT) return null
      const def = areas.find((x) => x.key === key)
      const day = (a.dDt[0] || '').slice(0, 10)
      return {
        pct,
        item: {
          key: 'move:' + key,
          kind: 'new',
          title: `${(L === 'ja' ? def?.ja : def?.en) ?? key} · ¥${now.toFixed(2)}/kWh`,
          meta: `${pct > 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}% ${L === 'ja' ? '前日比' : 'vs previous day'}${day ? ' · ' + day : ''}`,
          badge: isWatched('area:' + key) ? '★' : undefined,
          ts: tsOfDate(day),
          onClick: () => {
            setView('wholesale')
            setSel((p) => ({ ...p, [key]: true }))
            setShowNotif(false)
          },
        },
      }
    })
    .filter((x): x is Move => x != null)
    .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
    .slice(0, 5)
    .map((x) => x.item)

  const notifSections: NotifSection[] = [
    { key: 'data', label: L === 'ja' ? 'データ更新' : 'DATA UPDATES', items: dataItems },
    {
      key: 'moves',
      label: L === 'ja' ? `大きな変動 · 前日比${MOVE_PCT}%以上` : `NOTABLE MOVES · ≥${MOVE_PCT}% day-on-day`,
      items: moveItems,
    },
  ]
  const notifUnread = unreadCount(notifSections, notifSeenAt)


  // ---- computed (mirror of renderVals) ----
  const v = useMemo(
    () => buildMarketView({ view, range, gran, sel, closed, expanded, zoom, drRange, drOn, L, dark, live, driversLive, balLive, tielineLive, areaDayLive }),
    [view, range, gran, sel, closed, expanded, zoom, drRange, drOn, L, dark, live, driversLive, balLive, tielineLive, areaDayLive],
  )

  // ---- section renderers ----
  // Mechanical extraction for navigability: each renderer holds one section's
  // JSX verbatim (same closures over state/`v`) and is called from the single
  // return at the bottom — the rendered tree is identical.

  // Sub-view switcher (Wholesale / Balancing · Interconnectors / Drivers)
  const renderViewSwitcher = () => (
            <div style={s('display:flex;align-items:center;gap:14px;flex-wrap:wrap')}>
              <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                <span style={v.vwWS} {...press(() => setView('wholesale'), view === 'wholesale')}>Wholesale (Spot) 卸電力</span>
                <span style={v.vwBS} {...press(() => setView('balancing'), view === 'balancing')}>Balancing 需給調整</span>
              </div>
              <span style={s('color:var(--fnt3)')}>·</span>
              <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                <span style={v.vwIS} {...press(() => setView('interco'), view === 'interco')}>Interconnectors 連系線</span>
                <span style={v.vwDS} {...press(() => setView('drivers'), view === 'drivers')}>Drivers 燃料・為替</span>
              </div>
            </div>
  )

  // Control bar: range / area chips / granularity (spot & balancing only)
  const renderControlBar = () => (
              <div style={s('background:var(--bg1);border-radius:16px;padding:12px 16px;box-shadow:var(--sh1);display:flex;align-items:center;gap:12px;flex-wrap:wrap')}>
                <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                  <span style={v.r7S} {...press(() => setRange('7D'), range === '7D')}>7D</span>
                  <span style={v.r30S} {...press(() => setRange('30D'), range === '30D')}>30D</span>
                  <span style={v.r60S} {...press(() => setRange('60D'), range === '60D')}>60D</span>
                  <span style={v.r1yS} {...press(() => setRange('1Y'), range === '1Y')}>1Y</span>
                </div>
                <span style={s('width:1px;height:22px;background:var(--dv)')}></span>
                <span style={s('font-size:12px;color:var(--mut);flex-shrink:0')}>Areas エリア</span>
                <div style={s('display:flex;gap:6px;flex-wrap:wrap;align-items:center')}>
                  {v.areaChips.map((a) => (
                    <span key={a.key} style={a.s} {...press(() => toggleArea(a.key), !!sel[a.key])}>{a.label}</span>
                  ))}
                  <span style={s('font-size:11.5px;font-weight:600;padding:3px 11px;border-radius:999px;cursor:pointer;border:1px dashed var(--fnt2);background:transparent;color:var(--fnt);white-space:nowrap')} {...press(tSystem)} title="System series = PROPOSED · システム系列は提案中">System <span style={s('font-size:9px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:5px;padding:0 4px;margin-left:2px')}>P</span></span>
                </div>
                <span style={s('width:1px;height:22px;background:var(--dv)')}></span>
                <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                  <span style={v.gNS} {...press(granN, gran === 'Native')}>Native 30分</span>
                  <span style={v.gDS} {...press(granD, gran === 'Daily')}>Daily</span>
                  <span style={v.gWS} {...press(granW, gran === 'Weekly')}>Weekly</span>
                  <span style={v.gMS} {...press(granM, gran === 'Monthly')}>Monthly</span>
                </div>
                {v.rangeClampNote ? (
                  <span style={s("font-size:10.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:999px;padding:2px 10px;white-space:nowrap;font-feature-settings:'tnum' 1")}>{v.rangeClampNote}</span>
                ) : null}
                <span style={s('margin-left:auto;display:flex;gap:8px;align-items:center')}>
                  <Hoverable as="span" base={compare ? 'font-size:12px;font-weight:600;color:var(--ac);cursor:pointer;white-space:nowrap' : 'font-size:12px;font-weight:600;color:var(--acT);cursor:pointer;white-space:nowrap'} hover="color:var(--ac)" onClick={tCompare} title={L === 'ja' ? '前期間を重ねて比較' : 'Overlay the previous equal-length period'}>{compare ? '✓ ' : ''}Compare 比較</Hoverable>
                  <span style={s('color:var(--fnt3)')}>·</span>
                  <Hoverable as="span" base="font-size:12px;font-weight:500;color:var(--mut);cursor:pointer;white-space:nowrap" hover="color:var(--tx2)" onClick={resetAll}>Reset リセット</Hoverable>
                </span>
              </div>
  )

  // ================= WHOLESALE VIEW =================
  const renderWholesaleView = () => (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                {/* KPI row */}
                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>Avg clearing price<br />平均約定価格</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.kAvg} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>¥/kWh</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>{v.kAvgSub}</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{v.kAvgD}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Peak price<br />最高価格</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.kPeak} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kWh</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{v.kPeakSub}</div>
                    <span style={v.kPeakDS}>{v.kPeakD}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Peak demand<br />最大需要</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.kDem} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>MW</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{v.kDemSub}</div>
                    <span style={v.kDemDS}>{v.kDemD}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);position:relative')}>
                    <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                      <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Renewable share<br />再エネ比率</div>
                      <span style={s('font-size:9.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:6px;padding:1px 7px;flex-shrink:0')}>PROPOSED</span>
                    </div>
                    <div style={s('font-size:33px;font-weight:700;margin-top:10px;color:var(--fnt2);line-height:1.15')}>—</div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>Mix data exists · % aggregation not wired · 集計未接続</div>
                  </div>
                </div>

                {/* Price heatmap */}
                {v.showHeat && (
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                      <div>
                        <div style={s('display:flex;align-items:center;gap:9px')}>
                          <span style={s('font-size:16px;font-weight:600')}>Price Heatmap <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>価格ヒートマップ</span></span>
                          <span style={s('font-size:9.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:6px;padding:1px 7px')}>PROPOSED · new component</span>
                        </div>
                        <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Area × 30-min slot · today {v.heatDate} · ¥/kWh · deselected areas dimmed</div>
                      </div>
                      <div style={s('display:flex;align-items:center;gap:5px;font-size:11px;color:var(--mut);flex-shrink:0;padding-top:4px')}>
                        <span>low</span>
                        <span style={s('width:16px;height:10px;background:#9FE1CB;border-radius:2px')}></span>
                        <span style={s('width:16px;height:10px;background:#5DCAA5;border-radius:2px')}></span>
                        <span style={s('width:16px;height:10px;background:#FAC775;border-radius:2px')}></span>
                        <span style={s('width:16px;height:10px;background:#EF9F27;border-radius:2px')}></span>
                        <span style={s('width:16px;height:10px;background:#E24B4A;border-radius:2px')}></span>
                        <span>high</span>
                      </div>
                    </div>
                    <div style={s('display:flex;flex-direction:column;gap:4px;margin-top:14px')}>
                      {v.heatRows.map((hr) => (
                        <div key={hr.key} style={s('display:flex;align-items:center;gap:10px;cursor:pointer')} {...press(() => toggleArea(hr.key), !!sel[hr.key])} title="Click to toggle area · クリックで選択切替">
                          <span style={hr.labS}>{hr.label}</span>
                          <div style={s('flex:1;display:grid;grid-template-columns:repeat(48,1fr);gap:2px')}>
                            {hr.cells.map((c, ci) => (
                              <span key={ci} style={c.s} title={c.t}></span>
                            ))}
                          </div>
                        </div>
                      ))}
                      <div style={s('display:flex;align-items:center;gap:10px')}>
                        <span style={s('width:104px;flex-shrink:0')}></span>
                        <div style={s("flex:1;display:flex;justify-content:space-between;font-size:10.5px;color:var(--mut);font-feature-settings:'tnum' 1")}><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:30</span></div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Per-area sections */}
                {v.sections.map((sec) => (
                  <div key={sec.key} style={s('display:flex;flex-direction:column;gap:10px')}>
                    <div style={s('display:flex;align-items:center;gap:10px')}>
                      <span style={s('background:var(--bg1);border:1px solid var(--bd);border-radius:999px;padding:4px 14px;font-size:12.5px;font-weight:600')}>{sec.title} <span style={s('font-weight:400;color:var(--mut)')}>{sec.sub}</span></span>
                      <Hoverable as="span" base="width:26px;height:26px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--mut);cursor:pointer" hover="background:var(--bg2);color:var(--tx2)" onClick={() => toggleSec(sec.key)} title="Collapse / expand · 折りたたみ" aria-label={sec.open ? 'Collapse section' : 'Expand section'}>
                        {sec.open && (<RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><path d="M18 15l-6-6-6 6"></path></svg>`} />)}
                        {sec.closed && (<RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><path d="M6 9l6 6 6-6"></path></svg>`} />)}
                      </Hoverable>
                      <Hoverable as="span" base={`width:26px;height:26px;border-radius:999px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:${isWatched('area:' + sec.key) ? 'var(--ac)' : 'var(--fnt)'}`} hover="background:var(--bg2)" onClick={() => { const am = areas.find((x) => x.key === sec.key); toggleWatch({ id: 'area:' + sec.key, kind: 'area', en: am?.en || sec.key, ja: am?.ja || sec.key, screen: 'market' }) }} title={isWatched('area:' + sec.key) ? 'Remove from watchlist · ウォッチリストから削除' : 'Add to watchlist · ウォッチリストに追加'} aria-label={isWatched('area:' + sec.key) ? 'Remove from watchlist' : 'Add to watchlist'}><RawSvg html={`<svg viewBox="0 0 24 24" fill="${isWatched('area:' + sec.key) ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon></svg>`} /></Hoverable>
                      <span style={s("font-size:11.5px;color:var(--mut);margin-left:auto;font-feature-settings:'tnum' 1")}>{sec.meta}</span>
                      {sec.zoomLabel ? (
                        <Hoverable
                          as="span"
                          base="display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;background:var(--acTint);color:var(--acT);border:1px solid var(--ac);border-radius:999px;padding:2px 10px;cursor:pointer;white-space:nowrap"
                          hover="background:var(--acTint2)"
                          onClick={() => clearZoom(sec.key)}
                          title="Clear zoom · ズーム解除"
                          aria-label={`Clear zoom ${sec.zoomLabel}`}
                        >
                          <span style={s("font-feature-settings:'tnum' 1")}>{sec.zoomLabel}</span>
                          <span aria-hidden="true">✕</span>
                        </Hoverable>
                      ) : null}
                      <Hoverable
                        as="span"
                        base={`font-size:11px;font-weight:600;border:1px solid ${sec.expanded ? 'var(--ac)' : 'var(--bd2)'};background:${sec.expanded ? 'var(--acTint)' : 'var(--bg1)'};color:${sec.expanded ? 'var(--acT)' : 'var(--mut)'};border-radius:999px;padding:2px 11px;cursor:pointer;white-space:nowrap`}
                        hover="background:var(--hov)"
                        onClick={() => toggleExpand(sec.key)}
                        title="Combined generation mix + price chart · 電源構成と価格の重ね合わせ"
                        aria-label={sec.expanded ? 'Collapse combined chart' : 'Expand combined chart'}
                      >
                        {sec.expanded ? 'Collapse 縮小' : 'Expand 拡大'}
                      </Hoverable>
                    </div>
                    {sec.open && (
                      <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:20px')}>
                        <div style={s('background:var(--bg1);border-radius:20px;padding:18px 20px;box-shadow:var(--sh1)')}>
                          <div style={s('display:flex;justify-content:space-between;align-items:baseline')}>
                            <span style={s('font-size:14px;font-weight:600')}>Generation mix <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>電源構成</span></span>
                            <span style={s('font-size:11px;color:var(--mut)')}>{sec.mixMeta}</span>
                          </div>
                          <ChartFrame
                            n={sec.supN}
                            label={(i) => fmtDT(sec.supDt[i] ?? '')}
                            xs={sec.supXs}
                            dotY={(i) => 152 - (sec.supDemandA[i] / sec.supYmax) * 140}
                            onBrush={sec.canZoom ? (x0, x1) => setAreaZoom(sec.key, [sec.tOfX(x0), sec.tOfX(x1)]) : undefined}
                            brushLabel={(x0, x1) => `${fmtEpoch(sec.tOfX(x0))} → ${fmtEpoch(sec.tOfX(x1))}`}
                            onReset={() => clearZoom(sec.key)}
                            tip={(i) => (
                              <>
                                {FUELS.map((f, k) => (sec.supFuelA[k][i] >= 1 ? (
                                  <span key={f.key} style={s(`display:inline-block;margin-right:8px;color:${f.c === '#1B2A4A' || f.c === '#3A3A3A' ? 'inherit' : f.c}`)}>{f.en} {Math.round(sec.supFuelA[k][i]).toLocaleString('en-US')}</span>
                                ) : null))}
                                <span>dem {Math.round(sec.supDemandA[i]).toLocaleString('en-US')} MW</span>
                              </>
                            )}
                          >
                            {sec.mixPolys.map((segs, k) => segs.map((p, pi) => (<polygon key={'m' + k + '-' + pi} points={p} fill={FUELS[k].c} fillOpacity="0.85"></polygon>)))}
                            <g style={s('color:var(--tx)')}>{sec.demand.map((p, pi) => (<polyline key={'d' + pi} points={p} fill="none" stroke="currentColor" strokeWidth="1.8" strokeDasharray="1 0"></polyline>))}</g>
                          </ChartFrame>
                          <div style={s("display:flex;justify-content:space-between;padding:0 1.67%;margin-top:5px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                            <span>{sec.mixAx[0]}</span><span>{sec.mixAx[1]}</span><span>{sec.mixAx[2]}</span>
                          </div>
                          {sec.supStale ? (
                            <div style={s("font-size:10.5px;color:var(--warnTx);background:var(--warnBg);border-radius:6px;padding:2px 8px;margin-top:6px;display:inline-block;font-feature-settings:'tnum' 1")}>Supply data {sec.supStale} · 供給データ遅延</div>
                          ) : null}
                          <div style={s('display:flex;align-items:center;gap:14px;margin-top:9px;font-size:11px;color:var(--tx2);flex-wrap:wrap')}>
                            {sec.fuelLegend.map((f) => (<span key={f.key} style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s(`width:10px;height:10px;border-radius:3px;background:${f.c}`)}></span>{f.en} {f.ja}</span>))}
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid var(--tx)')}></span>Demand 需要</span>
                            <span style={s("margin-left:auto;font-feature-settings:'tnum' 1;color:var(--mut)")}>peak {sec.peakMW} MW</span>
                          </div>
                        </div>
                        <div style={s('background:var(--bg1);border-radius:20px;padding:18px 20px;box-shadow:var(--sh1)')}>
                          <div style={s('display:flex;justify-content:space-between;align-items:baseline')}>
                            <span style={s('font-size:14px;font-weight:600')}>Price <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>価格</span></span>
                            <span style={s('font-size:11px;color:var(--mut)')}>{sec.rangeLabel} · {sec.granLabel} · max / avg / min · ¥/kWh</span>
                          </div>
                          <ChartFrame
                            n={sec.n}
                            label={(i) => fmtDT(sec.pdt[i] ?? '')}
                            xs={sec.pxs}
                            dotY={sec.pDotY}
                            onBrush={sec.canZoom ? (x0, x1) => setAreaZoom(sec.key, [sec.tOfX(x0), sec.tOfX(x1)]) : undefined}
                            brushLabel={(x0, x1) => `${fmtEpoch(sec.tOfX(x0))} → ${fmtEpoch(sec.tOfX(x1))}`}
                            onReset={() => clearZoom(sec.key)}
                            tip={(i) => (
                              <>
                                <span style={s('color:#E24B4A')}>max ¥{sec.pmax[i].toFixed(2)}</span>
                                {' · '}
                                <span>avg ¥{sec.pavg[i].toFixed(2)}</span>
                                {' · '}
                                <span style={s('color:#00A5CF')}>min ¥{sec.pmin[i].toFixed(2)}</span>
                              </>
                            )}
                          >
                            {sec.band.map((p, pi) => (<polygon key={'b' + pi} points={p} fill="#00A5CF" fillOpacity="0.10"></polygon>))}
                            {sec.pMax.map((p, pi) => (<polyline key={'x' + pi} points={p} fill="none" stroke="#E24B4A" strokeWidth="1.6"></polyline>))}
                            <g style={s('color:var(--tx)')}>{sec.pAvg.map((p, pi) => (<polyline key={'a' + pi} points={p} fill="none" stroke="currentColor" strokeWidth="1.8"></polyline>))}</g>
                            {sec.pMin.map((p, pi) => (<polyline key={'i' + pi} points={p} fill="none" stroke="#00A5CF" strokeWidth="1.6"></polyline>))}
                            {compare
                              ? sec.pCmp.map((p, pi) => (<polyline key={'c' + pi} points={p} fill="none" stroke="var(--mut)" strokeWidth="1.5" strokeDasharray="4 3" strokeOpacity="0.85"></polyline>))
                              : null}
                          </ChartFrame>
                          <div style={s("display:flex;justify-content:space-between;padding:0 1.67%;margin-top:5px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                            <span>{sec.priceAx[0]}</span><span>{sec.priceAx[1]}</span><span>{sec.priceAx[2]}</span>
                          </div>
                          {sec.priceStale ? (
                            <div style={s("font-size:10.5px;color:var(--warnTx);background:var(--warnBg);border-radius:6px;padding:2px 8px;margin-top:6px;display:inline-block;font-feature-settings:'tnum' 1")}>Price data {sec.priceStale} · 価格データ遅延</div>
                          ) : null}
                          <div style={s("display:flex;align-items:center;gap:14px;margin-top:9px;font-size:11px;color:var(--tx2);flex-wrap:wrap;font-feature-settings:'tnum' 1")}>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid #E24B4A')}></span>Max ¥{sec.vMax}</span>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid var(--tx)')}></span>Avg ¥{sec.vAvg}</span>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid #00A5CF')}></span>Min ¥{sec.vMin}</span>
                            {compare && sec.pCmp.length ? (
                              <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px dashed var(--mut)')}></span>{L === 'ja' ? '前期間 avg' : 'Prev period avg'}</span>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    )}
                    {sec.open && sec.expanded && (
                      <div style={s('background:var(--bg1);border-radius:20px;padding:18px 20px;box-shadow:var(--sh1)')}>
                        <div style={s('display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap')}>
                          <span style={s('font-size:14px;font-weight:600')}>Generation mix &amp; price <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>電源構成と価格</span></span>
                          <span style={s('font-size:11px;color:var(--mut)')}>{sec.rangeLabel} · {sec.granLabel} · MW (left) · ¥/kWh (right) · drag to zoom · ドラッグで範囲選択</span>
                        </div>
                        <div style={s('display:flex;align-items:stretch;gap:8px;margin-top:2px')}>
                          <div style={s("display:flex;flex-direction:column;justify-content:space-between;width:52px;flex-shrink:0;padding:12px 0 14px;text-align:right;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                            {sec.mwTicks.map((t, ti) => (<span key={ti}>{t}</span>))}
                          </div>
                          <div style={s('flex:1;min-width:0')}>
                            <ChartFrame
                              n={sec.cmbN}
                              height={sec.expH}
                              cssHeight={360}
                              label={(i) => fmtDT(sec.cmbDt[i] ?? '')}
                              xs={sec.cmbXs}
                              dotY={sec.expDotY}
                              onBrush={sec.canZoom ? (x0, x1) => setAreaZoom(sec.key, [sec.tOfX(x0), sec.tOfX(x1)]) : undefined}
                              brushLabel={(x0, x1) => `${fmtEpoch(sec.tOfX(x0))} → ${fmtEpoch(sec.tOfX(x1))}`}
                              onReset={() => clearZoom(sec.key)}
                              tip={(i) => {
                                const si = sec.cmbSupIdx[i]
                                const pi2 = sec.cmbPriceIdx[i]
                                return (
                                  <>
                                    {si >= 0 && sec.supDemandA[si] != null ? (
                                      <>
                                        {FUELS.map((f, k) => (sec.supFuelA[k][si] >= 1 ? (
                                          <span key={f.key} style={s(`display:inline-block;margin-right:8px;color:${f.c === '#1B2A4A' || f.c === '#3A3A3A' ? 'inherit' : f.c}`)}>{f.en} {Math.round(sec.supFuelA[k][si]).toLocaleString('en-US')}</span>
                                        ) : null))}
                                        <span>dem {Math.round(sec.supDemandA[si]).toLocaleString('en-US')} MW</span>
                                      </>
                                    ) : null}
                                    {si >= 0 && pi2 >= 0 && sec.pavg[pi2] != null ? ' │ ' : null}
                                    {pi2 >= 0 && sec.pavg[pi2] != null ? (
                                      <>
                                        <span style={s('color:#E24B4A')}>max ¥{sec.pmax[pi2].toFixed(2)}</span>
                                        {' · '}
                                        <span>avg ¥{sec.pavg[pi2].toFixed(2)}</span>
                                        {' · '}
                                        <span style={s('color:#00A5CF')}>min ¥{sec.pmin[pi2].toFixed(2)}</span>
                                      </>
                                    ) : null}
                                  </>
                                )
                              }}
                            >
                              {sec.expMixPolys.map((segs, k) => segs.map((p, pi) => (<polygon key={'em' + k + '-' + pi} points={p} fill={FUELS[k].c} fillOpacity="0.7"></polygon>)))}
                              <g style={s('color:var(--tx2)')}>{sec.expDemand.map((p, pi) => (<polyline key={'ed' + pi} points={p} fill="none" stroke="currentColor" strokeWidth="1.4" strokeOpacity="0.75"></polyline>))}</g>
                              {sec.expBand.map((p, pi) => (<polygon key={'eb' + pi} points={p} fill="#00A5CF" fillOpacity="0.10"></polygon>))}
                              {sec.expPMax.map((p, pi) => (<polyline key={'ex' + pi} points={p} fill="none" stroke="#E24B4A" strokeWidth="1.6"></polyline>))}
                              <g style={s('color:var(--tx)')}>{sec.expPAvg.map((p, pi) => (<polyline key={'ea' + pi} points={p} fill="none" stroke="currentColor" strokeWidth="2"></polyline>))}</g>
                              {sec.expPMin.map((p, pi) => (<polyline key={'ei' + pi} points={p} fill="none" stroke="#00A5CF" strokeWidth="1.6"></polyline>))}
                            </ChartFrame>
                            <div style={s("display:flex;justify-content:space-between;padding:0 1.67%;margin-top:5px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                              <span>{sec.priceAx[0]}</span><span>{sec.priceAx[1]}</span><span>{sec.priceAx[2]}</span>
                            </div>
                          </div>
                          <div style={s("display:flex;flex-direction:column;justify-content:space-between;width:46px;flex-shrink:0;padding:12px 0 14px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                            {sec.yenTicks.map((t, ti) => (<span key={ti}>¥{t}</span>))}
                          </div>
                        </div>
                        <div style={s('display:flex;align-items:center;gap:14px;margin-top:9px;font-size:11px;color:var(--tx2);flex-wrap:wrap')}>
                          {sec.fuelLegend.map((f) => (<span key={f.key} style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s(`width:10px;height:10px;border-radius:3px;background:${f.c}`)}></span>{f.en} {f.ja}</span>))}
                          <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid var(--tx2)')}></span>Demand 需要 (MW)</span>
                          <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid #E24B4A')}></span>Max ¥{sec.vMax}</span>
                          <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid var(--tx)')}></span>Avg ¥{sec.vAvg}</span>
                          <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid #00A5CF')}></span>Min ¥{sec.vMin}</span>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                <div style={s('font-size:12px;color:var(--mut);text-align:center;padding:2px 0 6px')}>{v.hiddenNote}</div>
              </div>
  )

  // ================= BALANCING VIEW =================
  const renderBalancingView = () => (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>
                <div style={s('display:grid;grid-template-columns:repeat(3,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>Weighted avg ΔkW price<br />加重平均ΔkW価格</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.balAvgPrice} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>¥/ΔkW·30min</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>all products · nationwide · {v.balDate} vs prior day<SampleTag failed={balLive.failed} /></div>
                    {v.balPriceChip && (
                      <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{v.balPriceChip}</span>
                    )}
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Procured volume<br />調達量合計</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.balProcTot} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>MW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>5 products · average over the day&apos;s slots · vs prior day<SampleTag failed={balLive.failed} /></div>
                    {v.balProcChip && <span style={v.balProcChip.style}>{v.balProcChip.txt}</span>}
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Shortfall slots<br />調達不足コマ</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.balShort} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>/ {v.balSlots}</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>{v.balShortSub}<SampleTag failed={balLive.failed} /></div>
                    {v.balShortChip && <span style={v.balShortChip.style}>{v.balShortChip.txt}</span>}
                  </div>
                </div>

                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Balancing Products <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>需給調整市場 商品別<SampleTag failed={balLive.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>EPRX · {v.balDate} · averages over the day&apos;s 30-min slots · nationwide procurement</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>¥/ΔkW·30min · MW</span>
                  </div>
                  <div style={s('display:grid;grid-template-columns:1.5fr .8fr .8fr .8fr 1.1fr .7fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)')}>
                    <span>PRODUCT · 商品</span><span style={s('text-align:right')}>AVG PRICE</span><span style={s('text-align:right')}>PROCURED</span><span style={s('text-align:right')}>OFFERED</span><span style={s('text-align:right')}>ACHIEVEMENT 達成率</span><span style={s('text-align:right')}>SHORT 不足</span>
                  </div>
                  {v.balRows.map((b, bi) => (
                    <Fragment key={bi}>
                    <Hoverable base={expandedProduct === b.code ? 'display:grid;grid-template-columns:1.5fr .8fr .8fr .8fr 1.1fr .7fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer;background:var(--hov)' : 'display:grid;grid-template-columns:1.5fr .8fr .8fr .8fr 1.1fr .7fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer'} hover="background:var(--hov)" onClick={() => tProduct(b.code)}>
                      <span style={s('display:flex;align-items:center;gap:9px;min-width:0')}>
                        <span style={b.dot}></span>
                        <span style={s('font-size:13px;font-weight:600;white-space:nowrap')}>{expandedProduct === b.code ? '▾ ' : '▸ '}{b.jp} <span style={s('font-weight:400;color:var(--mut);font-size:11.5px')}>{b.en}</span></span>
                      </span>
                      <span style={s("text-align:right;font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>¥{b.price}</span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{b.proc}</span>
                      <span style={s("text-align:right;font-size:13px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{b.off}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:72px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={b.bar}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{b.ach}</span>
                      </span>
                      <span style={s('text-align:right')}><span style={b.shortS}>{b.shortTxt}</span></span>
                    </Hoverable>
                    {expandedProduct === b.code ? (
                      <div style={s('padding:11px 10px 14px;border-bottom:1px solid var(--dv);background:var(--bg0)')}>
                        <div style={s('font-size:12px;font-weight:600;margin-bottom:8px')}>{L === 'ja' ? 'エリア別 調達内訳' : 'Procurement by TSO area'} <span style={s('font-weight:400;color:var(--mut);font-size:11px')}>{b.jp} {b.en}</span></div>
                        {b.areaRows.length ? (
                          <>
                            <div style={s('display:grid;grid-template-columns:1.4fr .9fr .9fr .9fr .8fr;gap:0;font-size:10.5px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 6px 6px;border-bottom:1px solid var(--dv)')}>
                              <span>AREA · エリア</span><span style={s('text-align:right')}>AVG PRICE</span><span style={s('text-align:right')}>PROCURED</span><span style={s('text-align:right')}>OFFERED</span><span style={s('text-align:right')}>達成率</span>
                            </div>
                            {b.areaRows.map((r) => (
                              <div key={r.area} style={s('display:grid;grid-template-columns:1.4fr .9fr .9fr .9fr .8fr;gap:0;align-items:center;padding:6px;border-bottom:1px solid var(--dv)')}>
                                <span style={s('font-size:12px;font-weight:500')}>{r.name}</span>
                                <span style={s("text-align:right;font-size:12px;font-weight:600;font-feature-settings:'tnum' 1")}>{r.price}</span>
                                <span style={s("text-align:right;font-size:12px;font-feature-settings:'tnum' 1")}>{r.proc}</span>
                                <span style={s("text-align:right;font-size:12px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{r.off}</span>
                                <span style={s("text-align:right;font-size:12px;font-feature-settings:'tnum' 1")}>{r.ach != null ? r.ach + '%' : '—'}</span>
                              </div>
                            ))}
                            <div style={s('font-size:10.5px;color:var(--mut);margin-top:7px')}>{L === 'ja' ? '最新日の30分コマ平均（¥/ΔkW·30min · MW）· 達成率＝調達量／応札量（広域調達のため他エリアの応札を使うと100%を超えます）' : 'Per-area averages over the latest day\'s slots (¥/ΔkW·30min · MW) · achievement = procured / offered, above 100% where an area drew on other areas\' offers (procurement is nationwide)'}</div>
                          </>
                        ) : (
                          <div style={s('font-size:11.5px;color:var(--mut)')}>{L === 'ja' ? 'エリア別データは読込中です。' : 'Per-area data still loading.'}</div>
                        )}
                      </div>
                    ) : null}
                    </Fragment>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>一次=primary FCR · 二次=secondary AFC/RR · 三次=tertiary replacement · prices weighted by contracted MW · short = slots where national procurement fell below the requirement · 価格は約定量加重平均 · 不足＝全国の約定量が必要量を下回ったコマ</div>
                </div>
                <BalancingAreaGrid sel={sel} gran={gran} range={range} L={L} />
              </div>
  )

  // ================= INTERCONNECTORS VIEW =================
  const renderIntercoView = () => (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>Lines at their limit<br />上限に達した連系線</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.icAtN} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>/ {v.icLimN} lines</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>reserved ≥97% of the limit in any slot · {v.icDate}<SampleTag failed={tielineLive.failed} /></div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{v.icAtChip}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Highest share of limit<br />最高確保率</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.icTopPct}<span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>%</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>{v.icTopLabel}<SampleTag failed={tielineLive.failed} /></div>
                    <span style={v.icWarnChip}>{v.icTopChip}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Widest area spread<br />最大エリア価格差</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.icSpread} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>/kWh</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>{v.icSpreadSub}<SampleTag failed={areaDayLive.failed} /></div>
                    <span style={v.icChipN}>JEPX day-ahead · 前日スポット</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Reserved on average<br />平均確保量</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.icResAvg} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>MW</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>vs {v.icLimAvg} MW of limits · all lines, both directions<SampleTag failed={tielineLive.failed} /></div>
                    <span style={v.icChipN}>{v.icResPct}% of the limits reserved</span>
                  </div>
                </div>

                {/* Reservation map */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Balancing Reservations — 9 Areas <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>連系線の調整力確保<SampleTag failed={tielineLive.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>ΔkW reserved on each line for cross-area balancing, at its peak slot · labels in MW · line width ∝ reservation limit · EPRX {v.icDate}</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px;flex-shrink:0')}>node prices = JEPX area daily average ¥/kWh · {v.areaDate}<SampleTag failed={areaDayLive.failed} /></span>
                  </div>
                  <svg viewBox="0 0 960 360" style={s('width:100%;height:auto;display:block;margin-top:8px')}>
                    <rect x="366" y="80" width="258" height="174" rx="18" fill="none" style={s('stroke:var(--mut)')} strokeDasharray="5 4" opacity="0.7"></rect>
                    <text x="495" y="72" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>Chubu · Hokuriku · Kansai: combined zones 合成エリア</text>
                    <text x="495" y="160" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icCombN} combined lines · peak {v.icCombPeak}%</text>
                    <text x="495" y="175" textAnchor="middle" fontSize="9.5" style={s('fill:var(--mut)')}>see the table below · 詳細は下表</text>
                    {v.icMap.map((m) => (
                      <line key={m.key} x1={m.x1} y1={m.y1} x2={m.x2} y2={m.y2} stroke={m.col} strokeWidth={m.w} strokeDasharray={m.dash}>
                        <title>{m.title}</title>
                      </line>
                    ))}
                    {v.icMap.filter((m) => m.has).map((m) => (
                      <g key={m.key}>
                        <circle cx={m.mx} cy={m.my} r="8" style={s('fill:var(--bg1)')} stroke={m.col} strokeWidth="1.5"></circle>
                        <text x={m.mx} y={m.my} transform={`rotate(${m.ang} ${m.mx} ${m.my})`} textAnchor="middle" dominantBaseline="central" fontSize="9" fill={m.arrowCol}>▶</text>
                      </g>
                    ))}
                    {v.icMap.map((m) => (
                      <text key={m.key} x={m.lx} y={m.ly} textAnchor={m.anchor} fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{m.label}</text>
                    ))}
                    <text x="640" y="218" textAnchor="middle" fontSize="9" style={s('fill:var(--mut)')}>50/60 Hz</text>
                    {v.icNodes.map((n) => (
                      <g key={n.key}>
                        {n.acc && <rect x={n.cx - 47} y={n.cy - 19} width="94" height="38" rx="12" style={s('fill:var(--bg1)')}></rect>}
                        <rect x={n.cx - 47} y={n.cy - 19} width="94" height="38" rx="12" style={s(n.acc ? 'fill:var(--acTint);stroke:var(--ac)' : 'fill:var(--bg3);stroke:var(--bd2)')}></rect>
                        <text x={n.cx} y={n.cy - 4} textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>{n.name}</text>
                        <text x={n.cx} y={n.cy + 11} textAnchor="middle" fontSize="10" fontWeight={n.pxBold ? 600 : undefined} style={{ fill: n.pxCol }}>¥{n.px}</text>
                      </g>
                    ))}
                  </svg>
                  <div style={s('display:flex;align-items:center;gap:16px;margin-top:8px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap;font-size:11.5px;color:var(--tx2)')}>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:14px;height:4px;border-radius:2px;background:#5DCAA5')}></span>&lt;55%</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:14px;height:4px;border-radius:2px;background:#FAC775')}></span>55–85%</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:14px;height:4px;border-radius:2px;background:#EF9F27')}></span>85–97%</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px;font-weight:600;color:var(--dn)')}><span style={s('width:14px;height:4px;border-radius:2px;background:#E24B4A')}></span>≥97% at the limit 上限到達</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:14px;height:0;border-top:2px dashed #B4BCC9')}></span>no reservation limit 上限なし</span>
                    <span style={s('margin-left:auto;color:var(--mut)')}>▶ = direction of the peak reservation · share of the reservation limit 確保上限に対する比率</span>
                  </div>
                </div>

                {/* Line table */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Interconnector Lines <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>連系線一覧<SampleTag failed={tielineLive.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Peak slot per line · EPRX {v.icDate} · spread = destination minus origin JEPX area price (daily average; combined zones use their areas&apos; mean) · 値差＝流入側−流出側</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>MW · ¥/kWh</span>
                  </div>
                  <div style={s('display:grid;grid-template-columns:1.6fr 1.2fr .55fr .55fr 1.2fr .6fr .8fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)')}>
                    <span>LINE · 連系線</span><span>ROUTE · 区間</span><span style={s('text-align:right')}>RESERVED</span><span style={s('text-align:right')}>LIMIT</span><span style={s('text-align:right')}>SHARE OF LIMIT 確保率</span><span style={s('text-align:right')}>SPREAD 値差</span><span style={s('text-align:right')}>AT LIMIT 上限</span>
                  </div>
                  {v.icRows.map((ln) => (
                    <Fragment key={ln.key}>
                    <Hoverable base={expandedLine === ln.key ? 'display:grid;grid-template-columns:1.6fr 1.2fr .55fr .55fr 1.2fr .6fr .8fr;gap:0;align-items:center;padding:9px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer;background:var(--hov)' : 'display:grid;grid-template-columns:1.6fr 1.2fr .55fr .55fr 1.2fr .6fr .8fr;gap:0;align-items:center;padding:9px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer'} hover="background:var(--hov)" onClick={() => tLine(ln.key)}>
                      <span style={s('min-width:0')}><span style={s('display:block;font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{expandedLine === ln.key ? '▾ ' : '▸ '}{ln.n1}</span><span style={s('display:block;font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{ln.n2}</span></span>
                      <span style={s('font-size:12px;color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{ln.route}</span>
                      <span style={s("text-align:right;font-size:12.5px;font-weight:600;font-feature-settings:'tnum' 1")}>{ln.reserved}</span>
                      <span style={s("text-align:right;font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{ln.limit}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:64px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={ln.barS}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{ln.pct}</span>
                      </span>
                      <span style={s("text-align:right;font-size:12.5px;font-weight:600;font-feature-settings:'tnum' 1")}>{ln.spread}</span>
                      <span style={s('text-align:right')}><span style={ln.atS}>{ln.atTxt}</span></span>
                    </Hoverable>
                    {expandedLine === ln.key ? (
                      <div style={s('padding:12px 10px 16px;border-bottom:1px solid var(--dv);background:var(--bg0)')}>
                        <div style={s('display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px;flex-wrap:wrap;gap:6px')}>
                          <span style={s('font-size:12.5px;font-weight:600')}>{L === 'ja' ? '30分コマ別の確保量／上限' : 'Reserved ÷ limit · 48 × 30-min slots'}</span>
                          <span style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>{ln.route} · {L === 'ja' ? 'ピーク' : 'peak'} {ln.pct}{ln.peakAt ? ' @ ' + ln.peakAt : ''} · {ln.reserved} / {ln.limit} MW · {L === 'ja' ? '値差' : 'spread'} {ln.spread}</span>
                        </div>
                        <div style={s('display:grid;grid-template-columns:repeat(48,1fr);gap:2px;align-items:end;height:64px')}>
                          {ln.bars.map((c, ci) => (
                            <span key={ci} title={c.t} style={{ ...c.barCol, height: c.h + '%' }}></span>
                          ))}
                        </div>
                        <div style={s("display:flex;justify-content:space-between;font-size:10.5px;color:var(--mut);margin-top:6px;font-feature-settings:'tnum' 1")}><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:30</span></div>
                        <div style={s('font-size:10.5px;color:var(--mut);margin-top:6px')}>{L === 'ja' ? 'バーの高さ＝確保上限に対する確保量の比率（各コマで比率の大きい方向）· ホバーでMW表示' : 'Bar height = share of the reservation limit, larger direction per slot · hover for MW'}</div>
                      </div>
                    ) : null}
                    </Fragment>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>Reserved = ΔkW set aside on the line for cross-area balancing procurement (EPRX) · limit = the most that may be reserved · neither is physical flow · click a line for its 48 slots</div>
                </div>

                {/* Congestion timeline */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Reservation Timeline <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>確保率タイムライン<SampleTag failed={tielineLive.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Share of the reservation limit by 30-min slot · EPRX {v.icDate} · 30分コマ別の確保率</div>
                    </div>
                    <div style={s('display:flex;align-items:center;gap:5px;font-size:11px;color:var(--mut);flex-shrink:0;padding-top:4px')}>
                      <span>low</span>
                      <span style={s('width:16px;height:10px;background:#9FE1CB;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#5DCAA5;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#FAC775;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#EF9F27;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#E24B4A;border-radius:2px')}></span>
                      <span>at limit</span>
                    </div>
                  </div>
                  <div style={s('display:flex;flex-direction:column;gap:4px;margin-top:14px')}>
                    {v.icRows.map((tl) => (
                      <div key={tl.key} style={s('display:flex;align-items:center;gap:10px')}>
                        <span style={s('width:158px;flex-shrink:0;font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{tl.short}</span>
                        <div style={s('flex:1;display:grid;grid-template-columns:repeat(48,1fr);gap:2px')}>
                          {tl.strip.map((c, ci) => (
                            <span key={ci} style={c.s} title={c.t}></span>
                          ))}
                        </div>
                        <span style={s("width:52px;flex-shrink:0;text-align:right;font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>{tl.atShort}</span>
                      </div>
                    ))}
                    <div style={s('display:flex;align-items:center;gap:10px')}>
                      <span style={s('width:158px;flex-shrink:0')}></span>
                      <div style={s("flex:1;display:flex;justify-content:space-between;font-size:10.5px;color:var(--mut);font-feature-settings:'tnum' 1")}><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:30</span></div>
                      <span style={s('width:52px;flex-shrink:0;text-align:right;font-size:10.5px;color:var(--mut)')}>≥97%</span>
                    </div>
                  </div>
                </div>
              </div>
  )

  // ================= DRIVERS VIEW =================
  const renderDriversView = () => (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>JKM LNG front-month<br />JKM（LNGスポット）</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.drLngV} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>$/MMBtu</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>JKM=F futures · close {v.drCloseDate} · vs prior close<SampleTag failed={driversLive.failed} /></div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{v.drLngC}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Brent crude<br />ブレント原油</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.drBrentV} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>$/bbl</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>BZ=F futures · front month · vs prior close<SampleTag failed={driversLive.failed} /></div>
                    <span style={v.drBrentCS}>{v.drBrentC}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>USD/JPY<br />ドル円</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.drFxV}</div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>JPY=X spot rate · weaker yen = costlier fuel imports<SampleTag failed={driversLive.failed} /></div>
                    <span style={v.drFxCS}>{v.drFxC}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                      <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Marginal fuel cost<br />限界燃料費指数</div>
                      <span style={s('font-size:9.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:6px;padding:1px 7px;flex-shrink:0')}>PROPOSED</span>
                    </div>
                    <div style={s('font-size:33px;font-weight:700;margin-top:10px;color:var(--fnt2);line-height:1.15')}>—</div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>LNG SRMC estimate · efficiency assumptions not wired · 換算前提未設定</div>
                  </div>
                </div>

                <div style={s('display:grid;grid-template-columns:2fr 1fr;gap:20px;align-items:stretch')}>
                  {/* Indexed overlay chart */}
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);display:flex;flex-direction:column')}>
                    <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                      <div>
                        <div style={s('font-size:16px;font-weight:600')}>Drivers vs Spot — Indexed <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>燃料・為替×スポット<SampleTag failed={driversLive.failed} /></span></div>
                        <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Rebased to 100 at window start · daily closes · spot = 9-area mean · 期初＝100</div>
                      </div>
                      <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;flex-shrink:0')}>
                        <span style={v.dr30S} {...press(() => setDrRange('30D'), drRange === '30D')}>30D</span>
                        <span style={v.dr90S} {...press(() => setDrRange('90D'), drRange === '90D')}>90D</span>
                        <span style={v.dr1yS} {...press(() => setDrRange('1Y'), drRange === '1Y')}>1Y</span>
                      </div>
                    </div>
                    <div style={s('flex:1;margin-top:14px')}>
                      <svg viewBox="0 0 960 320" style={s('width:100%;height:auto;display:block')}>
                        <g style={s('color:var(--grid)')}>
                          <line x1="46" y1="69" x2="944" y2="69" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                          <line x1="46" y1="138" x2="944" y2="138" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                          <line x1="46" y1="207" x2="944" y2="207" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                          <line x1="46" y1="276" x2="944" y2="276" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                        </g>
                        <g style={s('color:var(--mut)')}>
                          <text x="38" y="73" textAnchor="end" fontSize="11" fill="currentColor">{v.drG1}</text>
                          <text x="38" y="142" textAnchor="end" fontSize="11" fill="currentColor">{v.drG2}</text>
                          <text x="38" y="211" textAnchor="end" fontSize="11" fill="currentColor">{v.drG3}</text>
                          <text x="38" y="280" textAnchor="end" fontSize="11" fill="currentColor">{v.drG4}</text>
                          <text x="46" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">{v.drX0}</text>
                          <text x="495" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">{v.drX1}</text>
                          <text x="930" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">{v.drX2}</text>
                        </g>
                        <line x1="46" x2="944" y1={v.dr100y} y2={v.dr100y} stroke="#94A3B8" strokeWidth="1" strokeDasharray="2 4" opacity={v.dr100op}></line>
                        <polyline points={v.drBrentPts} fill="none" stroke="#B08968" strokeWidth="1.8" strokeLinejoin="round" opacity={v.drBrentOp}></polyline>
                        <polyline points={v.drFxPts} fill="none" stroke="#8AB17D" strokeWidth="1.8" strokeLinejoin="round" opacity={v.drFxOp}></polyline>
                        <polyline points={v.drLngPts} fill="none" stroke="#E76F51" strokeWidth="1.8" strokeLinejoin="round" opacity={v.drLngOp}></polyline>
                        <polyline points={v.drSpotPts} fill="none" stroke="#00A5CF" strokeWidth="2.6" strokeLinejoin="round"></polyline>
                      </svg>
                    </div>
                    <div style={s('display:flex;align-items:center;gap:16px;margin-top:10px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap')}>
                      <span style={s('display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--tx2)')}><span style={s('width:20px;height:3px;border-radius:2px;background:#00A5CF')}></span>JEPX spot スポット</span>
                      <span style={v.drLngLegS} {...press(tLng, drOn.lng)}><span style={s('width:20px;height:3px;border-radius:2px;background:#E76F51')}></span>JKM</span>
                      <span style={v.drBrentLegS} {...press(tBrent, drOn.brent)}><span style={s('width:20px;height:3px;border-radius:2px;background:#B08968')}></span>Brent ブレント</span>
                      <span style={v.drFxLegS} {...press(tFx, drOn.fx)}><span style={s('width:20px;height:3px;border-radius:2px;background:#8AB17D')}></span>USD/JPY</span>
                      <span style={s('margin-left:auto;font-size:11px;color:var(--mut)')}>Click legend to toggle · 凡例クリックで切替</span>
                    </div>
                  </div>

                  {/* Driver detail panel */}
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);display:flex;flex-direction:column;min-width:0')}>
                    <div style={s('font-size:16px;font-weight:600')}>Driver Detail <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>ドライバー詳細<SampleTag failed={driversLive.failed} /></span></div>
                    <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Last close · Δ1d · 30d trend · correlation vs spot</div>
                    <div style={s('display:flex;flex-direction:column;margin-top:6px')}>
                      {v.drPanel.map((p) => (
                        <div key={p.key} style={s('padding:12px 0;border-bottom:1px solid var(--dv)')}>
                          <div style={s('display:flex;align-items:center;gap:8px;min-width:0')}>
                            <span style={p.dotS}></span>
                            <span style={s('font-size:13px;font-weight:600;white-space:nowrap')}>{p.name}</span>
                            <span style={s('font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{p.sub}</span>
                            <span style={s("margin-left:auto;font-size:16px;font-weight:700;font-feature-settings:'tnum' 1;white-space:nowrap")}>{p.last} <span style={s('font-size:10.5px;font-weight:500;color:var(--mut)')}>{p.unit}</span></span>
                          </div>
                          <div style={s('display:flex;align-items:center;gap:10px;margin-top:7px')}>
                            <span style={p.chipS}>{p.chip}</span>
                            <svg viewBox="0 0 64 18" style={s('width:64px;height:18px;margin-left:auto;flex-shrink:0')}><polyline points={p.spark} fill="none" stroke={p.color} strokeWidth="1.5"></polyline></svg>
                          </div>
                          <div style={s('display:flex;align-items:center;gap:8px;margin-top:9px')}>
                            <span style={s('font-size:11px;color:var(--mut);white-space:nowrap')}>90d corr 相関</span>
                            <span style={s('flex:1;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden')}><span style={p.corrBar}></span></span>
                            <span style={s("font-size:11.5px;font-weight:600;font-feature-settings:'tnum' 1")}>{p.corr}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div style={s('font-size:11.5px;color:var(--mut);line-height:1.6;margin-top:12px')}>
                      <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px;vertical-align:-1px"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`} />
                      {' '}LNG fuel costs pass through to spot with a 3–6 month lag under long-term contracts — JKM is the marginal-cargo signal. · 長期契約のLNG燃料費は3〜6ヶ月遅れて反映。JKMは限界カーゴのシグナル。
                    </div>
                  </div>
                </div>
              </div>
  )

  return (
    <>
      {/* ============ SIDEBAR ============ */}
      <Sidebar active="market" unread={notifUnread} onToggleNotif={toggleNotif} />

      {/* ============ MAIN COLUMN ============ */}
      <div style={s('flex:1;min-width:0;display:flex;flex-direction:column;position:relative')}>
        <TopBar screen="market" unread={notifUnread} onToggleNotif={toggleNotif}>
          {/* Notifications — snapshot freshness + notable day-on-day moves */}
          <NotificationsPopover
            open={showNotif}
            lang={L}
            sections={notifSections}
            seenAt={notifSeenAt}
            onClose={() => setShowNotif(false)}
            onMarkRead={notifMarkSeen}
            action={{
              label: L === 'ja' ? '政策の通知 →' : 'Policy activity →',
              onClick: () => {
                setShowNotif(false)
                setScreen('policy')
              },
            }}
          />
        </TopBar>

        {/* Scrollable content */}
        <div style={s('flex:1;overflow-y:auto;padding:26px 32px 40px')}>
          <div style={s('max-width:1500px;margin:0 auto;display:flex;flex-direction:column;gap:20px')}>
            <PageHeader
              screen="market"
              subtitle="Wholesale & balancing · 9 areas · 30-min resolution · 卸電力・需給調整市場 9エリア 30分値"
            >
              <ExportButton onClick={tExport} />
            </PageHeader>
            {renderViewSwitcher()}
            {v.isSpotBal && renderControlBar()}
            {v.isWholesale && renderWholesaleView()}
            {v.isBalancing && renderBalancingView()}
            {v.isInterco && renderIntercoView()}
            {v.isDrivers && renderDriversView()}
          </div>
        </div>
      </div>
    </>
  )
}
