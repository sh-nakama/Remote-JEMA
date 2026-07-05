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
