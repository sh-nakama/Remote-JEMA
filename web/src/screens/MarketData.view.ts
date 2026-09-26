// Market Data view model: everything the screen displays, computed from its controls and live data.
// Split out of MarketData.tsx verbatim; the screen memoises buildMarketView on the same inputs.
import type { Lang } from '../lib/app'
import { CHIP_BASE, makeChip, segBase, filterChipBase, slotLabel, fmtDate } from '../lib/chartkit'
import { gapSegments, segPoints, bandPoints, PLOT_X0, PLOT_W } from '../lib/chart'
import type { CSS } from '../lib/style'
import { areas, areaDefs, balProducts, icDefs, icUtil, drv, drDefs, gaussian as G } from './MarketData.data'
import {
  useWholesaleLive,
  windowLive,
  windowSupply,
  useDriversLive,
  useBalancingLive,
  BAL_CODES,
  useTielineLive,
  DAY_MS,
  effectiveRangeDays,
  rangeClampNote,
  latestT,
  latestPriceT,
  latestSupplyT,
} from './MarketData.live'

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
  const MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return MO[d.getMonth()] + ' ' + d.getDate()
}

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
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
  drOn: { jkm: boolean; ncl: boolean; fx: boolean }
  L: Lang
  dark: boolean
  live: ReturnType<typeof useWholesaleLive>
  driversLive: ReturnType<typeof useDriversLive>
  balLive: ReturnType<typeof useBalancingLive>
  tielineLive: ReturnType<typeof useTielineLive>
}

export function buildMarketView({ view, range, gran, sel, closed, expanded, zoom, drRange, drOn, L, dark, live, driversLive, balLive, tielineLive }: MarketViewInput) {
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
    let mix1: string[]
    let mix2: string[]
    let mix3: string[]
    let mix4: string[]
    let demandLine: string[]
    let expMix1: string[] = []
    let expMix2: string[] = []
    let expMix3: string[] = []
    let expMix4: string[] = []
    let expDemand: string[] = []
    let peakMWStr: string
    let mixMeta: string
    // Raw windowed mix arrays + geometry for the hover layer.
    let supN = 0
    let supYmax = 1
    let supDtA: string[] = []
    let supTA: number[] = []
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
      const nS = supW.demand.length
      const Xs = (i: number) => (useTime ? xOfT(supW.t[i]) : PLOT_X0 + (i / Math.max(1, nS - 1)) * PLOT_W)
      const my = (val: number) => 152 - (val / supW.ymax) * 140
      const myE = (val: number) => EXP_H - 12 - (val / supW.ymax) * (EXP_H - 28)
      const sSegs = (useTime ? gapSegments(supW.t) : nS ? ([[0, nS - 1]] as [number, number][]) : []).filter(
        ([s0, s1]) => s1 > s0,
      )
      const bands = (y: (val: number) => number) => ({
        b1: sSegs.map((sg) => bandPoints(sg, Xs, (i) => y(c1[i]), () => y(0))),
        b2: sSegs.map((sg) => bandPoints(sg, Xs, (i) => y(c2[i]), (i) => y(c1[i]))),
        b3: sSegs.map((sg) => bandPoints(sg, Xs, (i) => y(c3[i]), (i) => y(c2[i]))),
        b4: sSegs.map((sg) => bandPoints(sg, Xs, (i) => y(c4[i]), (i) => y(c3[i]))),
        dem: sSegs.map((sg) => segPoints(sg, Xs, (i) => y(supW.demand[i]))),
      })
      const std = bands(my)
      mix1 = std.b1
      mix2 = std.b2
      mix3 = std.b3
      mix4 = std.b4
      demandLine = std.dem
      const exp = bands(myE)
      expMix1 = exp.b1
      expMix2 = exp.b2
      expMix3 = exp.b3
      expMix4 = exp.b4
      expDemand = exp.dem
      peakMWStr = Math.round(Math.max(1, ...supW.demand)).toLocaleString('en-US')
      mixMeta = range + ' · ' + gran + ' · grouped MW'
      supN = nS
      supYmax = supW.ymax
      supDtA = supW.dt
      supTA = supW.t
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
      const myE = (val: number) => EXP_H - 12 - (val / ymax) * (EXP_H - 28)
      const demLine = dem.map((val) => val * 1.018)
      const fx = (i: number) => X(i, 48)
      const seg: [number, number] = [0, 47]
      const bands = (y: (val: number) => number) => ({
        b1: [bandPoints(seg, fx, (i) => y(c1[i]), () => y(0))],
        b2: [bandPoints(seg, fx, (i) => y(c2[i]), (i) => y(c1[i]))],
        b3: [bandPoints(seg, fx, (i) => y(c3[i]), (i) => y(c2[i]))],
        dem: [segPoints(seg, fx, (i) => y(demLine[i]))],
      })
      const std = bands(my)
      mix1 = std.b1
      mix2 = std.b2
      mix3 = std.b3
      mix4 = []
      demandLine = std.dem
      const exp = bands(myE)
      expMix1 = exp.b1
      expMix2 = exp.b2
      expMix3 = exp.b3
      expMix4 = []
      expDemand = exp.dem
      peakMWStr = P.toLocaleString('en-US')
      mixMeta = 'today · 14 fuels grouped · MW'
      // hover arrays for the synthetic "today" mix (half-hourly, oldest→newest)
      supN = 48
      supYmax = ymax
      supDtA = Array.from({ length: 48 }, (_, i) => String(Math.floor(i / 2)).padStart(2, '0') + ':' + (i % 2 === 0 ? '00' : '30'))
      supTA = Array.from({ length: 48 }, () => NaN)
      supDemandA = demLine
      supBaseA = c1
      supThermA = c2.map((val, i) => Math.max(0, val - c1[i]))
      supSolarA = c3.map((val, i) => Math.max(0, val - c2[i]))
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
      sub: live.ready && !la ? (L === 'ja' ? '· データなし（サンプル表示）' : '· no data — sample shown') : '',
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
      mix1,
      mix2,
      mix3,
      mix4,
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
      supBaseA,
      supThermA,
      supSolarA,
      supOtherA,
      // combined (expanded) chart
      expH: EXP_H,
      expMix1,
      expMix2,
      expMix3,
      expMix4,
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
    for (const a of liveSel) {
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
    balProcTot: balLive.ready ? Math.round(balLive.procTot).toLocaleString('en-US') : '9,321',
    balAvgPrice: balLive.ready && balLive.avgPrice != null ? balLive.avgPrice.toFixed(2) : '4.87',
    balD1S: { ...CHIP_BASE, background: 'var(--upBg)', color: 'var(--up)' } as CSS,
    balD2S: { ...CHIP_BASE, background: 'var(--upBg)', color: 'var(--up)' } as CSS,
  }
}

export type MarketView = ReturnType<typeof buildMarketView>
