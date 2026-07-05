// Live-data adapter for the Market Data wholesale view.
//
// Fetches per-area wholesale price snapshots (produced by `repower export-web`)
// at the selected granularity and reshapes them into the arrays the existing
// chart geometry already consumes. Fixtures remain the loading/fallback state,
// so the render code in MarketData.tsx is unchanged.

import { useEffect, useState } from 'react'
import { getSnapshot } from '../lib/data'
import type { WholesaleSnapshot, WholesaleStats } from '../lib/types'

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
  peakMW: number | null // stats.peak_demand_mw
  avgPrice: number | null // stats.avg_price
  latest: number | null // latest period price_avg
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
      keys.map(async (key) => {
        const [snap, daily, stats] = await Promise.all([
          getSnapshot<WholesaleSnapshot>(`wholesale/${key}/${gran}.json`),
          gran === 'Daily'
            ? null
            : getSnapshot<WholesaleSnapshot>(`wholesale/${key}/Daily.json`).catch(() => null),
          getSnapshot<WholesaleStats>(`wholesale_stats/${key}.json`).catch(() => null),
        ])
        const price = snap.price
        const dsrc = (daily ?? snap).price
        const la: LiveArea = {
          key,
          avg: rev(price.map((p) => nn(p.price_avg))),
          max: rev(price.map((p) => nn(p.price_max ?? p.price_avg))),
          min: rev(price.map((p) => nn(p.price_min ?? p.price_avg))),
          dt: rev(price.map((p) => p.datetime)),
          dAvg: rev(dsrc.map((p) => nn(p.price_avg))),
          dMax: rev(dsrc.map((p) => nn(p.price_max ?? p.price_avg))),
          peakMW: stats?.peak_demand_mw ?? null,
          avgPrice: stats?.avg_price ?? null,
          latest: price.length ? nn(price[price.length - 1].price_avg) : null,
        }
        return [key, la] as const
      }),
    )
      .then((entries) => {
        if (alive) setState({ areas: Object.fromEntries(entries), loading: false, ready: true })
      })
      .catch(() => {
        if (alive) setState((s) => ({ ...s, loading: false }))
      })
    return () => {
      alive = false
    }
  }, [keysCsv, gran])

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

export interface BalancingLive {
  ready: boolean
  rows: Record<string, BalRow>
  procTot: number
  avgPrice: number | null
}

// Frontend balProducts order ↔ exporter product codes.
export const BAL_CODES = ['1-0', '2-1', '2-2', '3-1', '3-2']
const BAL_AREAS = ['hokkaido', 'tohoku', 'tepco', 'chubu', 'hokuriku', 'kansai', 'chugoku', 'shikoku', 'kyushu']

/** National balancing KPIs per product: summed procured/required across the 9 areas,
 * mean clearing price. (需給調整市場 is procured nationwide.) */
export function useBalancingLive(): BalancingLive {
  const [state, setState] = useState<BalancingLive>({ ready: false, rows: {}, procTot: 0, avgPrice: null })
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
        let procTot = 0
        const prices: number[] = []
        for (const code of BAL_CODES) {
          let proc = 0
          let off = 0
          const ps: number[] = []
          for (const s of all) {
            if (!s || s.product_code !== code) continue
            if (s.avg_contracted_mw != null) proc += s.avg_contracted_mw
            if (s.avg_bid_volume_mw != null) off += s.avg_bid_volume_mw
            if (s.avg_price != null) ps.push(s.avg_price)
          }
          const price = ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : null
          rows[code] = { price, proc, off, ach: off > 0 ? (proc / off) * 100 : null }
          procTot += proc
          if (price != null) prices.push(price)
        }
        const avgPrice = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : null
        setState({ ready: true, rows, procTot, avgPrice })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
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
}

/** Latest-day 48-slot reserved/TTC utilisation + TTC per mapped interconnector line.
 * Lines with no clean mapping (combined-zone pairs) are absent → caller falls back
 * to the fixture. Utilisation is reserved/TTC (real), typically low (uncongested). */
export function useTielineLive(market = 'DAM'): TielineLive {
  const [state, setState] = useState<TielineLive>({ ready: false, byKey: {} })
  useEffect(() => {
    let alive = true
    getSnapshot<TielineSnapshot>(`tieline/${market}.json`)
      .then((snap) => {
        if (!alive) return
        const byKey: TielineLive['byKey'] = {}
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
        setState({ ready: true, byKey })
      })
      .catch(() => {
        if (alive) setState({ ready: false, byKey: {} })
      })
    return () => {
      alive = false
    }
  }, [market])
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
  const [snap, setSnap] = useState<DriversSnapshot | null>(null)
  useEffect(() => {
    let alive = true
    getSnapshot<DriversSnapshot>('drivers.json')
      .then((d) => alive && setSnap(d))
      .catch(() => alive && setSnap(null))
    return () => {
      alive = false
    }
  }, [])
  if (!snap || !snap.dates || snap.dates.length === 0) {
    return { ready: false, spot: [], jkm: [], ncl: [], fx: [], corr: { jkm: null, ncl: null, fx: null } }
  }
  return {
    ready: true,
    spot: toNewestFirst(snap.spot),
    jkm: toNewestFirst(snap.jkm),
    ncl: toNewestFirst(snap.ncl),
    fx: toNewestFirst(snap.fx),
    corr: snap.corr || { jkm: null, ncl: null, fx: null },
  }
}

// Trailing periods to plot for a given (gran, range) window.
const PERIODS: Record<Gran, Record<Range, number>> = {
  Native: { '7D': 7 * 48, '30D': 30 * 48, '60D': 60 * 48, '1Y': 365 * 48 },
  Daily: { '7D': 7, '30D': 30, '60D': 60, '1Y': 365 },
  Weekly: { '7D': 2, '30D': 5, '60D': 9, '1Y': 53 },
  Monthly: { '7D': 1, '30D': 2, '60D': 3, '1Y': 12 },
}
const MAX_POINTS = 90

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function fmtDate(iso: string): string {
  const p = iso.slice(0, 10).split('-')
  if (p.length < 3) return iso
  return MONTHS[Number(p[1]) - 1] + ' ' + Number(p[2])
}

export interface Windowed {
  avg: number[] // oldest -> newest (plot order)
  max: number[]
  min: number[]
  labels: [string, string, string] // start, mid, end
}

/**
 * Slice the newest K periods for (gran,range), downsample to <= MAX_POINTS, and
 * return in plot order (oldest -> newest). Rows with a non-finite avg are dropped
 * (real data has gaps; fixtures don't), keeping avg/max/min/dt aligned.
 */
export function windowLive(la: LiveArea, gran: Gran, range: Range): Windowed {
  const want = Math.min(PERIODS[gran][range], la.avg.length)
  const step = Math.max(1, Math.ceil(want / MAX_POINTS))
  const order: number[] = []
  for (let i = want - 1; i >= 0; i -= step) order.push(i) // oldest -> newest (arrays are newest-first)
  const keep = order.filter((i) => Number.isFinite(la.avg[i]))
  const avg = keep.map((i) => la.avg[i])
  const max = keep.map((i) => (Number.isFinite(la.max[i]) ? la.max[i] : la.avg[i]))
  const min = keep.map((i) => (Number.isFinite(la.min[i]) ? la.min[i] : la.avg[i]))
  const dts = keep.map((i) => la.dt[i])
  const n = dts.length
  const labels: [string, string, string] = [
    n ? fmtDate(dts[0]) : '',
    n ? fmtDate(dts[Math.floor((n - 1) / 2)]) : '',
    n ? fmtDate(dts[n - 1]) : '',
  ]
  return { avg, max, min, labels }
}
