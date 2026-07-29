// Live-data adapter for the Market Data wholesale view.
//
// Fetches per-area wholesale price snapshots (produced by `repower export-web`)
// at the selected granularity and reshapes them into the arrays the existing
// chart geometry already consumes. Fixtures remain the loading/fallback state,
// so the render code in MarketData.tsx is unchanged.

import { useEffect, useState } from 'react'
import { fmtDate } from '../lib/chartkit'
import { getSnapshot, useDataNonce } from '../lib/data'
import type { SupplyRecord, WholesaleSnapshot, WholesaleStats } from '../lib/types'

// fmtDate used to live here; it moved to the shared chartkit module. Re-exported
// so existing importers keep working.
export { fmtDate }

export type Gran = 'Native' | 'Daily' | 'Weekly' | 'Monthly'
export type Range = '7D' | '30D' | '60D' | '1Y'

/** One area's live series, all price arrays in NEWEST-FIRST order (index 0 = latest period). */
export interface LiveArea {
  key: string
  avg: number[] // price_avg at the requested gran
  max: number[]
  min: number[]
  dt: string[] // datetimes aligned to avg/max/min
  dAvg: number[] // Daily price_avg (gran-independent) — stable KPIs
  dMax: number[] // Daily price_max
  dDt: string[] // datetimes aligned to dAvg/dMax (for KPI date labels)
  peakMW: number | null // stats.peak_demand_mw
  avgPrice: number | null // stats.avg_price
  latest: number | null // latest period price_avg
  // grouped generation mix at the requested gran, newest-first (MW)
  supBase: number[] // nuclear + hydro + geothermal + biomass
  supTherm: number[] // coal + lng + oil + thermal_other
  supSolar: number[] // solar + wind
  supDemand: number[] // area demand
  supDt: string[] // datetimes aligned to the supply arrays
}

export interface LiveState {
  areas: Record<string, LiveArea>
  loading: boolean
  ready: boolean
}

function rev<T>(a: T[]): T[] {
  return a.slice().reverse()
}
const nn = (x: number | null | undefined): number => (x == null ? NaN : x)

/**
 * Fetch the selected areas' wholesale snapshots at `gran` (plus Daily for KPIs
 * and per-area stats). Keyed by a sorted CSV of the selection so re-selecting an
 * already-loaded set is a no-op; per-path fetches are cached in `getSnapshot`.
 */
export function useWholesaleLive(selectedKeys: string[], gran: Gran): LiveState {
  const keysCsv = [...selectedKeys].sort().join(',')
  const nonce = useDataNonce()
  const [state, setState] = useState<LiveState>({ areas: {}, loading: false, ready: false })

  useEffect(() => {
    const keys = keysCsv ? keysCsv.split(',') : []
    if (keys.length === 0) {
      setState({ areas: {}, loading: false, ready: true })
      return
    }
    let alive = true
    setState((s) => ({ ...s, loading: true }))
    Promise.all(
      keys.map(async (key): Promise<readonly [string, LiveArea] | null> => {
        try {
          const [snap, daily, stats] = await Promise.all([
            getSnapshot<WholesaleSnapshot>(`wholesale/${key}/${gran}.json`),
            gran === 'Daily'
              ? null
              : getSnapshot<WholesaleSnapshot>(`wholesale/${key}/Daily.json`).catch(() => null),
            getSnapshot<WholesaleStats>(`wholesale_stats/${key}.json`).catch(() => null),
          ])
          const price = snap.price
          const dsrc = (daily ?? snap).price
          const sup = snap.supply
          // Individual fuel columns fall back to 0 so one missing fuel doesn't void
          // a row, but `area_demand_mw` is read with `nn` below: exports pad the
          // tail with all-null rows, and coercing those to 0 drew a demand line
          // flat along the axis instead of ending the series.
          const g = (r: SupplyRecord, k: keyof SupplyRecord): number => {
            const v = r[k]
            return typeof v === 'number' && Number.isFinite(v) ? v : 0
          }
          const la: LiveArea = {
            key,
            avg: rev(price.map((p) => nn(p.price_avg))),
            max: rev(price.map((p) => nn(p.price_max ?? p.price_avg))),
            min: rev(price.map((p) => nn(p.price_min ?? p.price_avg))),
            dt: rev(price.map((p) => p.datetime)),
            dAvg: rev(dsrc.map((p) => nn(p.price_avg))),
            dMax: rev(dsrc.map((p) => nn(p.price_max ?? p.price_avg))),
            dDt: rev(dsrc.map((p) => p.datetime)),
            peakMW: stats?.peak_demand_mw ?? null,
            avgPrice: stats?.avg_price ?? null,
            latest: price.length ? nn(price[price.length - 1].price_avg) : null,
            supBase: rev(sup.map((r) => g(r, 'nuclear') + g(r, 'hydro') + g(r, 'geothermal') + g(r, 'biomass'))),
            supTherm: rev(sup.map((r) => g(r, 'coal') + g(r, 'lng') + g(r, 'oil') + g(r, 'thermal_other'))),
            supSolar: rev(sup.map((r) => g(r, 'solar_actual') + g(r, 'wind_actual'))),
            supDemand: rev(sup.map((r) => nn(r.area_demand_mw))),
            supDt: rev(sup.map((r) => r.datetime)),
          }
          return [key, la] as const
        } catch {
          // One area's snapshot failing (missing file or invalid JSON — e.g. a
          // stale export with bare `NaN` tokens) must NOT reject the whole batch
          // and blank every area to fixtures. Skip it; that area alone falls back.
          return null
        }
      }),
    )
      .then((entries) => {
        if (!alive) return
        const ok = entries.filter((e): e is readonly [string, LiveArea] => e !== null)
        setState({ areas: Object.fromEntries(ok), loading: false, ready: true })
      })
      .catch(() => {
        if (alive) setState((s) => ({ ...s, loading: false, ready: true }))
      })
    return () => {
      alive = false
    }
  }, [keysCsv, gran, nonce])

  return state
}

// ── Balancing (需給調整市場 / EPRX) ─────────────────────────────────────────

export interface BalancingStats {
  schema: number
  product_code: string
  product: string
  area: string
  window_days: number
  start: string
  end: string
  avg_demand_mw: number | null
  avg_contracted_mw: number | null
  avg_bid_volume_mw: number | null
  avg_unprocured_mw: number | null
  avg_price: number | null
  avg_max_price: number | null
}

export interface BalRow {
  price: number | null
  proc: number
  off: number
  ach: number | null
}

/** One product's figures for a single TSO area (drill-down detail). */
export interface BalAreaRow extends BalRow {
  area: string
}

export interface BalancingLive {
  ready: boolean
  rows: Record<string, BalRow>
  /** Per-product, per-area breakdown (procured-desc) for the row drill-down. */
  areaRows: Record<string, BalAreaRow[]>
  procTot: number
  avgPrice: number | null
  /** Latest stats-window end date (ISO) across products/areas — caption "as of". */
  end: string | null
}

// Frontend balProducts order ↔ exporter product codes.
export const BAL_CODES = ['1-0', '2-1', '2-2', '3-1', '3-2']
const BAL_AREAS = ['hokkaido', 'tohoku', 'tepco', 'chubu', 'hokuriku', 'kansai', 'chugoku', 'shikoku', 'kyushu']

/** National balancing KPIs per product: summed procured/required across the 9 areas,
 * mean clearing price. (需給調整市場 is procured nationwide.) */
export function useBalancingLive(): BalancingLive {
  const nonce = useDataNonce()
  const [state, setState] = useState<BalancingLive>({ ready: false, rows: {}, areaRows: {}, procTot: 0, avgPrice: null, end: null })
  useEffect(() => {
    let alive = true
    const jobs: Promise<BalancingStats | null>[] = []
    for (const code of BAL_CODES)
      for (const area of BAL_AREAS)
        jobs.push(getSnapshot<BalancingStats>(`balancing_stats/${code}/${area}.json`).catch(() => null))
    Promise.all(jobs)
      .then((all) => {
        if (!alive) return
        const rows: Record<string, BalRow> = {}
        const areaRows: Record<string, BalAreaRow[]> = {}
        let procTot = 0
        let end: string | null = null
        for (const s of all) if (s?.end && (!end || s.end > end)) end = s.end
        for (const code of BAL_CODES) {
          let proc = 0
          let off = 0
          const ps: number[] = []
          const ar: BalAreaRow[] = []
          for (const s of all) {
            if (!s || s.product_code !== code) continue
            const aProc = s.avg_contracted_mw ?? 0
            const aOff = s.avg_bid_volume_mw ?? 0
            if (s.avg_contracted_mw != null) proc += s.avg_contracted_mw
            if (s.avg_bid_volume_mw != null) off += s.avg_bid_volume_mw
            if (s.avg_price != null) ps.push(s.avg_price)
            if (aProc > 0 || aOff > 0 || s.avg_price != null)
              ar.push({ area: s.area, price: s.avg_price, proc: aProc, off: aOff, ach: aOff > 0 ? (aProc / aOff) * 100 : null })
          }
          const price = ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : null
          rows[code] = { price, proc, off, ach: off > 0 ? (proc / off) * 100 : null }
          areaRows[code] = ar.sort((a, b) => b.proc - a.proc)
          procTot += proc
        }
        // Volume-weighted by procured (contracted) MW across products — matches the
        // "Weighted avg ΔkW price / 加重平均" label (a plain mean over products would
        // over-weight thinly-procured products).
        let wNum = 0
        let wDen = 0
        for (const code of BAL_CODES) {
          const r = rows[code]
          if (r.price != null && r.proc > 0) {
            wNum += r.price * r.proc
            wDen += r.proc
          }
        }
        const avgPrice = wDen > 0 ? wNum / wDen : null
        setState({ ready: true, rows, areaRows, procTot, avgPrice, end })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [nonce])
  return state
}

// ── Tieline / interconnectors (連系線) ───────────────────────────────────────

export interface TielineLineSnap {
  key: string | null
  pair: string
  date: string
  ttc: number | null
  util: (number | null)[]
  util_now: number | null
}
export interface TielineSnapshot {
  schema: number
  market: string
  slots: string[]
  lines: TielineLineSnap[]
}
export interface TielineLive {
  ready: boolean
  byKey: Record<string, { util: number[]; ttc: number | null; utilNow: number | null }>
  /** Snapshot day (ISO, latest across lines) — caption "as of". */
  date: string | null
}

/** Latest-day 48-slot reserved/TTC utilisation + TTC per mapped interconnector line.
 * Lines with no clean mapping (combined-zone pairs) are absent → caller falls back
 * to the fixture. Utilisation is reserved/TTC (real), typically low (uncongested). */
export function useTielineLive(market = 'DAM'): TielineLive {
  const nonce = useDataNonce()
  const [state, setState] = useState<TielineLive>({ ready: false, byKey: {}, date: null })
  useEffect(() => {
    let alive = true
    getSnapshot<TielineSnapshot>(`tieline/${market}.json`)
      .then((snap) => {
        if (!alive) return
        const byKey: TielineLive['byKey'] = {}
        let date: string | null = null
        for (const ln of snap.lines) if (ln.date && (!date || ln.date > date)) date = ln.date
        for (const ln of snap.lines) {
          // Skip unmapped pairs and lines with no forward TTC (capacity is on the
          // reverse leg) — those fall back to the fixture.
          if (!ln.key || !ln.ttc || ln.ttc <= 0) continue
          byKey[ln.key] = {
            util: ln.util.map((x) => (typeof x === 'number' && Number.isFinite(x) ? x : 0)),
            ttc: ln.ttc,
            utilNow: ln.util_now,
          }
        }
        setState({ ready: true, byKey, date })
      })
      .catch(() => {
        if (alive) setState({ ready: false, byKey: {}, date: null })
      })
    return () => {
      alive = false
    }
  }, [market, nonce])
  return state
}

// ── Drivers (fuels / FX) ────────────────────────────────────────────────────

export interface DriversSnapshot {
  schema: number
  start: string | null
  end: string | null
  dates: string[]
  spot: (number | null)[]
  jkm: (number | null)[]
  ncl: (number | null)[]
  fx: (number | null)[]
  corr: { jkm: number | null; ncl: number | null; fx: number | null }
  units: Record<string, string>
  sources: Record<string, string>
}

export interface DriversLive {
  ready: boolean
  spot: number[]
  jkm: number[]
  ncl: number[]
  fx: number[]
  corr: { jkm: number | null; ncl: number | null; fx: number | null }
  /** Last close date of the series window (ISO) — caption "as of". */
  end: string | null
}

// chronological (oldest→newest, possibly with null gaps) → gap-free newest-first
function toNewestFirst(a: (number | null)[]): number[] {
  const filled: number[] = []
  let last = NaN
  for (const v of a) {
    if (typeof v === 'number' && Number.isFinite(v)) last = v
    filled.push(last)
  }
  const firstFinite = filled.find((x) => Number.isFinite(x))
  return filled.map((x) => (Number.isFinite(x) ? x : firstFinite ?? 0)).reverse()
}

export function useDriversLive(): DriversLive {
  const nonce = useDataNonce()
  const [snap, setSnap] = useState<DriversSnapshot | null>(null)
  useEffect(() => {
    let alive = true
    getSnapshot<DriversSnapshot>('drivers.json')
      .then((d) => alive && setSnap(d))
      .catch(() => alive && setSnap(null))
    return () => {
      alive = false
    }
  }, [nonce])
  if (!snap || !snap.dates || snap.dates.length === 0) {
    return { ready: false, spot: [], jkm: [], ncl: [], fx: [], corr: { jkm: null, ncl: null, fx: null }, end: null }
  }
  return {
    ready: true,
    spot: toNewestFirst(snap.spot),
    jkm: toNewestFirst(snap.jkm),
    ncl: toNewestFirst(snap.ncl),
    fx: toNewestFirst(snap.fx),
    corr: snap.corr || { jkm: null, ncl: null, fx: null },
    end: snap.end ?? snap.dates[snap.dates.length - 1] ?? null,
  }
}

// Calendar length of each range chip. This — not a record count — defines the
// plotted window (see `windowLive`).
export const RANGE_DAYS: Record<Range, number> = { '7D': 7, '30D': 30, '60D': 60, '1Y': 365 }
export const DAY_MS = 86_400_000

/** Native (30-min) snapshots are exported for a trailing window only, so a `1Y ·
 *  Native` request can never be honoured — the charts clamp to this and say so.
 *  Mirrors `LEVEL_WINDOW_DAYS["Native"]` in `dashboard/export_web.py`. */
export const NATIVE_EXPORT_DAYS = 90

/** Shortest window that yields enough aggregated buckets to draw a line at each
 *  granularity (~4 buckets). Without this, `Monthly · 7D` selects at most one
 *  monthly point and every chart renders blank. */
const GRAN_MIN_DAYS: Record<Gran, number> = { Native: 0, Daily: 0, Weekly: 28, Monthly: 120 }

/** Calendar days actually plottable for (gran, range): `RANGE_DAYS`, capped by the
 *  Native export window and floored by the granularity's minimum useful span. */
export function effectiveRangeDays(gran: Gran, range: Range): number {
  const want = RANGE_DAYS[range]
  if (gran === 'Native') return Math.min(want, NATIVE_EXPORT_DAYS)
  return Math.max(want, GRAN_MIN_DAYS[gran])
}

/** Bilingual note explaining why the plotted window differs from the range chip,
 *  or `''` when the request was honoured exactly. */
export function rangeClampNote(gran: Gran, range: Range): string {
  const want = RANGE_DAYS[range]
  const got = effectiveRangeDays(gran, range)
  if (got === want) return ''
  if (got < want) return `Native limited to last ${got} days · 30分値は直近${got}日`
  return `${gran} widened to ${got} days · ${gran}表示は${got}日に拡大`
}

/** Parse an ISO datetime ("2026-07-11" / "2026-07-11T22:30:00") to epoch ms (UTC).
 *  Returns NaN for the fixtures' non-ISO day labels ("Jun 12"), which callers use
 *  to fall back to index spacing. */
export function parseISO(iso: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(iso)
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], m[4] ? +m[4] : 0, m[5] ? +m[5] : 0) : NaN
}

/** Newest datetime at which `values` actually has a number. Arrays are
 *  newest-first, so this walks forward to the first populated row. Exports pad
 *  both series with all-null rows, so the raw index 0 can be days ahead of the
 *  real data and would otherwise anchor the chart window on nothing. */
function newestWithData(dts: string[], values: number[]): number {
  for (let i = 0; i < dts.length; i++) {
    if (!Number.isFinite(values[i])) continue
    const t = parseISO(dts[i])
    if (Number.isFinite(t)) return t
  }
  return NaN
}

/** Newest datetime carrying data across an area's price and supply series, or
 *  NaN when neither has any. */
export function latestT(la: LiveArea): number {
  const p = newestWithData(la.dt, la.avg)
  const s = newestWithData(la.supDt, la.supDemand)
  if (!Number.isFinite(p)) return s
  if (!Number.isFinite(s)) return p
  return Math.max(p, s)
}

/** Newest datetime with a price, for the staleness caption. */
export function latestPriceT(la: LiveArea): number {
  return newestWithData(la.dt, la.avg)
}

/** Newest datetime with a generation mix, for the staleness caption. */
export function latestSupplyT(la: LiveArea): number {
  return newestWithData(la.supDt, la.supDemand)
}

// Plot budget per price line. High enough that Native (30-min) renders a visibly
// denser, oscillating line than the aggregated levels instead of aliasing into a
// coarse daily-looking shape when a wide range is downsampled to a single line.
const MAX_POINTS = 720

export interface Windowed {
  avg: number[] // oldest -> newest (plot order)
  max: number[]
  min: number[]
  dt: string[] // raw ISO datetimes aligned to avg/max/min (for hover)
  t: number[] // epoch ms aligned to dt
  labels: [string, string, string] // start, mid, end
}

/** Indices (newest-first arrays) whose datetime falls inside [t0, t1], returned
 *  oldest -> newest and downsampled to <= MAX_POINTS.
 *
 *  Windowing by *time* rather than by record count is the fix for issue #22: the
 *  real series have gaps, so "the newest 336 rows" spanned ~38 days for a 7D chip
 *  and the chart drew its data as a sliver on a wildly oversized axis. */
function indicesInWindow(dts: string[], t0: number, t1: number): number[] {
  const hits: number[] = []
  // Newest-first: walk from index 0 and stop once we fall out of the window.
  for (let i = 0; i < dts.length; i++) {
    const t = parseISO(dts[i])
    if (!Number.isFinite(t)) continue
    if (t > t1) continue
    if (t < t0) break
    hits.push(i)
  }
  hits.reverse() // oldest -> newest (plot order)
  if (hits.length <= MAX_POINTS) return hits
  const step = Math.ceil(hits.length / MAX_POINTS)
  const out: number[] = []
  for (let k = 0; k < hits.length; k += step) out.push(hits[k])
  // Always keep the newest point so the line reaches the right edge of its data.
  const last = hits[hits.length - 1]
  if (out[out.length - 1] !== last) out.push(last)
  return out
}

/**
 * Slice the price series to the time window `[t0, t1]` (epoch ms), downsample to
 * <= MAX_POINTS and return in plot order (oldest -> newest). Rows with a
 * non-finite avg are dropped (real data has gaps; fixtures don't), keeping
 * avg/max/min/dt aligned.
 */
export function windowLive(la: LiveArea, t0: number, t1: number): Windowed {
  const keep = indicesInWindow(la.dt, t0, t1).filter((i) => Number.isFinite(la.avg[i]))
  const avg = keep.map((i) => la.avg[i])
  const max = keep.map((i) => (Number.isFinite(la.max[i]) ? la.max[i] : la.avg[i]))
  const min = keep.map((i) => (Number.isFinite(la.min[i]) ? la.min[i] : la.avg[i]))
  const dts = keep.map((i) => la.dt[i])
  const t = keep.map((i) => parseISO(la.dt[i]))
  const n = dts.length
  const labels: [string, string, string] = [
    n ? fmtDate(dts[0]) : '',
    n ? fmtDate(dts[Math.floor((n - 1) / 2)]) : '',
    n ? fmtDate(dts[n - 1]) : '',
  ]
  return { avg, max, min, dt: dts, t, labels }
}

export interface SupplyWindow {
  baseload: number[] // oldest -> newest
  thermal: number[]
  solar: number[]
  other: number[] // residual to demand (net imports + storage), >= 0
  demand: number[]
  dt: string[] // raw ISO datetimes aligned to the windowed arrays (for hover)
  t: number[] // epoch ms aligned to dt
  ymax: number
}

/** Window the grouped generation mix to `[t0, t1]` (epoch ms), oldest→newest, on
 * the same budget as the price line. `other` fills the gap up to demand so the 4
 * bands stack to area demand (imports/storage); 0 when domestic generation
 * already exceeds it. */
export function windowSupply(la: LiveArea, t0: number, t1: number): SupplyWindow {
  // Exports pad the series with rows whose values are all null (the TSO feed lags
  // behind the timestamp grid). Treating those as 0 drew a demand line flat along
  // the axis — i.e. "demand fell to zero" — so drop them and let the gap
  // segmentation leave honest whitespace instead.
  const order = indicesInWindow(la.supDt, t0, t1).filter((i) => Number.isFinite(la.supDemand[i]))
  const pick = (arr: number[]) => order.map((i) => (Number.isFinite(arr[i]) ? arr[i] : 0))
  const baseload = pick(la.supBase)
  const thermal = pick(la.supTherm)
  const solar = pick(la.supSolar)
  const demand = pick(la.supDemand)
  const dt = order.map((i) => la.supDt[i])
  const t = order.map((i) => parseISO(la.supDt[i]))
  const other = demand.map((d, i) => Math.max(0, d - baseload[i] - thermal[i] - solar[i]))
  let ymax = 1
  for (let i = 0; i < demand.length; i++) {
    ymax = Math.max(ymax, demand[i], baseload[i] + thermal[i] + solar[i] + other[i])
  }
  return { baseload, thermal, solar, other, demand, dt, t, ymax: ymax * 1.08 }
}
