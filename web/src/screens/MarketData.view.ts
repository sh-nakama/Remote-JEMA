// Market Data view model: everything the screen displays, computed from its controls and live data.
// Split out of MarketData.tsx verbatim; the screen memoises buildMarketView on the same inputs.
import type { Lang } from '../lib/app'
import { CHIP_BASE, makeChip, segBase, filterChipBase, slotLabel, fmtDate, MONTHS } from '../lib/chartkit'
import { gaussian as G } from '../lib/fixtures'
import { gapSegments, segPoints, bandPoints, PLOT_X0, PLOT_W } from '../lib/chart'
import type { CSS } from '../lib/style'
import { sampleNote } from '../lib/freshness'
import { areas, areaDefs, balProducts, icDefs, icSample, icSampleUtil, drv, drDefs } from './MarketData.data'
import {
  useWholesaleLive,
  windowLive,
  windowSupply,
  FUELS,
  useDriversLive,
  useBalancingLive,
  BAL_CODES,
  useTielineLive,
  useAreaDayLive,
  tielineStats,
  DRIVER_KEYS,
  DAY_MS,
  effectiveRangeDays,
  rangeClampNote,
  latestT,
  latestPriceT,
  latestSupplyT,
} from './MarketData.live'
import type { DriverKey, TlLine } from './MarketData.live'

export type View = 'wholesale' | 'balancing' | 'interco' | 'drivers'
export type Range = '7D' | '30D' | '60D' | '1Y'
export type Gran = 'Native' | 'Daily' | 'Weekly' | 'Monthly'
export type DrRange = '30D' | '90D' | '1Y'

/** Inclusive epoch-ms window a chart is plotted over. */
export type Domain = [number, number]

// makeChip / segBase / filterChipBase / slotLabel / fmtDate now live in
// lib/chartkit (shared with the other screens).

// Fixture-only: the synthetic series have no real dates, so "days ago" is counted
// back from the fixtures' frozen "today". Live data labels use its actual datetimes.
export function dateLabel(daysAgo: number): string {
  const d = new Date(2026, 6, 2)
  d.setDate(d.getDate() - daysAgo)
  return MONTHS[d.getMonth()] + ' ' + d.getDate()
}

export const SHOW_HEATMAP = true

/** ISO datetime → hover label: "Jul 11", or "Jul 11 22:30" for intraday slots.
 *  Non-ISO strings (fixture day labels like "Jun 12") are shown verbatim. */
export function fmtDT(v: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(v)
  if (!m) return v
  const lbl = MONTHS[Number(m[2]) - 1] + ' ' + Number(m[3])
  return m[4] && !(m[4] === '00' && m[5] === '00') ? lbl + ' ' + m[4] + ':' + m[5] : lbl
}

/** Epoch ms → "Jul 11" / "Jul 11 22:30" (UTC — snapshot datetimes are wall-clock JST). */
export function fmtEpoch(t: number): string {
  if (!Number.isFinite(t)) return ''
  const d = new Date(t)
  const lbl = MONTHS[d.getUTCMonth()] + ' ' + d.getUTCDate()
  const hh = d.getUTCHours()
  const mm = d.getUTCMinutes()
  return hh || mm ? lbl + ' ' + String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0') : lbl
}

/** Start / middle / end tick labels for an epoch-ms domain. */
export function axisLabels(d: Domain): [string, string, string] {
  return [fmtEpoch(d[0]), fmtEpoch((d[0] + d[1]) / 2), fmtEpoch(d[1])]
}

export interface MarketViewInput {
  view: View
  range: Range
  gran: Gran
  sel: Record<string, boolean>
  closed: Record<string, boolean>
  expanded: Record<string, boolean>
  zoom: Record<string, Domain>
  drRange: DrRange
  drOn: Record<DriverKey, boolean>
  L: Lang
  dark: boolean
  live: ReturnType<typeof useWholesaleLive>
  driversLive: ReturnType<typeof useDriversLive>
  balLive: ReturnType<typeof useBalancingLive>
  tielineLive: ReturnType<typeof useTielineLive>
  areaDayLive: ReturnType<typeof useAreaDayLive>
}

export function buildMarketView({ view, range, gran, sel, closed, expanded, zoom, drRange, drOn, L, dark, live, driversLive, balLive, tielineLive, areaDayLive }: MarketViewInput) {
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
      t: b.days.map(() => NaN),
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

  // KPIs come from whichever selected areas loaded; fixtures only while none has.
  const liveSel = live.ready ? selAreas.filter((a) => !!live.areas[a.key]) : []
  const useLive = liveSel.length > 0

  // ---- KPIs (live daily series when loaded, else fixtures) ----
  const act = useLive ? liveSel : selAreas.length ? selAreas : areas
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
  // The stats export has one peak figure and no prior period, so there is no real change to show.
  kDemC.txt = useLive ? '—' : '▲ +1.8% vs prior period'

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

  /** Stacked-area polygons, one list per layer: layer k spans cumulative(k-1)..cumulative(k) per gap segment. */
  const stackPolys = (
    layers: number[][],
    segs: [number, number][],
    xOf: (i: number) => number,
    y: (val: number) => number,
  ): string[][] => {
    const cum: number[][] = []
    layers.forEach((l, k) => cum.push(l.map((v, i) => v + (k ? cum[k - 1][i] : 0))))
    return layers.map((_l, k) =>
      segs.map((sg) => bandPoints(sg, xOf, (i) => y(cum[k][i]), (i) => y(k ? cum[k - 1][i] : 0))),
    )
  }

  // ---- plotted time window ----
  // Issue #22: the window is now derived from the *selected range*, anchored at
  // the newest datetime in the data — not from the union of whatever each area
  // happens to carry. Coverage differs wildly per area (one TSO's supply feed can
  // lag a month), and taking the union let a single stale series stretch the axis
  // so every chart drew its data as a sliver at one edge, regardless of the range
  // chip. A 7D chip now always draws exactly 7 days; a short series simply stops
  // early and leaves honest whitespace.
  const rangeDays = effectiveRangeDays(gran, range)
  let anchorMs = NaN
  for (const a of selAreas) {
    const la = live.ready ? live.areas[a.key] ?? null : null
    if (!la) continue
    const t = latestT(la)
    if (Number.isFinite(t) && !(t <= anchorMs)) anchorMs = t
  }
  const haveDomain = Number.isFinite(anchorMs)
  const baseDomain: Domain = haveDomain ? [anchorMs - rangeDays * DAY_MS, anchorMs] : [0, 1]

  /** For each ascending time in `from`, the index of the nearest time in `to`,
   *  or −1 when there is no sample within `tol` ms. Both inputs are ascending,
   *  so one pass suffices.
   *
   *  The tolerance matters: without it, a supply feed that lags the price feed by
   *  weeks still resolves to *some* index, and the combined chart's tooltip would
   *  report a month-old generation mix under today's timestamp — re-fabricating
   *  exactly the data the gap-segmented polygons deliberately leave blank. */
  const nearestMap = (from: number[], to: number[], tol: number): number[] => {
    if (!to.length) return from.map(() => -1)
    const out: number[] = []
    let j = 0
    for (const t of from) {
      while (j + 1 < to.length && Math.abs(to[j + 1] - t) <= Math.abs(to[j] - t)) j++
      out.push(Math.abs(to[j] - t) <= tol ? j : -1)
    }
    return out
  }

  /** Median sample spacing of an ascending series, or NaN when undeterminable. */
  const cadence = (t: number[]): number => {
    const d: number[] = []
    for (let i = 1; i < t.length; i++) {
      const g = t[i] - t[i - 1]
      if (Number.isFinite(g) && g > 0) d.push(g)
    }
    if (!d.length) return NaN
    d.sort((a, b) => a - b)
    return d[Math.floor(d.length / 2)]
  }

  // Expanded (combined mix + price) chart geometry: same 480-wide viewBox, taller.
  const EXP_H = 320

  const sections = selAreas.map((a) => {
    // Per-area live/fixture: each chart uses its own snapshot when loaded, so a
    // single missing/corrupt area falls back alone (and says so in its header).
    const la = live.ready ? (live.areas[a.key] ?? null) : null
    const useTime = !!la && haveDomain
    // Drag-selected zoom is per area, so one area can be inspected closely while
    // the others stay on the range window.
    const zoomDom = zoom[a.key] ?? null
    const dom: Domain = useTime ? zoomDom ?? baseDomain : [0, 1]
    const xOfT = (t: number) => PLOT_X0 + ((t - dom[0]) / (dom[1] - dom[0])) * PLOT_W
    /** viewBox x → epoch ms (brush selections come back in viewBox units). */
    const tOfX = (x: number) => dom[0] + ((x - PLOT_X0) / PLOT_W) * (dom[1] - dom[0])

    const w = la ? windowLive(la, dom[0], dom[1]) : winLabeled(a)
    const n = w.avg.length
    const lo = n ? Math.min(...w.min) * 0.92 : 0
    const hi = n ? Math.max(...w.max) * 1.05 : 1
    const span = hi - lo || 1
    const py = (val: number) => 150 - ((val - lo) / span) * 135
    const pyE = (val: number) => EXP_H - 14 - ((val - lo) / span) * (EXP_H - 32)
    const pxs = useTime
      ? w.t.map(xOfT)
      : w.avg.map((_v, i) => PLOT_X0 + (i / Math.max(1, n - 1)) * PLOT_W)
    // Break the line wherever the series has a hole: a single polyline would
    // bridge a multi-week gap with a straight segment that reads as real data.
    const pSegs = (useTime ? gapSegments(w.t) : n ? ([[0, n - 1]] as [number, number][]) : []).filter(
      ([s0, s1]) => s1 > s0,
    )
    const lineOf = (arr: number[], y: (val: number) => number) =>
      pSegs.map((sg) => segPoints(sg, (i) => pxs[i], (i) => y(arr[i])))
    const bandOf = (y: (val: number) => number) =>
      pSegs.map((sg) => bandPoints(sg, (i) => pxs[i], (i) => y(w.max[i]), (i) => y(w.min[i])))

    // Compare overlay: the equal-length window immediately before this one, drawn
    // at its own timestamps shifted forward by the window span so it shares this
    // chart's axis. Shifted by time rather than aligned by slot index — the series
    // have holes, so slot-for-slot would pair unrelated timestamps. Clamped to the
    // plot box so an outlier prior period can't escape the chart. Always computed;
    // JSX only draws it when `compare`.
    const cmpSpan = dom[1] - dom[0]
    const wPrev = la && useTime ? windowLive(la, dom[0] - cmpSpan, dom[0]) : null
    const pyC = (val: number) => Math.max(12, Math.min(150, py(val)))
    const pCmp =
      wPrev && wPrev.avg.length > 1
        ? gapSegments(wPrev.t)
            .filter(([s0, s1]) => s1 > s0)
            .map((sg) =>
              segPoints(sg, (i) => xOfT(wPrev.t[i] + cmpSpan), (i) => pyC(wPrev.avg[i])),
            )
        : []

    // generation mix — real windowed supply when live (gran-responsive), else synthetic "today"
    const supW = la ? windowSupply(la, dom[0], dom[1]) : null
    let mixPolys: string[][]
    let demandLine: string[]
    let expMixPolys: string[][] = []
    let expDemand: string[] = []
    let peakMWStr: string
    let mixMeta: string
    // Raw windowed mix arrays + geometry for the hover layer.
    let supN = 0
    let supYmax = 1
    let supDtA: string[] = []
    let supTA: number[] = []
    let supDemandA: number[] = []
    let supFuelA: number[][] = FUELS.map(() => [])
    let supXs: number[] = []
    if (supW) {
      const nS = supW.demand.length
      const Xs = (i: number) => (useTime ? xOfT(supW.t[i]) : PLOT_X0 + (i / Math.max(1, nS - 1)) * PLOT_W)
      const my = (val: number) => 152 - (val / supW.ymax) * 140
      const myE = (val: number) => EXP_H - 12 - (val / supW.ymax) * (EXP_H - 28)
      const sSegs = (useTime ? gapSegments(supW.t) : nS ? ([[0, nS - 1]] as [number, number][]) : []).filter(
        ([s0, s1]) => s1 > s0,
      )
      const bands = (y: (val: number) => number) => ({
        polys: stackPolys(supW.fuels, sSegs, Xs, y),
        dem: sSegs.map((sg) => segPoints(sg, Xs, (i) => y(supW.demand[i]))),
      })
      const std = bands(my)
      mixPolys = std.polys
      demandLine = std.dem
      const exp = bands(myE)
      expMixPolys = exp.polys
      expDemand = exp.dem
      peakMWStr = Math.round(Math.max(1, ...supW.demand)).toLocaleString('en-US')
      mixMeta = range + ' · ' + gran + ' · MW by technology'
      supN = nS
      supYmax = supW.ymax
      supDtA = supW.dt
      supTA = supW.t
      supDemandA = supW.demand
      supFuelA = supW.fuels
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
      const myE = (val: number) => EXP_H - 12 - (val / ymax) * (EXP_H - 28)
      const demLine = dem.map((val) => val * 1.018)
      const fx = (i: number) => X(i, 48)
      const seg: [number, number] = [0, 47]
      // Sample data only knows baseload / thermal / solar: file them under nuclear / LNG / solar.
      const fx48 = FUELS.map((f) =>
        f.key === 'nuclear' ? c1 : f.key === 'lng' ? c2.map((val, i) => Math.max(0, val - c1[i])) : f.key === 'solar_actual' ? c3.map((val, i) => Math.max(0, val - c2[i])) : c1.map(() => 0),
      )
      const bands = (y: (val: number) => number) => ({
        polys: stackPolys(fx48, [seg], fx, y),
        dem: [segPoints(seg, fx, (i) => y(demLine[i]))],
      })
      const std = bands(my)
      mixPolys = std.polys
      demandLine = std.dem
      const exp = bands(myE)
      expMixPolys = exp.polys
      expDemand = exp.dem
      peakMWStr = P.toLocaleString('en-US')
      mixMeta = 'today · 14 fuels grouped · MW'
      // hover arrays for the synthetic "today" mix (half-hourly, oldest→newest)
      supN = 48
      supYmax = ymax
      supDtA = Array.from({ length: 48 }, (_, i) => String(Math.floor(i / 2)).padStart(2, '0') + ':' + (i % 2 === 0 ? '00' : '30'))
      supTA = Array.from({ length: 48 }, () => NaN)
      supDemandA = demLine
      supFuelA = fx48
      supXs = Array.from({ length: 48 }, (_v, i) => X(i, 48))
    }

    const open = !closed[a.key]
    // x-axis tick labels (start / mid / end) come from the *requested* window, so
    // they can never contradict the range chip — even when the series is short.
    const domAx: [string, string, string] = useTime ? axisLabels(dom) : ['', '', '']
    const priceAx: [string, string, string] = useTime ? domAx : w.labels
    const mixAx: [string, string, string] = useTime
      ? domAx
      : [
          supN ? fmtDT(supDtA[0]) : '',
          supN ? fmtDT(supDtA[Math.floor((supN - 1) / 2)]) : '',
          supN ? fmtDT(supDtA[supN - 1]) : '',
        ]

    // Coverage honesty: a series whose newest point predates the window's right
    // edge stops early and leaves whitespace — say so instead of letting it read
    // as "no data today". Measured from the newest row that actually carries a
    // value, since exports pad the tail with all-null rows.
    const staleNote = (t: number): string => {
      if (!useTime || !Number.isFinite(t)) return ''
      const behind = Math.floor((dom[1] - t) / DAY_MS)
      if (behind < 2) return ''
      return `through ${fmtEpoch(t)} · ${behind}d behind`
    }
    const priceStale = la ? staleNote(latestPriceT(la)) : ''
    const supStale = la ? staleNote(latestSupplyT(la)) : ''

    // Combined chart hover walks the denser of the two series and maps across.
    // A match is only accepted within ~1.5 samples of the target series' own
    // cadence, so the tooltip stays silent over a gap instead of inventing values.
    const priceTol = (cadence(w.t) || 30 * 60_000) * 1.5
    const supTol = (cadence(supTA) || 30 * 60_000) * 1.5
    const cmbOnPrice = n >= supN
    const cmbXs = cmbOnPrice ? pxs : supXs
    const cmbN = cmbOnPrice ? n : supN
    const cmbDt = cmbOnPrice ? w.dt : supDtA
    const cmbPriceIdx = cmbOnPrice
      ? w.avg.map((_v, i) => i)
      : useTime
        ? nearestMap(supTA, w.t, priceTol)
        : supDemandA.map(() => -1)
    const cmbSupIdx = cmbOnPrice
      ? useTime
        ? nearestMap(w.t, supTA, supTol)
        : w.avg.map(() => -1)
      : supDemandA.map((_v, i) => i)

    const zoomLabel = zoomDom ? `Zoomed ${fmtEpoch(zoomDom[0])} → ${fmtEpoch(zoomDom[1])}` : ''

    return {
      key: a.key,
      title: L === 'ja' ? a.ja + ' / ' + a.en : a.en + ' / ' + a.ja,
      sub: live.ready && !la ? sampleNote(L) : '',
      meta:
        'latest ¥' +
        (la && la.latest != null ? la.latest.toFixed(2) : a.intraday[29].toFixed(2)) +
        ' · ' +
        range +
        ' · ' +
        gran,
      open,
      closed: !open,
      expanded: !!expanded[a.key],
      zoomLabel,
      canZoom: useTime,
      tOfX,
      mixPolys,
      fuelLegend: FUELS.map((f, k) => ({ ...f, used: supFuelA[k].some((x) => x > 0) })).filter((f) => f.used),
      mixMeta,
      demand: demandLine,
      peakMW: peakMWStr,
      band: bandOf(py),
      pMax: lineOf(w.max, py),
      pAvg: lineOf(w.avg, py),
      pMin: lineOf(w.min, py),
      pCmp,
      vMax: n ? Math.max(...w.max).toFixed(1) : '—',
      vAvg: n ? mean(w.avg).toFixed(1) : '—',
      vMin: n ? Math.min(...w.min).toFixed(1) : '—',
      rangeLabel: range,
      granLabel: gran,
      priceAx,
      mixAx,
      priceStale,
      supStale,
      // hover geometry — price chart
      n,
      // Exposed so the hover dot uses the same guarded scale as the polylines;
      // computing it inline in JSX divided by an unguarded `hi - lo`, which is 0
      // when a (zoomed) window holds only identical prices — e.g. all ¥0.00.
      pDotY: (i: number) => (Number.isFinite(w.avg[i]) ? py(w.avg[i]) : 150),
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
      supFuelA,
      // combined (expanded) chart
      expH: EXP_H,
      expMixPolys,
      expDemand,
      expBand: bandOf(pyE),
      expPMax: lineOf(w.max, pyE),
      expPAvg: lineOf(w.avg, pyE),
      expPMin: lineOf(w.min, pyE),
      expDotY: (i: number) => {
        const k = cmbPriceIdx[i]
        // NaN suppresses the dot in ChartFrame; a fallback position would plant a
        // marker where the price series has no sample.
        return k >= 0 && Number.isFinite(w.avg[k]) ? pyE(w.avg[k]) : NaN
      },
      cmbN,
      cmbXs,
      cmbDt,
      cmbPriceIdx,
      cmbSupIdx,
      mwTicks: [supYmax, supYmax / 2, 0].map((val) => Math.round(val).toLocaleString('en-US')),
      yenTicks: [hi, (hi + lo) / 2, lo].map((val) => val.toFixed(1)),
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

  // ---- balancing: the latest EPRX day, nationally (fixtures while loading) ----
  const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US')
  const pName = (bi: number) => (L === 'ja' ? balProducts[bi].jp : balProducts[bi].en)
  const shortS = (n: number): CSS =>
    (n > 0
      ? { fontSize: 11, fontWeight: 600, background: 'var(--warnBg)', color: 'var(--warnTx)', borderRadius: 6, padding: '1px 8px', fontFeatureSettings: "'tnum' 1", whiteSpace: 'nowrap' }
      : { fontSize: 11.5, color: 'var(--fnt)', fontFeatureSettings: "'tnum' 1", whiteSpace: 'nowrap' }) as CSS
  const balRows = balProducts.map((b, bi) => {
    const code = BAL_CODES[bi]
    const lv = balLive.ready ? balLive.rows[code] : undefined
    // Live but without this product on the latest day: say so rather than show a sample figure.
    const gone = balLive.ready && !lv
    const ach = lv ? lv.ach : gone ? null : b.ach
    const short = lv ? lv.short : gone ? null : b.short
    const areaDetail = (balLive.ready ? balLive.areaRows[code] : undefined) || []
    return {
      jp: b.jp,
      en: b.en,
      code,
      price: lv ? (lv.price != null ? lv.price.toFixed(2) : '—') : gone ? '—' : b.price,
      proc: lv ? fmtInt(lv.proc) : gone ? '—' : b.proc,
      off: lv ? fmtInt(lv.off) : gone ? '—' : b.off,
      ach: ach != null ? Math.round(ach) + '%' : '—',
      shortTxt: short != null ? short + ' / ' + (lv ? lv.slots : 48) : '—',
      shortS: shortS(short ?? 0),
      areaRows: areaDetail.map((r) => ({
        area: r.area,
        name: areaDefs.find((a) => a.key === r.area)?.[L === 'ja' ? 'ja' : 'en'] || r.area,
        price: r.price != null ? '¥' + r.price.toFixed(2) : '—',
        proc: fmtInt(r.proc),
        off: fmtInt(r.off),
        ach: r.ach != null ? Math.round(r.ach) : null,
      })),
      dot: { width: 8, height: 8, borderRadius: 999, background: dark ? b.cd : b.c, flexShrink: 0 } as CSS,
      bar: { display: 'block', width: Math.min(100, ach ?? 0) + '%', height: '100%', borderRadius: 3, background: dark ? b.cd : b.c } as CSS,
    }
  })
  // National KPIs with real day-on-day changes. A missing prior day leaves the chip out.
  const bDay = balLive.ready ? balLive.day : null
  const bPrev = balLive.ready ? balLive.prev : null
  const dayChip = (cur: number | null | undefined, prev: number | null | undefined, dec: number) =>
    cur != null && prev != null && prev !== 0 ? makeChip(cur - prev, ((cur - prev) / prev) * 100, dec) : null
  const balPriceChip = balLive.ready ? dayChip(bDay?.price, bPrev?.price, 2) : { txt: '▼ −0.32 (−6.2%)', style: {} }
  const balProcChip = balLive.ready
    ? dayChip(bDay?.contracted_mw, bPrev?.contracted_mw, 0)
    : { txt: '▲ +214 (+2.4%)', style: { ...CHIP_BASE, background: 'var(--upBg)', color: 'var(--up)' } as CSS }
  // The product with the most short slots (ties: the larger gap) heads the shortfall card.
  let worst = -1
  if (balLive.ready)
    BAL_CODES.forEach((code, bi) => {
      const r = balLive.rows[code]
      const w = worst >= 0 ? balLive.rows[BAL_CODES[worst]] : undefined
      if (r && (!w || r.short > w.short || (r.short === w.short && (r.maxGap ?? 0) > (w.maxGap ?? 0)))) worst = bi
    })
  const wr = worst >= 0 ? balLive.rows[BAL_CODES[worst]] : undefined
  let balShortSub = '三次② evening ramp · 17:00–18:30'
  let balShortChip: { txt: string; style: CSS } | null = {
    txt: "▼ −2 slots vs y'day",
    style: { ...CHIP_BASE, background: 'var(--upBg)', color: 'var(--up)' },
  }
  if (balLive.ready) {
    balShortSub = !wr
      ? '—'
      : wr.short > 0 && wr.run
        ? `${pName(worst)} · ${L === 'ja' ? '最長' : 'longest run'} ${wr.run.start}–${wr.run.end}`
        : L === 'ja' ? '全商品で必要量を確保' : 'every product met its requirement'
    balShortChip = null
    if (wr && wr.prevShort != null) {
      const d = wr.short - wr.prevShort
      // Fewer short slots is the good direction, so the colours invert.
      balShortChip = {
        txt: (d > 0 ? '▲ +' : d < 0 ? '▼ −' : '± ') + Math.abs(d) + (L === 'ja' ? ' コマ 前日比' : ' slots vs prior day'),
        style: {
          ...CHIP_BASE,
          background: d > 0 ? 'var(--dnBg)' : d < 0 ? 'var(--upBg)' : 'rgba(138,147,163,.14)',
          color: d > 0 ? 'var(--dn)' : d < 0 ? 'var(--up)' : 'var(--mut)',
        },
      }
    }
  }

  // ---- interconnectors: ΔkW reserved for cross-area balancing vs the limit (EPRX) ----
  const icLines: TlLine[] = tielineLive.ready
    ? tielineLive.lines
    : icSample.map((l, li) => ({
        pair: l.pair,
        key: l.key,
        fwd: { from: l.from, to: l.to, reserved: icSampleUtil[li].map((u) => u * l.limit), limit: icSampleUtil[li].map(() => l.limit) },
        rev: { from: l.to, to: l.from, reserved: icSampleUtil[li].map(() => 0), limit: icSampleUtil[li].map(() => 0) },
      }))
  const icAreaName = (k: string) => {
    const a = areaDefs.find((x) => x.key === k)
    return a ? (L === 'ja' ? a.ja : a.en) : k
  }
  const side = (keys: string[]) => keys.map(icAreaName).join(L === 'ja' ? '・' : ' + ')
  // Node prices: JEPX daily area averages (a sample curve only while system.json loads).
  const px: Record<string, number> = {}
  areas.forEach((a) => {
    px[a.key] = areaDayLive.ready ? (areaDayLive.avg[a.key] ?? NaN) : a.intraday[29]
  })
  const sidePx = (keys: string[]) => {
    const xs = keys.map((k) => px[k]).filter((x) => Number.isFinite(x))
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN
  }
  const fmtMW = (n: number) => Math.round(n).toLocaleString('en-US')
  const uColor = (val: number) =>
    !Number.isFinite(val) ? '#B4BCC9' : val >= 0.97 ? '#E24B4A' : val >= 0.85 ? '#EF9F27' : val >= 0.55 ? '#FAC775' : val >= 0.35 ? '#5DCAA5' : '#9FE1CB'
  // North to south; the combined Chubu/Hokuriku/Kansai zones sit between Tokyo–Chubu and Kansai–Chugoku.
  const IC_ORDER: Record<string, number> = { hh: 0, st: 1, fc: 2, ck: 4, sk: 5, cs: 6, kq: 7 }
  const icRank = (ln: TlLine) => (ln.key ? (IC_ORDER[ln.key] ?? 8) : 3)
  const icRows = [...icLines].sort((a, b) => icRank(a) - icRank(b)).map((ln) => {
    const st = tielineStats(ln)
    const def = ln.key ? icDefs.find((d) => d.key === ln.key) : undefined
    const peakDir = st.peak?.rev ? ln.rev : ln.fwd
    const route = side(peakDir.from) + ' → ' + side(peakDir.to)
    const pct = st.peak ? Math.round(st.peak.share * 100) : 0
    const spread = sidePx(peakDir.to) - sidePx(peakDir.from)
    const tip = (x: (typeof st.slots)[number], i: number) => {
      const d = x.rev ? ln.rev : ln.fwd
      return (
        (def?.short ?? ln.pair) + ' ' + slotLabel(i) + ' · ' +
        (Number.isFinite(x.share) ? Math.round(x.share * 100) + '% · ' + fmtMW(x.reserved) + ' / ' + fmtMW(x.limit) + ' MW · ' + side(d.from) + ' → ' + side(d.to) : L === 'ja' ? '上限なし' : 'no limit')
      )
    }
    return {
      key: ln.pair,
      icKey: ln.key,
      ln,
      st,
      n1: def ? (L === 'ja' ? def.ja : def.en) : side(ln.fwd.from) + ' → ' + side(ln.fwd.to),
      n2: def ? (L === 'ja' ? def.en : def.ja) : L === 'ja' ? 'combined zone' : '合成エリア（EPRX公表単位）',
      short: def?.short ?? ln.pair,
      route,
      reserved: st.peak ? fmtMW(st.peak.reserved) : '0',
      limit: st.peak ? fmtMW(st.peak.limit) : '0',
      pct: st.peak ? pct + '%' : '—',
      peakAt: st.peakIdx >= 0 ? slotLabel(st.peakIdx) : '',
      barS: { display: 'block', width: pct + '%', height: '100%', borderRadius: 3, background: uColor(st.peak?.share ?? NaN) } as CSS,
      spread: Number.isFinite(spread) ? (spread >= 0 ? '+¥' : '−¥') + Math.abs(spread).toFixed(2) : '—',
      atTxt: st.peak ? st.atLimit + ' / ' + st.slots.length : L === 'ja' ? '確保なし' : 'none reserved',
      atShort: st.peak ? st.atLimit + ' / ' + st.slots.length : '—',
      atS: shortS(st.atLimit),
      bars: st.slots.map((x, i) => ({
        h: Number.isFinite(x.share) ? Math.max(3, Math.round(x.share * 100)) : 3,
        barCol: { display: 'block', width: '100%', borderRadius: 2, background: uColor(x.share) } as CSS,
        t: tip(x, i),
      })),
      strip: st.slots.map((x, i) => ({
        s: { height: 14, borderRadius: 2, background: uColor(x.share) } as CSS,
        t: tip(x, i),
      })),
    }
  })
  const icLimited = icRows.filter((r) => r.st.peak)
  const icAtLimit = icLimited.filter((r) => r.st.atLimit > 0)
  const icAtSlots = icLimited.reduce((n, r) => n + r.st.atLimit, 0)
  const icTop = icLimited.reduce<(typeof icRows)[number] | null>((a, r) => (!a || r.st.peak!.share > a.st.peak!.share ? r : a), null)
  const icResAvg = icRows.reduce((n, r) => n + r.st.avgReserved, 0)
  const icLimAvg = icRows.reduce((n, r) => n + r.st.avgLimit, 0)
  // Widest JEPX area spread of the day.
  const pxKeys = areas.map((a) => a.key).filter((k) => Number.isFinite(px[k]))
  const pxHi = pxKeys.reduce<string | null>((a, k) => (a == null || px[k] > px[a] ? k : a), null)
  const pxLo = pxKeys.reduce<string | null>((a, k) => (a == null || px[k] < px[a] ? k : a), null)
  // Map: the seven physical lines drawn between node centres; the combined zones get an outline.
  const IC_NODE: Record<string, [number, number]> = {
    hokkaido: [885, 35], tohoku: [795, 95], tepco: [700, 170], chubu: [565, 225], hokuriku: [450, 110],
    kansai: [425, 225], chugoku: [250, 185], shikoku: [300, 290], kyushu: [85, 265],
  }
  const IC_LABEL: Record<string, [number, number, 'middle' | 'end']> = {
    hh: [826, 44, 'middle'], st: [735, 116, 'middle'], fc: [626, 178, 'middle'], ck: [337, 187, 'middle'],
    sk: [372, 277, 'middle'], cs: [257, 242, 'end'], kq: [156, 205, 'middle'],
  }
  const ARROW_TXT: Record<string, string> = { '#FAC775': '#D99A2B', '#5DCAA5': '#2A9D8F', '#9FE1CB': '#2A9D8F' }
  const limTop = Math.max(1, ...icRows.map((r) => r.st.maxLimit))
  const icMap = icRows
    .filter((r) => r.icKey && IC_LABEL[r.icKey])
    .map((r) => {
      const [x1, y1] = IC_NODE[r.ln.fwd.from[0]]
      const [x2, y2] = IC_NODE[r.ln.fwd.to[0]]
      const back = !!r.st.peak?.rev
      const col = uColor(r.st.peak?.share ?? NaN)
      const [lx, ly, anchor] = IC_LABEL[r.icKey!]
      return {
        key: r.icKey!,
        x1, y1, x2, y2,
        mx: (x1 + x2) / 2,
        my: (y1 + y2) / 2,
        ang: Math.round((Math.atan2(back ? y1 - y2 : y2 - y1, back ? x1 - x2 : x2 - x1) * 180) / Math.PI),
        col,
        arrowCol: ARROW_TXT[col] ?? col,
        w: r.st.peak ? Math.round((2 + 5 * Math.sqrt(r.st.maxLimit / limTop)) * 10) / 10 : 1.5,
        dash: r.st.peak ? undefined : '4 4',
        label: r.st.peak ? r.reserved : '—',
        title: r.n1 + ' · ' + r.route + ' · ' + r.pct,
        lx, ly, anchor,
        has: !!r.st.peak,
      }
    })
  const icCombined = icRows.filter((r) => !r.icKey)
  const icCombPeak = icCombined.reduce((m, r) => Math.max(m, r.st.peak?.share ?? 0), 0)
  const icNodes = areas.map((a) => {
    const [cx, cy] = IC_NODE[a.key]
    return {
      key: a.key,
      name: a.en,
      cx,
      cy,
      px: Number.isFinite(px[a.key]) ? px[a.key].toFixed(2) : '—',
      pxCol: a.key === pxHi ? 'var(--dn)' : a.key === pxLo ? 'var(--up)' : 'var(--mut)',
      pxBold: a.key === pxHi || a.key === pxLo,
      acc: a.key === 'tepco',
    }
  })
  // ---- drivers (live fuels/FX when loaded, else fixtures) ----
  const dvLive = driversLive.ready
  const D: Record<'spot' | DriverKey, number[]> = dvLive
    ? { spot: driversLive.spot, lng: driversLive.lng, brent: driversLive.brent, fx: driversLive.fx }
    : drv
  // A series without closes (e.g. before its first scrape) is left off rather than drawn as zeros.
  const drHas: Record<DriverKey, boolean> = dvLive ? driversLive.has : { lng: true, brent: true, fx: true }
  const drAvail = Math.min(D.spot.length, ...DRIVER_KEYS.filter((k) => drHas[k]).map((k) => D[k].length))
  const drN = Math.min({ '30D': 30, '90D': 90, '1Y': 365 }[drRange], drAvail)
  const drStep = drRange === '1Y' ? 3 : 1
  const drIdx: number[] = []
  for (let d = drN - 1; d >= 0; d -= drStep) drIdx.push(d)
  const reb = (arr: number[]) => {
    const b = arr[drIdx[0]] || 1
    return drIdx.map((d) => (arr[d] / b) * 100)
  }
  const rSpot = reb(D.spot)
  const rDr: Record<DriverKey, number[]> = { lng: reb(D.lng), brent: reb(D.brent), fx: reb(D.fx) }
  const drShown = (k: DriverKey) => drOn[k] && drHas[k]
  const visVals = [...rSpot]
  for (const k of DRIVER_KEYS) if (drShown(k)) visVals.push(...rDr[k])
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
  const noCloses = L === 'ja' ? 'データ未取得' : 'no closes yet'
  const drK = (k: DriverKey) => {
    const arr = D[k]
    const d = arr[0] - arr[1]
    return drHas[k]
      ? makeChip(d, (d / arr[1]) * 100)
      : { txt: noCloses, style: { ...CHIP_BASE, background: 'rgba(138,147,163,.14)', color: 'var(--mut)' } as CSS }
  }
  const drLast = (k: DriverKey, dec: number) => (drHas[k] ? D[k][0].toFixed(dec) : '—')
  const kL = drK('lng')
  const kB = drK('brent')
  const kF = drK('fx')
  // Live correlations are the exporter's (trailing 90 days); a sample value only stands in for sample data.
  const drCorr = (k: DriverKey, i: number): number | null => (dvLive ? driversLive.corr[k] : drDefs[i].corr)
  const drPanel = drDefs.map((dd, i) => {
    const arr = D[dd.key]
    const c = drK(dd.key)
    const s30: number[] = []
    for (let d2 = 29; d2 >= 0; d2--) s30.push(arr[d2])
    const mn = Math.min(...s30)
    const mx = Math.max(...s30)
    const spark = drHas[dd.key]
      ? s30.map((val, j) => ((j / 29) * 64).toFixed(1) + ',' + (15.5 - ((val - mn) / (mx - mn || 1)) * 13).toFixed(1)).join(' ')
      : ''
    const corr = drCorr(dd.key, i)
    return {
      key: dd.key,
      name: L === 'ja' ? dd.ja : dd.en,
      sub: dd.src,
      unit: dd.unit,
      last: drLast(dd.key, dd.dec),
      color: dd.color,
      chip: c.txt,
      chipS: { ...c.style, marginTop: 0, padding: '2px 8px' } as CSS,
      dotS: { width: 8, height: 8, borderRadius: 999, background: dd.color, flexShrink: 0 } as CSS,
      spark,
      corr: corr != null ? corr.toFixed(2) : '—',
      corrBar: { display: 'block', width: Math.max(0, corr ?? 0) * 100 + '%', height: '100%', borderRadius: 3, background: dd.color } as CSS,
    }
  })

  // ---- caption "as of" dates (data-truth) ----
  // Live captions show the real snapshot dates (ISO, matching the fixtures'
  // format); while a snapshot is still loading, its fixture date renders.
  let wsToday = '2026-07-02'
  if (useLive) {
    let latest = ''
    for (const a of liveSel) {
      const d = (live.areas[a.key].dDt[0] ?? '').slice(0, 10)
      if (d > latest) latest = d
    }
    if (latest) wsToday = latest
  }
  const tlDate = tielineLive.ready && tielineLive.date ? tielineLive.date.slice(0, 10) : null
  const drDate = (daysAgo: number) => (dvLive && driversLive.dates[daysAgo] ? fmtDate(driversLive.dates[daysAgo]) : dateLabel(daysAgo))
  const icDate = tlDate ?? '2026-07-01'
  const areaDate = areaDayLive.ready && areaDayLive.date ? areaDayLive.date : icDate

  return {
    heatDate: wsToday,
    balDate: balLive.ready && balLive.date ? balLive.date : '2026-07-01',
    icDate,
    areaDate,
    drCloseDate: driversLive.ready && driversLive.end ? driversLive.end.slice(0, 10) : '2026-07-01',
    icAtN: icAtLimit.length,
    icLimN: icLimited.length,
    icAtChip:
      icAtSlots > 0
        ? L === 'ja' ? `上限到達 計${icAtSlots}コマ` : `${icAtSlots} slot${icAtSlots === 1 ? '' : 's'} at the limit in total`
        : L === 'ja' ? '上限到達なし' : 'no line reached its limit',
    icTopPct: icTop ? Math.round(icTop.st.peak!.share * 100) : 0,
    icTopLabel: icTop ? `${icTop.n1} · ${icTop.route}` : '—',
    icTopChip: icTop ? `${L === 'ja' ? 'ピーク' : 'peak'} ${icTop.peakAt} · ${icTop.reserved} / ${icTop.limit} MW` : '—',
    icSpread: pxHi && pxLo ? '¥' + (px[pxHi] - px[pxLo]).toFixed(2) : '—',
    icSpreadSub: pxHi && pxLo ? `${icAreaName(pxHi)} vs ${icAreaName(pxLo)} · ${L === 'ja' ? '日平均' : 'daily average'} ${areaDate}` : '—',
    icResAvg: fmtMW(icResAvg),
    icLimAvg: fmtMW(icLimAvg),
    icResPct: icLimAvg > 0 ? Math.round((icResAvg / icLimAvg) * 100) : 0,
    icRows,
    icMap,
    icNodes,
    icCombN: icCombined.length,
    icCombPeak: Math.round(icCombPeak * 100),
    icChipN: { ...CHIP_BASE, background: 'rgba(138,147,163,.14)', color: 'var(--mut)' } as CSS,
    icWarnChip: { ...CHIP_BASE, background: icAtSlots > 0 ? 'var(--dnBg)' : 'rgba(138,147,163,.14)', color: icAtSlots > 0 ? 'var(--dn)' : 'var(--mut)' } as CSS,
    dr30S: segBase(drRange === '30D'),
    dr90S: segBase(drRange === '90D'),
    dr1yS: segBase(drRange === '1Y'),
    drSpotPts: dPts(rSpot),
    drLngPts: drHas.lng ? dPts(rDr.lng) : '',
    drBrentPts: drHas.brent ? dPts(rDr.brent) : '',
    drFxPts: drHas.fx ? dPts(rDr.fx) : '',
    drLngOp: drShown('lng') ? 1 : 0,
    drBrentOp: drShown('brent') ? 1 : 0,
    drFxOp: drShown('fx') ? 1 : 0,
    drLngLegS: drLeg(drShown('lng')),
    drBrentLegS: drLeg(drShown('brent')),
    drFxLegS: drLeg(drShown('fx')),
    drG1: gVal(69),
    drG2: gVal(138),
    drG3: gVal(207),
    drG4: gVal(276),
    dr100y: Math.round(y100 * 10) / 10,
    dr100op: y100 >= 14 && y100 <= 290 ? 0.8 : 0,
    drX0: drDate(drN - 1),
    drX1: drDate(Math.floor(drN / 2)),
    drX2: drDate(0),
    drLngV: drLast('lng', 2),
    drLngC: kL.txt,
    drBrentV: drLast('brent', 2),
    drBrentC: kB.txt,
    drBrentCS: kB.style,
    drFxV: drLast('fx', 2),
    drFxC: kF.txt,
    drFxCS: kF.style,
    drPanel,
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
    kAvgSub: (useLive ? liveSel.length : selAreas.length || 9) + ' areas · ' + range + ' · vs prior ' + range,
    kAvgD: kAvgC.txt,
    kPeak: pk.v.toFixed(2),
    kPeakSub: (pk.area ? (L === 'ja' ? pk.area.ja : pk.area.en) : '') + ' · ' + (pk.dt ? fmtDate(pk.dt) : dateLabel(pk.d)) + ' · vs prior period',
    kPeakD: kPeakC.txt,
    kPeakDS: kPeakC.style,
    kDem: demV.toLocaleString('en-US'),
    kDemSub: 'sum of selected-area peaks · 17:30 slot',
    kDemD: kDemC.txt,
    kDemDS: kDemC.style,
    showHeat: SHOW_HEATMAP,
    heatRows,
    sections,
    hiddenNote,
    // The plotted window can differ from the range chip: `Native` is capped by
    // the export window, `Weekly`/`Monthly` are floored so a line can be drawn.
    rangeClampNote: rangeClampNote(gran, range),
    balRows,
    balProcTot: balLive.ready ? (bDay?.contracted_mw != null ? fmtInt(bDay.contracted_mw) : '—') : '9,321',
    balAvgPrice: balLive.ready ? (bDay?.price != null ? bDay.price.toFixed(2) : '—') : '4.87',
    balPriceChip: balPriceChip?.txt ?? null,
    balProcChip,
    balShort: balLive.ready ? (wr ? String(wr.short) : '—') : '3',
    balSlots: wr ? wr.slots : 48,
    balShortSub,
    balShortChip,
  }
}

export type MarketView = ReturnType<typeof buildMarketView>
