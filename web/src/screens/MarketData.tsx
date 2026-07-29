// Ported from screens/market-data.html — the Market Data screen.
import { Fragment, useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { s, Hoverable, RawSvg } from '../lib/style'
import type { CSS } from '../lib/style'
import { useApp } from '../lib/app'
import { FreshnessChip } from '../lib/freshness'
import { CHIP_BASE, makeChip, segBase, filterChipBase, slotLabel, fmtDate } from '../lib/chartkit'
import { downloadCsv } from '../lib/download'
import {
  areas,
  areaDefs,
  balProducts,
  icDefs,
  icUtil,
  drv,
  drDefs,
  gaussian as G,
} from './MarketData.data'
import {
  useWholesaleLive,
  windowLive,
  windowLivePrev,
  windowSupply,
  useDriversLive,
  useBalancingLive,
  BAL_CODES,
  useTielineLive,
} from './MarketData.live'

type View = 'wholesale' | 'balancing' | 'interco' | 'drivers'
type Range = '7D' | '30D' | '60D' | '1Y'
type Gran = 'Native' | 'Daily' | 'Weekly' | 'Monthly'
type DrRange = '30D' | '90D' | '1Y'

// makeChip / segBase / filterChipBase / slotLabel / fmtDate now live in
// lib/chartkit (shared with the other screens).

// Fixture-only: the synthetic series have no real dates, so "days ago" is counted
// back from the fixtures' frozen "today". Live data labels use its actual datetimes.
function dateLabel(daysAgo: number): string {
  const d = new Date(2026, 6, 2)
  d.setDate(d.getDate() - daysAgo)
  const MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return MO[d.getMonth()] + ' ' + d.getDate()
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** ISO datetime → hover label: "Jul 11", or "Jul 11 22:30" for intraday slots.
 *  Non-ISO strings (fixture day labels like "Jun 12") are shown verbatim. */
function fmtDT(v: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(v)
  if (!m) return v
  const lbl = MONTHS[Number(m[2]) - 1] + ' ' + Number(m[3])
  return m[4] && !(m[4] === '00' && m[5] === '00') ? lbl + ' ' + m[4] + ':' + m[5] : lbl
}

/**
 * Shared hover layer for the static price / generation-mix SVGs. Renders the given
 * chart `children` inside the SVG and, on mouse-move, a dashed crosshair + an
 * anchored value tooltip (with the exact datetime) for the nearest data point.
 * Point `i` maps to x = 8 + i/(n-1)·464 in the 480-wide viewBox — identical to the
 * polyline geometry. When `n < 2` (e.g. fixtures) the chart renders but is inert.
 */
function ChartHover({
  n,
  dt,
  xs,
  dotY,
  tip,
  children,
}: {
  n: number
  dt: string[]
  xs?: number[]
  dotY?: (i: number) => number
  tip: (i: number) => ReactNode
  children: ReactNode
}) {
  const [i, setI] = useState<number | null>(null)
  // When `xs` (per-point viewBox x-positions) is supplied the chart is plotted on a
  // shared time axis, so map/invert through it; otherwise fall back to the even
  // index spacing (x = 8 + k/(n-1)·464).
  const useXs = !!xs && xs.length === n
  const xOf = (k: number) => (useXs ? xs![k] : 8 + (k / Math.max(1, n - 1)) * 464)
  const onMove = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (n < 2) return
    const r = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * 480
    let k: number
    if (useXs) {
      k = 0
      let best = Infinity
      for (let j = 0; j < n; j++) {
        const d = Math.abs(xs![j] - px)
        if (d < best) {
          best = d
          k = j
        }
      }
    } else {
      k = Math.round(((px - 8) / 464) * (n - 1))
    }
    k = Math.max(0, Math.min(n - 1, k))
    if (k !== i) setI(k)
  }
  const onLeave = () => setI(null)
  const x = i != null ? xOf(i) : 0
  const leftPct = i != null ? Math.max(10, Math.min(90, (x / 480) * 100)) : 0
  return (
    <div style={s('position:relative')}>
      <svg
        viewBox="0 0 480 160"
        style={s('width:100%;height:auto;display:block;margin-top:10px')}
        preserveAspectRatio="none"
        onMouseMove={onMove}
        onMouseLeave={onLeave}
      >
        {children}
        {i != null && (
          <g>
            <line x1={x} y1="6" x2={x} y2="152" stroke="var(--mut)" strokeWidth="0.8" strokeDasharray="3 3"></line>
            {dotY ? <circle cx={x} cy={dotY(i)} r="2.6" fill="var(--tx)"></circle> : null}
          </g>
        )}
      </svg>
      {i != null && (
        <div
          style={s(
            `position:absolute;top:2px;left:${leftPct}%;transform:translateX(-50%);background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:4px 9px;font-size:11px;white-space:nowrap;pointer-events:none;color:var(--tx);box-shadow:var(--sh1);z-index:5;font-feature-settings:'tnum' 1`,
          )}
        >
          <span style={s('color:var(--mut);margin-right:6px')}>{fmtDT(dt[i] ?? '')}</span>
          {tip(i)}
        </div>
      )}
    </div>
  )
}

export function MarketDataScreen() {
  const { lang, setLang, theme, toggleTheme, setScreen, toast, openOverlay, collapsed, toggleCollapsed, watch, focusArea, clearFocusArea, defaultGran, isWatched, toggleWatch, refreshData, refreshing } = useApp()
  const L = lang
  const dark = theme === 'dark'

  const [view, setView] = useState<View>('wholesale')
  const [range, setRange] = useState<Range>('60D')
  const [gran, setGran] = useState<Gran>(defaultGran)
  const [sel, setSel] = useState<Record<string, boolean>>({ hokkaido: true, tohoku: true, tepco: true })
  const [closed, setClosed] = useState<Record<string, boolean>>({})
  const [drRange, setDrRange] = useState<DrRange>('90D')
  const [drOn, setDrOn] = useState<{ jkm: boolean; ncl: boolean; fx: boolean }>({ jkm: true, ncl: true, fx: true })
  // Compare overlay (period-over-period) + inline drill-down accordions.
  const [compare, setCompare] = useState(false)
  const [expandedLine, setExpandedLine] = useState<string | null>(null)
  const [expandedProduct, setExpandedProduct] = useState<string | null>(null)

  const showHeatmap = true

  const toggleArea = (key: string) =>
    setSel((prev) => {
      const next = { ...prev }
      if (next[key]) delete next[key]
      else next[key] = true
      return next
    })
  const toggleSec = (key: string) => setClosed((prev) => ({ ...prev, [key]: !prev[key] }))
  const resetAll = () => {
    setRange('60D')
    setGran('Daily')
    setSel({ hokkaido: true, tohoku: true, tepco: true })
    setClosed({})
  }

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
  const tNotif = () => toast('Notifications live on the Overview screen · 通知は概況画面にあります')
  const tNav = () => toast('Placeholder destination in this prototype · 本プロトタイプ対象外')
  const tRefresh = () => {
    refreshData()
    toast('Reloaded latest data · 最新データを再取得しました')
  }
  const tJkm = () => setDrOn((p) => ({ ...p, jkm: !p.jkm }))
  const tNcl = () => setDrOn((p) => ({ ...p, ncl: !p.ncl }))
  const tFx = () => setDrOn((p) => ({ ...p, fx: !p.fx }))

  const selectedKeys = areas.filter((a) => sel[a.key]).map((a) => a.key)
  const live = useWholesaleLive(selectedKeys, gran)
  const driversLive = useDriversLive()
  const balLive = useBalancingLive()
  const tielineLive = useTielineLive('DAM')

  // ---- computed (mirror of renderVals) ----
  const v = useMemo(() => {
    const selAreas = areas.filter((a) => sel[a.key])
    const N = { '7D': 7, '30D': 30, '60D': 60, '1Y': 365 }[range]
    const step = range === '1Y' ? 6 : 1

    const win = (a: (typeof areas)[number]) => {
      const idx: number[] = []
      for (let d = N - 1; d >= 0; d -= step) idx.push(d)
      return {
        avg: idx.map((d) => a.dailyAvg[d]),
        max: idx.map((d) => a.dailyMax[d]),
        min: idx.map((d) => a.dailyMin[d]),
        days: idx,
      }
    }
    // fixture window with date labels (fallback while live data loads)
    const winLabeled = (a: (typeof areas)[number]) => {
      const b = win(a)
      const m = Math.floor((b.days.length - 1) / 2)
      return {
        avg: b.avg,
        max: b.max,
        min: b.min,
        dt: b.days.map((d) => dateLabel(d)),
        labels: [dateLabel(b.days[0]), dateLabel(b.days[m]), dateLabel(b.days[b.days.length - 1])] as [
          string,
          string,
          string,
        ],
      }
    }
    const mean = (arr: number[]) => arr.reduce((x, y) => x + y, 0) / arr.length
    const finite = (arr: number[]) => arr.filter((x) => Number.isFinite(x))
    const meanF = (arr: number[]) => (arr.length ? arr.reduce((x, y) => x + y, 0) / arr.length : 0)

    // Live data is used only once every selected area's snapshot has loaded;
    // otherwise the fixtures render (loading fallback).
    const useLive = live.ready && selAreas.length > 0 && selAreas.every((a) => !!live.areas[a.key])

    // ---- KPIs (live daily series when loaded, else fixtures) ----
    const act = selAreas.length ? selAreas : areas
    let kAvgV: number
    let kAvgP: number
    let pkPrev: number
    let demV: number
    let pk: { v: number; area: (typeof areas)[number] | null; d: number; dt: string } = { v: -1, area: null, d: 0, dt: '' }
    if (useLive) {
      const curAvgs = act.map((a) => meanF(finite(live.areas[a.key].dAvg.slice(0, N))))
      const prevAvgs = act.map((a) => meanF(finite(live.areas[a.key].dAvg.slice(N, N * 2))))
      kAvgV = meanF(curAvgs)
      kAvgP = meanF(prevAvgs)
      act.forEach((a) => {
        const dm = live.areas[a.key].dMax
        for (let d = 0; d < Math.min(N, dm.length); d++)
          if (Number.isFinite(dm[d]) && dm[d] > pk.v) pk = { v: dm[d], area: a, d, dt: live.areas[a.key].dDt[d] ?? '' }
      })
      pkPrev = Math.max(
        0,
        ...act.map((a) => {
          const w = finite(live.areas[a.key].dMax.slice(N, N * 2))
          return w.length ? Math.max(...w) : 0
        }),
      )
      demV = act.reduce((sum, a) => sum + (live.areas[a.key].peakMW ?? 0), 0)
    } else {
      const curAvgs = act.map((a) => mean(a.dailyAvg.slice(0, N)))
      const prevAvgs = act.map((a) => mean(a.dailyAvg.slice(N, N * 2)))
      kAvgV = mean(curAvgs)
      kAvgP = mean(prevAvgs)
      act.forEach((a) => {
        for (let d = 0; d < N; d++) if (a.dailyMax[d] > pk.v) pk = { v: a.dailyMax[d], area: a, d, dt: '' }
      })
      pkPrev = Math.max(...act.map((a) => Math.max(...a.dailyMax.slice(N, N * 2))))
      demV = act.reduce((sum, a) => sum + a.peak, 0)
    }
    const kAvgC = makeChip(kAvgV - kAvgP, kAvgP ? ((kAvgV - kAvgP) / kAvgP) * 100 : 0)
    const kPeakC = makeChip(pk.v - pkPrev, pkPrev ? ((pk.v - pkPrev) / pkPrev) * 100 : 0)
    const kDemC = makeChip((demV * 0.018) / 1000, 1.8)
    kDemC.txt = '▲ +1.8% vs prior period'

    // ---- heatmap ----
    const heatCol = (val: number) =>
      val < 8 ? '#9FE1CB' : val < 11 ? '#5DCAA5' : val < 14 ? '#FAC775' : val < 18 ? '#EF9F27' : '#E24B4A'
    const heatRows = areas.map((a) => {
      const on = !!sel[a.key]
      return {
        key: a.key,
        label: L === 'ja' ? a.ja + ' ' + a.en : a.en + ' ' + a.ja,
        labS: {
          width: 104,
          flexShrink: 0,
          fontSize: 12,
          fontWeight: on ? 600 : 500,
          color: on ? 'var(--tx)' : 'var(--fnt)',
          whiteSpace: 'nowrap' as const,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        } as CSS,
        cells: a.intraday.map((val, i) => ({
          s: { height: 16, borderRadius: 2, background: heatCol(val), opacity: on ? 1 : dark ? 0.22 : 0.3 } as CSS,
          t: a.en + ' ' + slotLabel(i) + ' · ¥' + val.toFixed(2),
        })),
      }
    })

    // ---- area chips ----
    const areaChips = areas.map((a) => ({
      key: a.key,
      label: L === 'ja' ? a.ja : a.en,
      s: filterChipBase(!!sel[a.key]),
    }))

    // ---- per-area sections ----
    const X = (i: number, n: number) => 8 + (i / (n - 1)) * 464
    const pts = (arr: number[], y: (val: number) => number) =>
      arr.map((val, i) => X(i, arr.length).toFixed(1) + ',' + y(val).toFixed(1)).join(' ')

    // Shared x time-domain across every selected live area (price + supply windows),
    // so all area charts map the same x-pixel to the same calendar time ("align the
    // x-axis"). Fixtures (no live data) keep the even index spacing.
    const parseT = (iso: string): number => {
      const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(iso)
      return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], m[4] ? +m[4] : 0, m[5] ? +m[5] : 0) : NaN
    }
    let gMin = Infinity
    let gMax = -Infinity
    const accT = (iso: string) => {
      const t = parseT(iso)
      if (Number.isFinite(t)) {
        if (t < gMin) gMin = t
        if (t > gMax) gMax = t
      }
    }
    for (const a of selAreas) {
      const la = live.ready ? live.areas[a.key] ?? null : null
      if (!la) continue
      windowLive(la, gran, range).dt.forEach(accT)
      windowSupply(la, gran, range).dt.forEach(accT)
    }
    const haveDomain = Number.isFinite(gMin) && Number.isFinite(gMax) && gMax > gMin
    const xAtTime = (iso: string): number => {
      const t = parseT(iso)
      if (!Number.isFinite(t) || !haveDomain) return 8
      return 8 + ((t - gMin) / (gMax - gMin)) * 464
    }
    const fmtEpoch = (t: number): string => {
      const d = new Date(t)
      const lbl = MONTHS[d.getUTCMonth()] + ' ' + d.getUTCDate()
      const hh = d.getUTCHours()
      const mm = d.getUTCMinutes()
      return hh || mm ? lbl + ' ' + String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0') : lbl
    }
    const sharedAx: [string, string, string] = haveDomain
      ? [fmtEpoch(gMin), fmtEpoch((gMin + gMax) / 2), fmtEpoch(gMax)]
      : ['', '', '']

    const sections = selAreas.map((a) => {
      // Per-area live/fixture: each chart uses its own snapshot when loaded, so a
      // single missing/corrupt area falls back alone instead of dragging every
      // area to fixtures (the KPI block above still gates on the stricter useLive).
      const la = live.ready ? (live.areas[a.key] ?? null) : null
      const w = la ? windowLive(la, gran, range) : winLabeled(a)
      const n = w.avg.length
      const lo = Math.min(...w.min) * 0.92
      const hi = Math.max(...w.max) * 1.05
      const py = (val: number) => 150 - ((val - lo) / (hi - lo)) * 135
      // Plot each price point at its real time position on the shared domain (live),
      // so the same x-pixel is the same calendar time across every area chart.
      const pxAt = (i: number) => (la && haveDomain ? xAtTime(w.dt[i]) : 8 + (i / Math.max(1, n - 1)) * 464)
      const ptsP = (arr: number[], y: (val: number) => number) =>
        arr.map((val, i) => pxAt(i).toFixed(1) + ',' + y(val).toFixed(1)).join(' ')
      const pxs = w.avg.map((_v, i) => pxAt(i))
      // Compare overlay: previous equal-length window's avg, aligned slot-for-slot
      // to this window by index. Clamped to the plot box so an outlier prior period
      // can't escape the chart. Always computed; JSX only draws it when `compare`.
      const pyC = (val: number) => Math.max(12, Math.min(150, py(val)))
      const prevAvg = la ? windowLivePrev(la, gran, range) : []
      const cmpN = Math.min(w.avg.length, prevAvg.length)
      const pCmp =
        cmpN > 1
          ? prevAvg.slice(0, cmpN).map((val, i) => pxAt(i).toFixed(1) + ',' + pyC(val).toFixed(1)).join(' ')
          : ''
      const band =
        ptsP(w.max, py) +
        ' ' +
        w.min.map((_val, i) => pxAt(n - 1 - i).toFixed(1) + ',' + py(w.min[n - 1 - i]).toFixed(1)).join(' ')

      // generation mix — real windowed supply when live (gran-responsive), else synthetic "today"
      const supW = la ? windowSupply(la, gran, range) : null
      let mix1: string
      let mix2: string
      let mix3: string
      let mix4: string
      let demandLine: string
      let peakMWStr: string
      let mixMeta: string
      // Raw windowed mix arrays + geometry for the hover layer (live only).
      let supN = 0
      let supYmax = 1
      let supDtA: string[] = []
      let supDemandA: number[] = []
      let supBaseA: number[] = []
      let supThermA: number[] = []
      let supSolarA: number[] = []
      let supOtherA: number[] = []
      let supXs: number[] = []
      if (supW) {
        const c1 = supW.baseload
        const c2 = c1.map((b, i) => b + supW.thermal[i])
        const c3 = c2.map((val, i) => val + supW.solar[i])
        const c4 = c3.map((val, i) => val + supW.other[i])
        const nS = Math.max(2, c1.length)
        const Xs = (i: number) => (haveDomain ? xAtTime(supW.dt[i]) : 8 + (i / (nS - 1)) * 464)
        const my = (val: number) => 152 - (val / supW.ymax) * 140
        const fwd = (arr: number[]) => arr.map((v, i) => Xs(i).toFixed(1) + ',' + my(v).toFixed(1)).join(' ')
        const rev = (arr: number[]) =>
          arr.map((_v, i) => Xs(nS - 1 - i).toFixed(1) + ',' + my(arr[nS - 1 - i]).toFixed(1)).join(' ')
        mix1 = fwd(c1) + ' ' + Xs(nS - 1).toFixed(1) + ',152 ' + Xs(0).toFixed(1) + ',152'
        mix2 = fwd(c2) + ' ' + rev(c1)
        mix3 = fwd(c3) + ' ' + rev(c2)
        mix4 = fwd(c4) + ' ' + rev(c3)
        demandLine = fwd(supW.demand)
        peakMWStr = Math.round(Math.max(1, ...supW.demand)).toLocaleString('en-US')
        mixMeta = range + ' · ' + gran + ' · grouped MW'
        supN = supW.demand.length
        supYmax = supW.ymax
        supDtA = supW.dt
        supDemandA = supW.demand
        supBaseA = supW.baseload
        supThermA = supW.thermal
        supSolarA = supW.solar
        supOtherA = supW.other
        supXs = supW.demand.map((_v, i) => Xs(i))
      } else {
        const P = a.peak
        const dem = Array.from({ length: 48 }, (_, i) => {
          const t = i / 2
          return P * (0.6 + 0.15 * G(t, 9.5, 6) + 0.24 * G(t, 18.5, 5) + 0.015 * Math.sin(i * 0.9 + a.ph))
        })
        const solar = Array.from({ length: 48 }, (_, i) => {
          const t = i / 2
          return P * 0.3 * (a.solarF || 1) * G(t, 12.5, 5.5)
        })
        const base = Array.from({ length: 48 }, (_, i) => P * (0.33 + 0.008 * Math.sin(i * 0.5 + a.ph)))
        const c1 = base
        const c3 = dem
        const c2 = dem.map((val, i) => Math.max(base[i], val - solar[i]))
        const ymax = P * 1.12
        const my = (val: number) => 152 - (val / ymax) * 140
        const fwd = (arr: number[]) => pts(arr, my)
        const rev = (arr: number[]) =>
          arr.map((_val, i) => X(47 - i, 48).toFixed(1) + ',' + my(arr[47 - i]).toFixed(1)).join(' ')
        const demLine = dem.map((val) => val * 1.018)
        mix1 = fwd(c1) + ' 472,152 8,152'
        mix2 = fwd(c2) + ' ' + rev(c1)
        mix3 = fwd(c3) + ' ' + rev(c2)
        mix4 = ''
        demandLine = pts(demLine, my)
        peakMWStr = P.toLocaleString('en-US')
        mixMeta = 'today · 14 fuels grouped · MW'
        // hover arrays for the synthetic "today" mix (half-hourly, oldest→newest)
        supN = 48
        supYmax = ymax
        supDtA = Array.from({ length: 48 }, (_, i) => String(Math.floor(i / 2)).padStart(2, '0') + ':' + (i % 2 === 0 ? '00' : '30'))
        supDemandA = demLine
        supBaseA = c1
        supThermA = c2.map((val, i) => Math.max(0, val - c1[i]))
        supSolarA = c3.map((val, i) => Math.max(0, val - c2[i]))
        supXs = Array.from({ length: 48 }, (_v, i) => 8 + (i / 47) * 464)
      }

      const open = !closed[a.key]
      // x-axis tick labels (start / mid / end). Shared domain when live so every area
      // chart reads alike; else the window's own labels (price) / slot times (mix).
      const priceAx: [string, string, string] = la && haveDomain ? sharedAx : w.labels
      const mixAx: [string, string, string] =
        supW && haveDomain
          ? sharedAx
          : [
              supN ? fmtDT(supDtA[0]) : '',
              supN ? fmtDT(supDtA[Math.floor((supN - 1) / 2)]) : '',
              supN ? fmtDT(supDtA[supN - 1]) : '',
            ]
      return {
        key: a.key,
        title: L === 'ja' ? a.ja + ' / ' + a.en : a.en + ' / ' + a.ja,
        sub: '',
        meta:
          'latest ¥' +
          (la && la.latest != null ? la.latest.toFixed(2) : a.intraday[29].toFixed(2)) +
          ' · ' +
          range +
          ' · ' +
          gran,
        open,
        closed: !open,
        mix1,
        mix2,
        mix3,
        mix4,
        mixMeta,
        demand: demandLine,
        peakMW: peakMWStr,
        band,
        pMax: ptsP(w.max, py),
        pAvg: ptsP(w.avg, py),
        pMin: ptsP(w.min, py),
        pCmp,
        vMax: Math.max(...w.max).toFixed(1),
        vAvg: mean(w.avg).toFixed(1),
        vMin: Math.min(...w.min).toFixed(1),
        rangeLabel: range,
        granLabel: gran,
        // shared x-axis tick labels (start / mid / end) — identical across all area
        // charts when live, so the aligned time domain is legible.
        priceAx,
        mixAx,
        // hover geometry — price chart
        n,
        plo: lo,
        phi: hi,
        pdt: w.dt,
        pxs,
        pavg: w.avg,
        pmax: w.max,
        pmin: w.min,
        // hover geometry — generation-mix chart (0 points ⇒ no hover, e.g. fixtures)
        supN,
        supYmax,
        supDt: supDtA,
        supXs,
        supDemandA,
        supBaseA,
        supThermA,
        supSolarA,
        supOtherA,
      }
    })

    const hiddenCount = 9 - selAreas.length
    const hiddenNote =
      hiddenCount > 0
        ? hiddenCount +
          ' deselected area' +
          (hiddenCount > 1 ? 's' : '') +
          ' hidden — toggle chips or heatmap rows to show · 非選択エリアは非表示（チップまたはヒートマップ行で切替）'
        : 'All 9 areas shown · 全9エリア表示中'

    // ---- balancing rows ----
    const balRows = balProducts.map((b, bi) => {
      const lv = balLive.ready ? balLive.rows[BAL_CODES[bi]] : null
      const price = lv && lv.price != null ? lv.price.toFixed(2) : b.price
      const proc = lv ? Math.round(lv.proc).toLocaleString('en-US') : b.proc
      const off = lv ? Math.round(lv.off).toLocaleString('en-US') : b.off
      const ach = lv && lv.ach != null ? Math.round(lv.ach) : b.ach
      // Per-area breakdown for the drill-down (procured-desc). Live only.
      const areaDetail = (balLive.ready ? balLive.areaRows[BAL_CODES[bi]] : undefined) || []
      return {
        jp: b.jp,
        en: b.en,
        code: BAL_CODES[bi],
        price,
        proc,
        off,
        ach,
        areaRows: areaDetail.map((r) => ({
          area: r.area,
          name: areaDefs.find((a) => a.key === r.area)?.[L === 'ja' ? 'ja' : 'en'] || r.area,
          price: r.price != null ? '¥' + r.price.toFixed(2) : '—',
          proc: Math.round(r.proc).toLocaleString('en-US'),
          off: Math.round(r.off).toLocaleString('en-US'),
          ach: r.ach != null ? Math.round(r.ach) : null,
        })),
        dot: { width: 8, height: 8, borderRadius: 999, background: dark ? b.cd : b.c, flexShrink: 0 } as CSS,
        bar: { display: 'block', width: ach + '%', height: '100%', borderRadius: 3, background: dark ? b.cd : b.c } as CSS,
      }
    })
    // ---- interconnectors ----
    const pxN: Record<string, number> = {}
    areas.forEach((a) => {
      pxN[a.key] = a.intraday[29]
    })
    const icPx: Record<string, string> = {}
    areas.forEach((a) => {
      icPx[a.key] = a.intraday[29].toFixed(2)
    })
    const fmtMW = (n: number) => Math.round(n).toLocaleString('en-US')
    const icF: Record<string, string> = {}
    let icFlowSum = 0
    let icCapSum = 0
    let icCongN = 0
    let icMaxUv = 0
    let icMaxIdx = -1
    const icAreaName = (k: string) => {
      const a = areaDefs.find((x) => x.key === k)
      return a ? (L === 'ja' ? a.ja : a.en) : k
    }
    const uColor = (val: number) =>
      val >= 0.97 ? '#E24B4A' : val >= 0.85 ? '#EF9F27' : val >= 0.55 ? '#FAC775' : val >= 0.35 ? '#5DCAA5' : '#9FE1CB'
    const icRows = icDefs.map((l, li) => {
      const tl = tielineLive.ready ? tielineLive.byKey[l.key] : undefined
      const u = tl ? tl.util : icUtil[li]
      const capN = tl && tl.ttc != null ? tl.ttc : l.cap
      const uNow = tl && tl.utilNow != null ? tl.utilNow : u[29]
      const flow = uNow * capN
      icF[l.key] = fmtMW(flow)
      icFlowSum += flow
      icCapSum += capN
      if (uNow >= 0.97) icCongN++
      if (uNow > icMaxUv) {
        icMaxUv = uNow
        icMaxIdx = li
      }
      const cong = u.filter((x) => x >= 0.97).length
      const A = (k: string) => areaDefs.find((a) => a.key === k)!
      const nm = (k: string) => (L === 'ja' ? A(k).ja : A(k).en)
      const spread = pxN[l.to] - pxN[l.from]
      const pc = Math.round(uNow * 100)
      return {
        key: l.key,
        n1: L === 'ja' ? l.ja : l.en,
        n2: L === 'ja' ? l.en : l.ja,
        short: l.short,
        route: nm(l.from) + ' → ' + nm(l.to),
        flow: fmtMW(flow),
        cap: fmtMW(capN),
        pct: pc + '%',
        barS: { display: 'block', width: pc + '%', height: '100%', borderRadius: 3, background: uColor(uNow) } as CSS,
        spread: (spread >= 0 ? '+¥' : '−¥') + Math.abs(spread).toFixed(2),
        congTxt: cong + ' / 48',
        congS: (cong > 0
          ? {
              fontSize: 11,
              fontWeight: 600,
              background: 'var(--warnBg)',
              color: 'var(--warnTx)',
              borderRadius: 6,
              padding: '1px 8px',
              fontFeatureSettings: "'tnum' 1",
              whiteSpace: 'nowrap',
            }
          : { fontSize: 11.5, color: 'var(--fnt)', fontFeatureSettings: "'tnum' 1", whiteSpace: 'nowrap' }) as CSS,
        // Intraday drill-down: per-slot utilization + flow (MW), plus peak.
        peakPct: Math.round(Math.max(...u) * 100),
        bars: u.map((val, i) => ({
          h: Math.max(3, Math.round(val * 100)),
          barCol: { display: 'block', width: '100%', borderRadius: 2, background: uColor(val) } as CSS,
          t: l.en + ' ' + slotLabel(i) + ' · ' + Math.round(val * 100) + '% · ' + fmtMW(val * capN) + ' MW',
        })),
        strip: u.map((val, i) => ({
          s: { height: 14, borderRadius: 2, background: uColor(val) } as CSS,
          t: l.en + ' ' + slotLabel(i) + ' · ' + Math.round(val * 100) + '% · ' + fmtMW(val * capN) + ' MW',
        })),
      }
    })
    const icMaxDef = icMaxIdx >= 0 ? icDefs[icMaxIdx] : null
    const icMaxLabel = icMaxDef
      ? `${L === 'ja' ? icMaxDef.ja : icMaxDef.en} · ${icAreaName(icMaxDef.from)} → ${icAreaName(icMaxDef.to)}`
      : ''
    // ---- drivers (live fuels/FX when loaded, else fixtures) ----
    const dvLive = driversLive.ready
    const D: { spot: number[]; jkm: number[]; ncl: number[]; fx: number[] } = dvLive
      ? { spot: driversLive.spot, jkm: driversLive.jkm, ncl: driversLive.ncl, fx: driversLive.fx }
      : drv
    const drAvail = Math.min(D.spot.length, D.jkm.length, D.ncl.length, D.fx.length)
    const drN = Math.min({ '30D': 30, '90D': 90, '1Y': 365 }[drRange], drAvail)
    const drStep = drRange === '1Y' ? 3 : 1
    const drIdx: number[] = []
    for (let d = drN - 1; d >= 0; d -= drStep) drIdx.push(d)
    const reb = (arr: number[]) => {
      const b = arr[drIdx[0]] || 1
      return drIdx.map((d) => (arr[d] / b) * 100)
    }
    const rSpot = reb(D.spot)
    const rJkm = reb(D.jkm)
    const rNcl = reb(D.ncl)
    const rFx = reb(D.fx)
    const visVals = [...rSpot]
    if (drOn.jkm) visVals.push(...rJkm)
    if (drOn.ncl) visVals.push(...rNcl)
    if (drOn.fx) visVals.push(...rFx)
    const drLo = Math.min(...visVals) - 2
    const drHi = Math.max(...visVals) + 2
    const dX = (i: number) => 46 + (i / (drIdx.length - 1)) * 898
    const dY = (r: number) => 14 + ((drHi - r) / (drHi - drLo)) * 276
    const dPts = (arr: number[]) => arr.map((r, i) => dX(i).toFixed(1) + ',' + dY(r).toFixed(1)).join(' ')
    const gVal = (y: number) => (drHi - ((y - 14) / 276) * (drHi - drLo)).toFixed(0)
    const y100 = dY(100)
    const drLeg = (on: boolean): CSS => ({
      display: 'inline-flex',
      alignItems: 'center',
      gap: 7,
      fontSize: 12,
      color: 'var(--tx2)',
      cursor: 'pointer',
      opacity: on ? 1 : 0.4,
      textDecoration: on ? 'none' : 'line-through',
    })
    const drK = (arr: number[]) => {
      const d = arr[0] - arr[1]
      return makeChip(d, (d / arr[1]) * 100)
    }
    const kJ = drK(D.jkm)
    const kN = drK(D.ncl)
    const kF = drK(D.fx)
    const drCorr: Record<'jkm' | 'ncl' | 'fx', number> = {
      jkm: dvLive && driversLive.corr.jkm != null ? driversLive.corr.jkm : drDefs[0].corr,
      ncl: dvLive && driversLive.corr.ncl != null ? driversLive.corr.ncl : drDefs[1].corr,
      fx: dvLive && driversLive.corr.fx != null ? driversLive.corr.fx : drDefs[2].corr,
    }
    const drPanel = drDefs.map((dd) => {
      const arr = D[dd.key]
      const d = arr[0] - arr[1]
      const c = makeChip(d, (d / arr[1]) * 100)
      const s30: number[] = []
      for (let d2 = 29; d2 >= 0; d2--) s30.push(arr[d2])
      const mn = Math.min(...s30)
      const mx = Math.max(...s30)
      const spark = s30
        .map((val, i) => ((i / 29) * 64).toFixed(1) + ',' + (15.5 - ((val - mn) / (mx - mn || 1)) * 13).toFixed(1))
        .join(' ')
      return {
        key: dd.key,
        name: L === 'ja' ? dd.ja : dd.en,
        sub: dd.src,
        unit: dd.unit,
        last: arr[0].toFixed(dd.dec),
        color: dd.color,
        chip: c.txt,
        chipS: { ...c.style, marginTop: 0, padding: '2px 8px' } as CSS,
        dotS: { width: 8, height: 8, borderRadius: 999, background: dd.color, flexShrink: 0 } as CSS,
        spark,
        corr: drCorr[dd.key].toFixed(2),
        corrBar: { display: 'block', width: Math.max(0, drCorr[dd.key]) * 100 + '%', height: '100%', borderRadius: 3, background: dd.color } as CSS,
      }
    })

    // ---- caption "as of" dates (data-truth) ----
    // Live captions show the real snapshot dates (ISO, matching the fixtures'
    // format); while a snapshot is still loading, its fixture date renders.
    let wsToday = '2026-07-02'
    if (useLive) {
      let latest = ''
      for (const a of selAreas) {
        const d = (live.areas[a.key].dDt[0] ?? '').slice(0, 10)
        if (d > latest) latest = d
      }
      if (latest) wsToday = latest
    }
    const tlDate = tielineLive.ready && tielineLive.date ? tielineLive.date.slice(0, 10) : null

    return {
      heatDate: wsToday,
      balDate: balLive.ready && balLive.end ? balLive.end.slice(0, 10) : '2026-07-01',
      icMapDate: tlDate ?? '2026-07-01',
      icTodayDate: tlDate ?? '2026-07-02',
      drCloseDate: driversLive.ready && driversLive.end ? driversLive.end.slice(0, 10) : '2026-07-01',
      icCong: icCongN,
      icMaxU: Math.round(icMaxUv * 100),
      icMaxLabel,
      icSpread: (pxN.tepco - pxN.kyushu).toFixed(2),
      icFlowTot: fmtMW(icFlowSum),
      icCapTot: fmtMW(icCapSum),
      icUtilTot: Math.round((icFlowSum / icCapSum) * 100),
      icPx,
      icF,
      icRows,
      icWarnChip: { ...CHIP_BASE, background: 'var(--dnBg)', color: 'var(--dn)' } as CSS,
      icChipN: { ...CHIP_BASE, background: 'rgba(138,147,163,.14)', color: 'var(--mut)' } as CSS,
      dr30S: segBase(drRange === '30D'),
      dr90S: segBase(drRange === '90D'),
      dr1yS: segBase(drRange === '1Y'),
      drSpotPts: dPts(rSpot),
      drJkmPts: dPts(rJkm),
      drNclPts: dPts(rNcl),
      drFxPts: dPts(rFx),
      drJkmOp: drOn.jkm ? 1 : 0,
      drNclOp: drOn.ncl ? 1 : 0,
      drFxOp: drOn.fx ? 1 : 0,
      drJkmLegS: drLeg(drOn.jkm),
      drNclLegS: drLeg(drOn.ncl),
      drFxLegS: drLeg(drOn.fx),
      drG1: gVal(69),
      drG2: gVal(138),
      drG3: gVal(207),
      drG4: gVal(276),
      dr100y: Math.round(y100 * 10) / 10,
      dr100op: y100 >= 14 && y100 <= 290 ? 0.8 : 0,
      drX0: dateLabel(drN - 1),
      drX1: dateLabel(Math.floor(drN / 2)),
      drX2: dateLabel(0),
      drJkmV: D.jkm[0].toFixed(2),
      drJkmC: kJ.txt,
      drNclV: D.ncl[0].toFixed(1),
      drNclC: kN.txt,
      drNclCS: kN.style,
      drFxV: D.fx[0].toFixed(2),
      drFxC: kF.txt,
      drFxCS: kF.style,
      drPanel,
      langJaS: segBase(L === 'ja'),
      langEnS: segBase(L === 'en'),
      vwWS: segBase(view === 'wholesale'),
      vwBS: segBase(view === 'balancing'),
      vwIS: segBase(view === 'interco'),
      vwDS: segBase(view === 'drivers'),
      isWholesale: view === 'wholesale',
      isBalancing: view === 'balancing',
      isInterco: view === 'interco',
      isDrivers: view === 'drivers',
      isSpotBal: view === 'wholesale' || view === 'balancing',
      r7S: segBase(range === '7D'),
      r30S: segBase(range === '30D'),
      r60S: segBase(range === '60D'),
      r1yS: segBase(range === '1Y'),
      gNS: segBase(gran === 'Native'),
      gDS: segBase(gran === 'Daily'),
      gWS: segBase(gran === 'Weekly'),
      gMS: segBase(gran === 'Monthly'),
      areaChips,
      kAvg: kAvgV.toFixed(2),
      kAvgSub: (selAreas.length || 9) + ' areas · ' + range + ' · vs prior ' + range,
      kAvgD: kAvgC.txt,
      kPeak: pk.v.toFixed(2),
      kPeakSub: (pk.area ? (L === 'ja' ? pk.area.ja : pk.area.en) : '') + ' · ' + (pk.dt ? fmtDate(pk.dt) : dateLabel(pk.d)) + ' · vs prior period',
      kPeakD: kPeakC.txt,
      kPeakDS: kPeakC.style,
      kDem: demV.toLocaleString('en-US'),
      kDemSub: 'sum of selected-area peaks · 17:30 slot',
      kDemD: kDemC.txt,
      kDemDS: kDemC.style,
      showHeat: showHeatmap,
      heatRows,
      sections,
      hiddenNote,
      balRows,
      balProcTot: balLive.ready ? Math.round(balLive.procTot).toLocaleString('en-US') : '9,321',
      balAvgPrice: balLive.ready && balLive.avgPrice != null ? balLive.avgPrice.toFixed(2) : '4.87',
      balD1S: { ...CHIP_BASE, background: 'var(--upBg)', color: 'var(--up)' } as CSS,
      balD2S: { ...CHIP_BASE, background: 'var(--upBg)', color: 'var(--up)' } as CSS,
    }
  }, [view, range, gran, sel, closed, drRange, drOn, L, dark, live, driversLive, balLive, tielineLive])

  const isDarkB = dark
  const isLightB = !dark

  // ---- section renderers ----
  // Mechanical extraction for navigability: each renderer holds one section's
  // JSX verbatim (same closures over state/`v`) and is called from the single
  // return at the bottom — the rendered tree is identical.

  const renderSidebar = () => (
      <div style={s(`width:264px;flex-shrink:0;background:var(--bg1);border-right:1px solid var(--bd);flex-direction:column;padding:22px 16px 16px;overflow-y:auto;${collapsed ? 'display:none' : 'display:flex'}`)}>
        <div style={s('padding:0 8px')}>
          <div style={s('display:flex;align-items:center;gap:7px')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:23px;height:23px;color:var(--ac);flex-shrink:0"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`} />
            <span style={s('font-size:21px;font-weight:700;letter-spacing:.01em')}>JEMA</span>
          </div>
          <div style={s('font-size:9px;font-weight:600;letter-spacing:.14em;color:var(--mut);margin-top:3px;text-transform:uppercase')}>Japan Energy Market Analytics</div>
        </div>

        <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:26px 8px 8px')}>MENU · メニュー</div>
        <div style={s('display:flex;flex-direction:column;gap:3px')}>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => setScreen('overview')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><rect x="3" y="3" width="7" height="9" rx="1"></rect><rect x="14" y="3" width="7" height="5" rx="1"></rect><rect x="14" y="12" width="7" height="9" rx="1"></rect><rect x="3" y="16" width="7" height="5" rx="1"></rect></svg>`} /><span>Market Overview</span>
            <span style={s('margin-left:auto;font-size:10.5px;font-weight:500;color:var(--mut)')}>概況</span>
          </Hoverable>
          <div style={s('display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:600;color:var(--acT);background:var(--acTint);cursor:pointer;position:relative')}>
            <span style={s('position:absolute;left:-16px;top:8px;bottom:8px;width:3px;background:var(--ac);border-radius:0 2px 2px 0')}></span>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><path d="M3 3v18h18"></path><path d="M8 17v-3"></path><path d="M13 17V9"></path><path d="M18 17V5"></path></svg>`} /><span>Market Data</span>
            <span style={s('margin-left:auto;font-size:10.5px;font-weight:500;color:var(--acHi)')}>データ</span>
          </div>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => setScreen('capacity')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><polygon points="12 2 22 8.5 12 15 2 8.5 12 2"></polygon><polyline points="2 14 12 20.5 22 14"></polyline></svg>`} /><span>Capacity &amp; Auctions</span>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;margin-left:auto;color:var(--mut);flex-shrink:0"><path d="M9 18l6-6-6-6"></path></svg>`} />
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => setScreen('policy')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><line x1="3" y1="22" x2="21" y2="22"></line><line x1="6" y1="18" x2="6" y2="11"></line><line x1="10" y1="18" x2="10" y2="11"></line><line x1="14" y1="18" x2="14" y2="11"></line><line x1="18" y1="18" x2="18" y2="11"></line><polygon points="12 2 20 7 4 7"></polygon></svg>`} /><span>Policy Deep Dive</span>
            <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>3</span>
          </Hoverable>
        </div>

        <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:22px 8px 8px')}>GENERAL · 全般</div>
        <div style={s('display:flex;flex-direction:column;gap:3px')}>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('watchlist')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon></svg>`} /><span>Watchlist</span>
            {watch.length > 0 && (
              <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>{watch.length}</span>
            )}
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={tNav}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} /><span>Notifications</span>
            <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>2</span>
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('settings')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><circle cx="12" cy="12" r="3"></circle><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path></svg>`} /><span>Settings</span>
          </Hoverable>
        </div>

        <div style={s('flex:1')}></div>

        <Hoverable base="display:flex;align-items:center;gap:8px;padding:6px 12px;color:var(--mut);font-size:12px;cursor:pointer;border-radius:10px" hover="background:var(--bg2);color:var(--tx2)" onClick={toggleCollapsed}>
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;flex-shrink:0"><path d="M11 17l-5-5 5-5"></path><path d="M18 17l-5-5 5-5"></path></svg>`} /><span>Collapse · 折りたたむ</span>
        </Hoverable>

        <div style={s('background:linear-gradient(135deg,var(--navyA),var(--navyB));border-radius:16px;padding:15px 15px 13px;color:#FFFFFF;margin-top:12px')}>
          <div style={s('display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;color:#7FD4E8;flex-shrink:0"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14a9 3 0 0 0 18 0V5"></path><path d="M3 12a9 3 0 0 0 18 0"></path></svg>`} />Data freshness · データ鮮度</div>
          <FreshnessChip inverse style={{ marginTop: 6 }} />
          <div style={s('font-size:10.5px;color:rgba(255,255,255,.55);margin-top:2px')}>Hugging Face sync · GitHub Actions daily</div>
          <Hoverable base="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.35);color:#FFFFFF;border-radius:999px;padding:5px 13px;font-size:12px;font-weight:500;cursor:pointer;margin-top:10px" hover="background:rgba(255,255,255,.10)" onClick={tRefresh}>
            <span style={s(refreshing ? 'display:inline-flex;animation:jema-spin .7s linear infinite' : 'display:inline-flex')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;flex-shrink:0"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>`} /></span>Refresh · 更新
          </Hoverable>
        </div>
      </div>
  )

  // Top bar (breadcrumb, search, theme/language toggles, profile)
  const renderTopBar = () => (
        <div style={s('height:72px;flex-shrink:0;background:var(--bg1);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:18px;padding:0 28px;position:relative;z-index:30')}>
          <div style={s('font-size:13px;color:var(--mut);flex-shrink:0')}>Market Data <span style={s('color:var(--fnt3)')}>·</span> マーケットデータ</div>
          <div onClick={() => openOverlay('search')} style={s('flex:1;max-width:520px;display:flex;align-items:center;gap:9px;background:var(--bg0);border:1px solid var(--bd);border-radius:12px;padding:8px 14px;color:var(--mut);cursor:text')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;flex-shrink:0"><circle cx="11" cy="11" r="8"></circle><path d="M21 21l-4.35-4.35"></path></svg>`} />
            <input readOnly onFocus={() => openOverlay('search')} placeholder="Search markets, areas, committees… 市場・エリア・委員会を検索…" style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:13px;background:transparent;color:var(--tx);min-width:0;cursor:text')} />
            <span style={s('border:1px solid var(--bd2);background:var(--bg1);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--mut);flex-shrink:0')}>⌘K</span>
          </div>
          <div style={s('flex:1')}></div>
          <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;flex-shrink:0" hover="background:var(--bg2)" onClick={toggleTheme} title="Toggle theme · テーマ切替" aria-label="Toggle theme">
            {isDarkB && (<RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`} />)}
            {isLightB && (<RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`} />)}
          </Hoverable>
          <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;position:relative;flex-shrink:0" hover="background:var(--bg2)" onClick={tNotif} aria-label="Notifications">
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} />
            <span style={s('position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:999px;background:var(--ac);border:1.5px solid var(--bg1)')}></span>
          </Hoverable>
          <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;flex-shrink:0')}>
            <span style={v.langJaS} onClick={() => setLang('ja')}>日本語</span>
            <span style={v.langEnS} onClick={() => setLang('en')}>English</span>
          </div>
          <div style={s('display:flex;align-items:center;gap:10px;flex-shrink:0')}>
            <div style={s('width:34px;height:34px;border-radius:999px;background:var(--avatar);color:#FFFFFF;display:flex;align-items:center;justify-content:center;font-size:11.5px;font-weight:600')}>AN</div>
            <div style={s('line-height:1.25')}>
              <div style={s('font-size:13px;font-weight:600')}>Analyst</div>
              <div style={s('font-size:11px;color:var(--mut)')}>analyst@example.jp</div>
            </div>
          </div>
        </div>
  )

  // Page header (title + Export CSV)
  const renderPageHeader = () => (
            <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:16px')}>
              <div>
                <div style={s('display:flex;align-items:baseline;gap:10px')}>
                  <span style={s('font-size:26px;font-weight:700;letter-spacing:-.01em')}>Market Data</span>
                  <span style={s('font-size:15px;font-weight:500;color:var(--mut)')}>マーケットデータ</span>
                </div>
                <div style={s('font-size:13.5px;color:var(--tx2);margin-top:2px')}>Wholesale &amp; balancing · 9 areas · 30-min resolution · 卸電力・需給調整市場 9エリア 30分値</div>
              </div>
              <div style={s('display:flex;gap:10px;flex-shrink:0;padding-top:4px')}>
                <Hoverable base="display:inline-flex;align-items:center;gap:7px;background:var(--bg1);border:1px solid var(--fnt3);color:var(--tx);border-radius:999px;padding:9px 20px;font-size:13.5px;font-weight:600;cursor:pointer" hover="background:var(--acTint2);border-color:var(--ac)" onClick={tExport}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;flex-shrink:0"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`} />Export CSV · 出力
                </Hoverable>
              </div>
            </div>
  )

  // Sub-view switcher (Wholesale / Balancing · Interconnectors / Drivers)
  const renderViewSwitcher = () => (
            <div style={s('display:flex;align-items:center;gap:14px;flex-wrap:wrap')}>
              <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                <span style={v.vwWS} onClick={() => setView('wholesale')}>Wholesale (Spot) 卸電力</span>
                <span style={v.vwBS} onClick={() => setView('balancing')}>Balancing 需給調整</span>
              </div>
              <span style={s('color:var(--fnt3)')}>·</span>
              <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                <span style={v.vwIS} onClick={() => setView('interco')}>Interconnectors 連系線</span>
                <span style={v.vwDS} onClick={() => setView('drivers')}>Drivers 燃料・為替</span>
              </div>
            </div>
  )

  // Control bar: range / area chips / granularity (spot & balancing only)
  const renderControlBar = () => (
              <div style={s('background:var(--bg1);border-radius:16px;padding:12px 16px;box-shadow:var(--sh1);display:flex;align-items:center;gap:12px;flex-wrap:wrap')}>
                <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                  <span style={v.r7S} onClick={() => setRange('7D')}>7D</span>
                  <span style={v.r30S} onClick={() => setRange('30D')}>30D</span>
                  <span style={v.r60S} onClick={() => setRange('60D')}>60D</span>
                  <span style={v.r1yS} onClick={() => setRange('1Y')}>1Y</span>
                </div>
                <span style={s('width:1px;height:22px;background:var(--dv)')}></span>
                <span style={s('font-size:12px;color:var(--mut);flex-shrink:0')}>Areas エリア</span>
                <div style={s('display:flex;gap:6px;flex-wrap:wrap;align-items:center')}>
                  {v.areaChips.map((a) => (
                    <span key={a.key} style={a.s} onClick={() => toggleArea(a.key)}>{a.label}</span>
                  ))}
                  <span style={s('font-size:11.5px;font-weight:600;padding:3px 11px;border-radius:999px;cursor:pointer;border:1px dashed var(--fnt2);background:transparent;color:var(--fnt);white-space:nowrap')} onClick={tSystem} title="System series = PROPOSED · システム系列は提案中">System <span style={s('font-size:9px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:5px;padding:0 4px;margin-left:2px')}>P</span></span>
                </div>
                <span style={s('width:1px;height:22px;background:var(--dv)')}></span>
                <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                  <span style={v.gNS} onClick={granN}>Native 30分</span>
                  <span style={v.gDS} onClick={granD}>Daily</span>
                  <span style={v.gWS} onClick={granW}>Weekly</span>
                  <span style={v.gMS} onClick={granM}>Monthly</span>
                </div>
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
                        <div key={hr.key} style={s('display:flex;align-items:center;gap:10px;cursor:pointer')} onClick={() => toggleArea(hr.key)} title="Click to toggle area · クリックで選択切替">
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
                    </div>
                    {sec.open && (
                      <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:20px')}>
                        <div style={s('background:var(--bg1);border-radius:20px;padding:18px 20px;box-shadow:var(--sh1)')}>
                          <div style={s('display:flex;justify-content:space-between;align-items:baseline')}>
                            <span style={s('font-size:14px;font-weight:600')}>Generation mix <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>電源構成</span></span>
                            <span style={s('font-size:11px;color:var(--mut)')}>{sec.mixMeta}</span>
                          </div>
                          <ChartHover
                            n={sec.supN}
                            dt={sec.supDt}
                            xs={sec.supXs}
                            dotY={(i) => 152 - (sec.supDemandA[i] / sec.supYmax) * 140}
                            tip={(i) => (
                              <>
                                <span style={s('color:#2A9D8F')}>base {Math.round(sec.supBaseA[i]).toLocaleString('en-US')}</span>
                                {' · '}
                                <span style={s('color:#4A6FA5')}>therm {Math.round(sec.supThermA[i]).toLocaleString('en-US')}</span>
                                {' · '}
                                <span style={s('color:#C99A2E')}>sol/wnd {Math.round(sec.supSolarA[i]).toLocaleString('en-US')}</span>
                                {' · '}
                                <span>dem {Math.round(sec.supDemandA[i]).toLocaleString('en-US')} MW</span>
                              </>
                            )}
                          >
                            <polygon points={sec.mix1} fill="#2A9D8F" fillOpacity="0.78"></polygon>
                            <polygon points={sec.mix2} fill="#4A6FA5" fillOpacity="0.72"></polygon>
                            <polygon points={sec.mix3} fill="#E9C46A" fillOpacity="0.82"></polygon>
                            {sec.mix4 ? <polygon points={sec.mix4} fill="#9AA5B5" fillOpacity="0.6"></polygon> : null}
                            <g style={s('color:var(--tx)')}><polyline points={sec.demand} fill="none" stroke="currentColor" strokeWidth="1.8" strokeDasharray="1 0"></polyline></g>
                          </ChartHover>
                          <div style={s("display:flex;justify-content:space-between;padding:0 1.67%;margin-top:5px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                            <span>{sec.mixAx[0]}</span><span>{sec.mixAx[1]}</span><span>{sec.mixAx[2]}</span>
                          </div>
                          <div style={s('display:flex;align-items:center;gap:14px;margin-top:9px;font-size:11px;color:var(--tx2);flex-wrap:wrap')}>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:10px;height:10px;border-radius:3px;background:#2A9D8F')}></span>Baseload 基幹</span>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:10px;height:10px;border-radius:3px;background:#4A6FA5')}></span>Thermal 火力</span>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:10px;height:10px;border-radius:3px;background:#E9C46A')}></span>Solar/Wind 太陽光・風力</span>
                            {sec.mix4 ? (<span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:10px;height:10px;border-radius:3px;background:#9AA5B5')}></span>Imports/Storage 連系・貯蔵</span>) : null}
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid var(--tx)')}></span>Demand 需要</span>
                            <span style={s("margin-left:auto;font-feature-settings:'tnum' 1;color:var(--mut)")}>peak {sec.peakMW} MW</span>
                          </div>
                        </div>
                        <div style={s('background:var(--bg1);border-radius:20px;padding:18px 20px;box-shadow:var(--sh1)')}>
                          <div style={s('display:flex;justify-content:space-between;align-items:baseline')}>
                            <span style={s('font-size:14px;font-weight:600')}>Price <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>価格</span></span>
                            <span style={s('font-size:11px;color:var(--mut)')}>{sec.rangeLabel} · {sec.granLabel} · max / avg / min · ¥/kWh</span>
                          </div>
                          <ChartHover
                            n={sec.n}
                            dt={sec.pdt}
                            xs={sec.pxs}
                            dotY={(i) => 150 - ((sec.pavg[i] - sec.plo) / (sec.phi - sec.plo)) * 135}
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
                            <polygon points={sec.band} fill="#00A5CF" fillOpacity="0.10"></polygon>
                            <polyline points={sec.pMax} fill="none" stroke="#E24B4A" strokeWidth="1.6"></polyline>
                            <g style={s('color:var(--tx)')}><polyline points={sec.pAvg} fill="none" stroke="currentColor" strokeWidth="1.8"></polyline></g>
                            <polyline points={sec.pMin} fill="none" stroke="#00A5CF" strokeWidth="1.6"></polyline>
                            {compare && sec.pCmp ? (
                              <polyline points={sec.pCmp} fill="none" stroke="var(--mut)" strokeWidth="1.5" strokeDasharray="4 3" strokeOpacity="0.85"></polyline>
                            ) : null}
                          </ChartHover>
                          <div style={s("display:flex;justify-content:space-between;padding:0 1.67%;margin-top:5px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                            <span>{sec.priceAx[0]}</span><span>{sec.priceAx[1]}</span><span>{sec.priceAx[2]}</span>
                          </div>
                          <div style={s("display:flex;align-items:center;gap:14px;margin-top:9px;font-size:11px;color:var(--tx2);flex-wrap:wrap;font-feature-settings:'tnum' 1")}>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid #E24B4A')}></span>Max ¥{sec.vMax}</span>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid var(--tx)')}></span>Avg ¥{sec.vAvg}</span>
                            <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px solid #00A5CF')}></span>Min ¥{sec.vMin}</span>
                            {compare && sec.pCmp ? (
                              <span style={s('display:inline-flex;align-items:center;gap:5px')}><span style={s('width:14px;height:0;border-top:2px dashed var(--mut)')}></span>{L === 'ja' ? '前期間 avg' : 'Prev period avg'}</span>
                            ) : null}
                          </div>
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
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>all products · nationwide</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>▼ −0.32 (−6.2%)</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Procured volume<br />調達量合計</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.balProcTot} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>MW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>5 products · vs prior day</div>
                    <span style={v.balD1S}>▲ +214 (+2.4%)</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Shortfall slots<br />調達不足コマ</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>3 <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>/ 48</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>三次② evening ramp · 17:00–18:30</div>
                    <span style={v.balD2S}>▼ −2 slots vs y&apos;day</span>
                  </div>
                </div>

                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Balancing Products <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>需給調整市場 商品別</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>EPRX · FY2025+ · daily · {v.balDate} · nationwide procurement</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>¥/ΔkW·30min · MW</span>
                  </div>
                  <div style={s('display:grid;grid-template-columns:1.6fr .9fr .9fr .9fr 1.2fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)')}>
                    <span>PRODUCT · 商品</span><span style={s('text-align:right')}>AVG PRICE</span><span style={s('text-align:right')}>PROCURED</span><span style={s('text-align:right')}>OFFERED</span><span style={s('text-align:right')}>ACHIEVEMENT 達成率</span>
                  </div>
                  {v.balRows.map((b, bi) => (
                    <Fragment key={bi}>
                    <Hoverable base={expandedProduct === b.code ? 'display:grid;grid-template-columns:1.6fr .9fr .9fr .9fr 1.2fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer;background:var(--hov)' : 'display:grid;grid-template-columns:1.6fr .9fr .9fr .9fr 1.2fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer'} hover="background:var(--hov)" onClick={() => tProduct(b.code)}>
                      <span style={s('display:flex;align-items:center;gap:9px;min-width:0')}>
                        <span style={b.dot}></span>
                        <span style={s('font-size:13px;font-weight:600;white-space:nowrap')}>{expandedProduct === b.code ? '▾ ' : '▸ '}{b.jp} <span style={s('font-weight:400;color:var(--mut);font-size:11.5px')}>{b.en}</span></span>
                      </span>
                      <span style={s("text-align:right;font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>¥{b.price}</span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{b.proc}</span>
                      <span style={s("text-align:right;font-size:13px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{b.off}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:72px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={b.bar}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{b.ach}%</span>
                      </span>
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
                            <div style={s('font-size:10.5px;color:var(--mut);margin-top:7px')}>{L === 'ja' ? '各エリアの直近ウィンドウ平均（¥/ΔkW·30min · MW）· 達成率＝調達量／応札量' : 'Per-area window averages (¥/ΔkW·30min · MW) · achievement = procured / offered'}</div>
                          </>
                        ) : (
                          <div style={s('font-size:11.5px;color:var(--mut)')}>{L === 'ja' ? 'エリア別データは読込中です。' : 'Per-area data still loading.'}</div>
                        )}
                      </div>
                    ) : null}
                    </Fragment>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>一次=primary FCR · 二次=secondary AFC/RR · 三次=tertiary replacement · Prices are weighted daily averages · 価格は日次加重平均</div>
                </div>
              </div>
  )

  // ================= INTERCONNECTORS VIEW =================
  const renderIntercoView = () => (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>Congested lines now<br />混雑中の連系線</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.icCong} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>/ 10 lines</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>≥97% of TTC · latest slot 14:30</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>▲ +1 line vs y&apos;day same slot</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Highest utilization<br />最高利用率</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.icMaxU}<span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>%</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>{v.icMaxLabel}</div>
                    <span style={v.icWarnChip}>binding since 11:00 · 混雑継続中</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Widest area spread<br />最大エリア価格差</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>¥{v.icSpread} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>/kWh</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>Tokyo vs Kyushu · latest slot</div>
                    <span style={v.icChipN}>congestion rent signal · 値差＝混雑レント</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Flow in use<br />総送電量</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.icFlowTot} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>MW</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>of {v.icCapTot} MW total TTC</div>
                    <span style={v.icChipN}>{v.icUtilTot}% of capability in use</span>
                  </div>
                </div>

                {/* Flow map */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Flow Map — 9 Areas <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>連系線フロー</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Net flows at latest slot 14:30 · labels in MW · line width ∝ transfer capability · OCCTO 系統情報 {v.icMapDate}</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px;flex-shrink:0')}>node prices = area spot ¥/kWh</span>
                  </div>
                  <svg viewBox="0 0 960 360" style={s('width:100%;height:auto;display:block;margin-top:8px')}>
                    <line x1="885" y1="35" x2="795" y2="95" stroke="#FAC775" strokeWidth="2.8"></line>
                    <line x1="795" y1="95" x2="700" y2="170" stroke="#EF9F27" strokeWidth="7"></line>
                    <line x1="565" y1="225" x2="700" y2="170" stroke="#E24B4A" strokeWidth="3.8"></line>
                    <line x1="425" y1="225" x2="565" y2="225" stroke="#5DCAA5" strokeWidth="4.1"></line>
                    <line x1="450" y1="110" x2="565" y2="225" stroke="#5DCAA5" strokeWidth="2.3"></line>
                    <line x1="450" y1="110" x2="425" y2="225" stroke="#5DCAA5" strokeWidth="3.6"></line>
                    <line x1="250" y1="185" x2="425" y2="225" stroke="#FAC775" strokeWidth="5.5"></line>
                    <line x1="300" y1="290" x2="425" y2="225" stroke="#FAC775" strokeWidth="3.2"></line>
                    <line x1="250" y1="185" x2="300" y2="290" stroke="#5DCAA5" strokeWidth="3"></line>
                    <line x1="85" y1="265" x2="250" y2="185" stroke="#E24B4A" strokeWidth="4.3"></line>
                    <circle cx="840" cy="65" r="8" style={s('fill:var(--bg1)')} stroke="#FAC775" strokeWidth="1.5"></circle>
                    <text x="840" y="65" transform="rotate(146 840 65)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#D99A2B">▶</text>
                    <circle cx="747.5" cy="132.5" r="8" style={s('fill:var(--bg1)')} stroke="#EF9F27" strokeWidth="1.5"></circle>
                    <text x="747.5" y="132.5" transform="rotate(142 747.5 132.5)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#EF9F27">▶</text>
                    <circle cx="632.5" cy="197.5" r="8" style={s('fill:var(--bg1)')} stroke="#E24B4A" strokeWidth="1.5"></circle>
                    <text x="632.5" y="197.5" transform="rotate(-22 632.5 197.5)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#E24B4A">▶</text>
                    <circle cx="495" cy="225" r="8" style={s('fill:var(--bg1)')} stroke="#5DCAA5" strokeWidth="1.5"></circle>
                    <text x="495" y="225" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#2A9D8F">▶</text>
                    <circle cx="507.5" cy="167.5" r="8" style={s('fill:var(--bg1)')} stroke="#5DCAA5" strokeWidth="1.5"></circle>
                    <text x="507.5" y="167.5" transform="rotate(45 507.5 167.5)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#2A9D8F">▶</text>
                    <circle cx="437.5" cy="167.5" r="8" style={s('fill:var(--bg1)')} stroke="#5DCAA5" strokeWidth="1.5"></circle>
                    <text x="437.5" y="167.5" transform="rotate(102 437.5 167.5)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#2A9D8F">▶</text>
                    <circle cx="337.5" cy="205" r="8" style={s('fill:var(--bg1)')} stroke="#FAC775" strokeWidth="1.5"></circle>
                    <text x="337.5" y="205" transform="rotate(13 337.5 205)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#D99A2B">▶</text>
                    <circle cx="362.5" cy="257.5" r="8" style={s('fill:var(--bg1)')} stroke="#FAC775" strokeWidth="1.5"></circle>
                    <text x="362.5" y="257.5" transform="rotate(-27 362.5 257.5)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#D99A2B">▶</text>
                    <circle cx="275" cy="237.5" r="8" style={s('fill:var(--bg1)')} stroke="#5DCAA5" strokeWidth="1.5"></circle>
                    <text x="275" y="237.5" transform="rotate(64 275 237.5)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#2A9D8F">▶</text>
                    <circle cx="167.5" cy="225" r="8" style={s('fill:var(--bg1)')} stroke="#E24B4A" strokeWidth="1.5"></circle>
                    <text x="167.5" y="225" transform="rotate(-26 167.5 225)" textAnchor="middle" dominantBaseline="central" fontSize="9" fill="#E24B4A">▶</text>
                    <text x="826" y="44" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.hh}</text>
                    <text x="735" y="116" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.st}</text>
                    <text x="626" y="178" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.fc}</text>
                    <text x="640" y="218" textAnchor="middle" fontSize="9" style={s('fill:var(--mut)')}>50/60 Hz</text>
                    <text x="495" y="209" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.kc}</text>
                    <text x="530" y="157" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.hc}</text>
                    <text x="415" y="164" textAnchor="end" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.hk}</text>
                    <text x="337" y="187" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.ck}</text>
                    <text x="372" y="277" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.sk}</text>
                    <text x="257" y="242" textAnchor="end" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.cs}</text>
                    <text x="156" y="205" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--tx2)')}>{v.icF.kq}</text>
                    <rect x="838" y="16" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="885" y="31" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Hokkaido</text>
                    <text x="885" y="46" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>¥{v.icPx.hokkaido}</text>
                    <rect x="748" y="76" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="795" y="91" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Tohoku</text>
                    <text x="795" y="106" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>¥{v.icPx.tohoku}</text>
                    <rect x="653" y="151" width="94" height="38" rx="12" style={s('fill:var(--acTint);stroke:var(--ac)')}></rect>
                    <text x="700" y="166" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Tokyo</text>
                    <text x="700" y="181" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--dn)')}>¥{v.icPx.tepco}</text>
                    <rect x="518" y="206" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="565" y="221" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Chubu</text>
                    <text x="565" y="236" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>¥{v.icPx.chubu}</text>
                    <rect x="403" y="91" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="450" y="106" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Hokuriku</text>
                    <text x="450" y="121" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>¥{v.icPx.hokuriku}</text>
                    <rect x="378" y="206" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="425" y="221" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Kansai</text>
                    <text x="425" y="236" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>¥{v.icPx.kansai}</text>
                    <rect x="203" y="166" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="250" y="181" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Chugoku</text>
                    <text x="250" y="196" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>¥{v.icPx.chugoku}</text>
                    <rect x="253" y="271" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="300" y="286" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Shikoku</text>
                    <text x="300" y="301" textAnchor="middle" fontSize="10" style={s('fill:var(--mut)')}>¥{v.icPx.shikoku}</text>
                    <rect x="38" y="246" width="94" height="38" rx="12" style={s('fill:var(--bg3);stroke:var(--bd2)')}></rect>
                    <text x="85" y="261" textAnchor="middle" fontSize="11.5" fontWeight="600" style={s('fill:var(--tx)')}>Kyushu</text>
                    <text x="85" y="276" textAnchor="middle" fontSize="10" fontWeight="600" style={s('fill:var(--up)')}>¥{v.icPx.kyushu}</text>
                  </svg>
                  <div style={s('display:flex;align-items:center;gap:16px;margin-top:8px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap;font-size:11.5px;color:var(--tx2)')}>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:14px;height:4px;border-radius:2px;background:#5DCAA5')}></span>&lt;55%</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:14px;height:4px;border-radius:2px;background:#FAC775')}></span>55–85%</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}><span style={s('width:14px;height:4px;border-radius:2px;background:#EF9F27')}></span>85–97%</span>
                    <span style={s('display:inline-flex;align-items:center;gap:6px;font-weight:600;color:var(--dn)')}><span style={s('width:14px;height:4px;border-radius:2px;background:#E24B4A')}></span>≥97% congested 混雑</span>
                    <span style={s('margin-left:auto;color:var(--mut)')}>▶ = net flow direction · utilization of TTC 運用容量に対する利用率</span>
                  </div>
                </div>

                {/* Line table */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Interconnector Lines <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>連系線一覧</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Latest slot 14:30 · spread = destination minus origin area price · 値差＝流入側−流出側</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>MW · ¥/kWh</span>
                  </div>
                  <div style={s('display:grid;grid-template-columns:1.6fr 1.2fr .55fr .55fr 1.2fr .6fr .8fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)')}>
                    <span>LINE · 連系線</span><span>ROUTE · 区間</span><span style={s('text-align:right')}>FLOW</span><span style={s('text-align:right')}>TTC</span><span style={s('text-align:right')}>UTILIZATION 利用率</span><span style={s('text-align:right')}>SPREAD 値差</span><span style={s('text-align:right')}>CONGESTED 混雑</span>
                  </div>
                  {v.icRows.map((ln) => (
                    <Fragment key={ln.key}>
                    <Hoverable base={expandedLine === ln.key ? 'display:grid;grid-template-columns:1.6fr 1.2fr .55fr .55fr 1.2fr .6fr .8fr;gap:0;align-items:center;padding:9px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer;background:var(--hov)' : 'display:grid;grid-template-columns:1.6fr 1.2fr .55fr .55fr 1.2fr .6fr .8fr;gap:0;align-items:center;padding:9px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer'} hover="background:var(--hov)" onClick={() => tLine(ln.key)}>
                      <span style={s('min-width:0')}><span style={s('display:block;font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{expandedLine === ln.key ? '▾ ' : '▸ '}{ln.n1}</span><span style={s('display:block;font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{ln.n2}</span></span>
                      <span style={s('font-size:12px;color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{ln.route}</span>
                      <span style={s("text-align:right;font-size:12.5px;font-weight:600;font-feature-settings:'tnum' 1")}>{ln.flow}</span>
                      <span style={s("text-align:right;font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{ln.cap}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:64px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={ln.barS}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{ln.pct}</span>
                      </span>
                      <span style={s("text-align:right;font-size:12.5px;font-weight:600;font-feature-settings:'tnum' 1")}>{ln.spread}</span>
                      <span style={s('text-align:right')}><span style={ln.congS}>{ln.congTxt}</span></span>
                    </Hoverable>
                    {expandedLine === ln.key ? (
                      <div style={s('padding:12px 10px 16px;border-bottom:1px solid var(--dv);background:var(--bg0)')}>
                        <div style={s('display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px;flex-wrap:wrap;gap:6px')}>
                          <span style={s('font-size:12.5px;font-weight:600')}>{L === 'ja' ? '当日の30分コマ別 フロー・利用率' : 'Intraday flow & utilization · 48 × 30-min slots'}</span>
                          <span style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>{ln.route} · {L === 'ja' ? 'ピーク' : 'peak'} {ln.peakPct}% · TTC {ln.cap} MW · {L === 'ja' ? '値差' : 'spread'} {ln.spread}</span>
                        </div>
                        <div style={s('display:grid;grid-template-columns:repeat(48,1fr);gap:2px;align-items:end;height:64px')}>
                          {ln.bars.map((c, ci) => (
                            <span key={ci} title={c.t} style={{ ...c.barCol, height: c.h + '%' }}></span>
                          ))}
                        </div>
                        <div style={s("display:flex;justify-content:space-between;font-size:10.5px;color:var(--mut);margin-top:6px;font-feature-settings:'tnum' 1")}><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:30</span></div>
                        <div style={s('font-size:10.5px;color:var(--mut);margin-top:6px')}>{L === 'ja' ? 'バーの高さ＝運用容量に対する利用率 · ホバーでMW表示' : 'Bar height = utilization of TTC · hover for MW'}</div>
                      </div>
                    ) : null}
                    </Fragment>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>TTC = total transfer capability 運用容量 · flows are net of counter-flows · click a line for hourly detail</div>
                </div>

                {/* Congestion timeline */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Congestion Timeline <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>混雑タイムライン</span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Utilization by 30-min slot · today {v.icTodayDate} · 30分コマ別利用率</div>
                    </div>
                    <div style={s('display:flex;align-items:center;gap:5px;font-size:11px;color:var(--mut);flex-shrink:0;padding-top:4px')}>
                      <span>free</span>
                      <span style={s('width:16px;height:10px;background:#9FE1CB;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#5DCAA5;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#FAC775;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#EF9F27;border-radius:2px')}></span>
                      <span style={s('width:16px;height:10px;background:#E24B4A;border-radius:2px')}></span>
                      <span>congested</span>
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
                        <span style={s("width:52px;flex-shrink:0;text-align:right;font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>{tl.congTxt}</span>
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
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.drJkmV} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>$/MMBtu</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>ICE · close {v.drCloseDate} · vs prior close</div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{v.drJkmC}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Newcastle coal<br />ニューカッスル石炭</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.drNclV} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>$/t</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>ICE FOB front-month · vs prior close</div>
                    <span style={v.drNclCS}>{v.drNclC}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>USD/JPY<br />ドル円</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{v.drFxV}</div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>TTM · weaker yen = costlier fuel imports</div>
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
                        <div style={s('font-size:16px;font-weight:600')}>Drivers vs Spot — Indexed <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>燃料・為替×スポット</span></div>
                        <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Rebased to 100 at window start · daily closes · spot = 9-area mean · 期初＝100</div>
                      </div>
                      <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;flex-shrink:0')}>
                        <span style={v.dr30S} onClick={() => setDrRange('30D')}>30D</span>
                        <span style={v.dr90S} onClick={() => setDrRange('90D')}>90D</span>
                        <span style={v.dr1yS} onClick={() => setDrRange('1Y')}>1Y</span>
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
                        <polyline points={v.drNclPts} fill="none" stroke="#B08968" strokeWidth="1.8" strokeLinejoin="round" opacity={v.drNclOp}></polyline>
                        <polyline points={v.drFxPts} fill="none" stroke="#8AB17D" strokeWidth="1.8" strokeLinejoin="round" opacity={v.drFxOp}></polyline>
                        <polyline points={v.drJkmPts} fill="none" stroke="#E76F51" strokeWidth="1.8" strokeLinejoin="round" opacity={v.drJkmOp}></polyline>
                        <polyline points={v.drSpotPts} fill="none" stroke="#00A5CF" strokeWidth="2.6" strokeLinejoin="round"></polyline>
                      </svg>
                    </div>
                    <div style={s('display:flex;align-items:center;gap:16px;margin-top:10px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap')}>
                      <span style={s('display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--tx2)')}><span style={s('width:20px;height:3px;border-radius:2px;background:#00A5CF')}></span>JEPX spot スポット</span>
                      <span style={v.drJkmLegS} onClick={tJkm}><span style={s('width:20px;height:3px;border-radius:2px;background:#E76F51')}></span>JKM</span>
                      <span style={v.drNclLegS} onClick={tNcl}><span style={s('width:20px;height:3px;border-radius:2px;background:#B08968')}></span>Newcastle 石炭</span>
                      <span style={v.drFxLegS} onClick={tFx}><span style={s('width:20px;height:3px;border-radius:2px;background:#8AB17D')}></span>USD/JPY</span>
                      <span style={s('margin-left:auto;font-size:11px;color:var(--mut)')}>Click legend to toggle · 凡例クリックで切替</span>
                    </div>
                  </div>

                  {/* Driver detail panel */}
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);display:flex;flex-direction:column;min-width:0')}>
                    <div style={s('font-size:16px;font-weight:600')}>Driver Detail <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>ドライバー詳細</span></div>
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
      {renderSidebar()}

      {/* ============ MAIN COLUMN ============ */}
      <div style={s('flex:1;min-width:0;display:flex;flex-direction:column;position:relative')}>
        {renderTopBar()}

        {/* Scrollable content */}
        <div style={s('flex:1;overflow-y:auto;padding:26px 32px 40px')}>
          <div style={s('max-width:1500px;margin:0 auto;display:flex;flex-direction:column;gap:20px')}>
            {renderPageHeader()}
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
