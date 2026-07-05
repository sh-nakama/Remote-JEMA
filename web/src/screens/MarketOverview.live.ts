// Live-data adapter for the Market Overview intraday chart + spot tiles.
//
// Fetches the system-price snapshot (system.json, from `repower export-web`) and
// reshapes it into the 48-slot arrays / step paths the existing chart geometry
// consumes. Fixtures remain the loading/fallback state.

import { useEffect, useState } from 'react'
import { getSnapshot } from '../lib/data'
import { X, Y } from './MarketOverview.data'

export interface SystemSnapshot {
  schema: number
  slots: string[]
  date_today: string | null
  date_yday: string | null
  system_today: (number | null)[]
  system_yday: (number | null)[]
  system_avg7: (number | null)[]
  tokyo_today: (number | null)[]
  now: { system: number | null; tokyo: number | null; slot: string | null }
  areas_now: Record<string, number>
}

export interface SystemLive {
  ready: boolean
  today: number[]
  yday: number[]
  avg7: number[]
  areasNow: Record<string, number>
  now: { system: number | null; tokyo: number | null; slot: string | null }
}

// Fill nulls / short arrays from a fixture baseline so the 48-slot chart geometry
// stays continuous even when a slot has no price.
function fill(live: (number | null)[] | undefined, fx: number[]): number[] {
  return fx.map((f, i) => {
    const v = live?.[i]
    return typeof v === 'number' && Number.isFinite(v) ? v : f
  })
}

export function useSystemLive(fxToday: number[], fxYday: number[], fxAvg7: number[]): SystemLive {
  const [snap, setSnap] = useState<SystemSnapshot | null>(null)
  useEffect(() => {
    let alive = true
    getSnapshot<SystemSnapshot>('system.json')
      .then((d) => alive && setSnap(d))
      .catch(() => alive && setSnap(null))
    return () => {
      alive = false
    }
  }, [])
  if (!snap) {
    return {
      ready: false,
      today: fxToday,
      yday: fxYday,
      avg7: fxAvg7,
      areasNow: {},
      now: { system: null, tokyo: null, slot: null },
    }
  }
  return {
    ready: true,
    today: fill(snap.system_today, fxToday),
    yday: fill(snap.system_yday, fxYday),
    avg7: fill(snap.system_avg7, fxAvg7),
    areasNow: snap.areas_now || {},
    now: snap.now || { system: null, tokyo: null, slot: null },
  }
}

const r1 = (n: number) => Math.round(n * 10) / 10
function stepPath(arr: number[]): string {
  let d = 'M' + r1(X(0)) + ',' + r1(Y(arr[0]))
  for (let i = 1; i < 48; i++) d += 'H' + r1(X(i)) + 'V' + r1(Y(arr[i]))
  return d + 'H944'
}

export interface Paths {
  today: string
  yday: string
  avg7: string
  todayA: string
  ydayA: string
  avg7A: string
}

/** Rebuild the six step paths from live 48-slot arrays (same geometry as fixtures). */
export function buildPaths(today: number[], yday: number[], avg7: number[]): Paths {
  return {
    today: stepPath(today),
    yday: stepPath(yday),
    avg7: stepPath(avg7),
    todayA: stepPath(today) + 'V290H46Z',
    ydayA: stepPath(yday) + 'V290H46Z',
    avg7A: stepPath(avg7) + 'V290H46Z',
  }
}
