// Live-data adapter for the Market Overview intraday chart + spot tiles.
//
// Fetches the system-price snapshot (system.json, from `repower export-web`) and
// reshapes it into the 48-slot arrays / step paths the existing chart geometry
// consumes. Fixtures remain the loading/fallback state.

import { useEffect, useState } from 'react'
import { getSnapshot } from '../lib/data'
import { X, Y, type Meeting } from './MarketOverview.data'

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

// ── Policy committee radar (live done meetings) ─────────────────────────────

interface PComSnap {
  key: string
  org: 'METI' | 'OCCTO' | 'EGC'
  en: string
  ja: string
  followed: boolean
}
interface PMtgSnap {
  com: string
  num: number
  org: string
  date: string
  status: string
  tori: boolean
  prevEn?: string
  prevJa?: string
}

export interface PolicyMeetingsLive {
  ready: boolean
  meetings: Meeting[]
}

/** The most recently summarised committee meetings, mapped to the Overview radar's
 * Meeting shape. No relevance score exists upstream, so the radar is ranked by
 * recency (newest = top / longest bar); the date shown is the summary date. */
export function usePolicyMeetings(): PolicyMeetingsLive {
  const [state, setState] = useState<PolicyMeetingsLive>({ ready: false, meetings: [] })
  useEffect(() => {
    let alive = true
    Promise.all([
      getSnapshot<{ committees: PComSnap[] }>('policy/committees.json'),
      getSnapshot<{ meetings: PMtgSnap[] }>('policy/meetings.json'),
    ])
      .then(([c, m]) => {
        if (!alive) return
        const com: Record<string, PComSnap> = {}
        for (const x of c.committees || []) com[x.key] = x
        const done = (m.meetings || []).filter((x) => x.status === 'done')
        // newest first (date desc, then meeting number desc)
        done.sort((a, b) => (a.date !== b.date ? (a.date < b.date ? 1 : -1) : (b.num || 0) - (a.num || 0)))
        // one row per committee (its latest summarised meeting) — a committee radar
        const seen = new Set<string>()
        const reps: PMtgSnap[] = []
        for (const x of done) {
          if (seen.has(x.com)) continue
          seen.add(x.com)
          reps.push(x)
        }
        const meetings: Meeting[] = reps.slice(0, 8).map((x, i) => {
          const cc = com[x.com]
          const d = x.date || ''
          return {
            en: cc ? cc.en : x.com,
            ja: cc ? cc.ja : x.com,
            tier: (x.org as 'METI' | 'OCCTO' | 'EGC') || 'METI',
            no: x.num,
            m: d ? parseInt(d.slice(5, 7), 10) : 0,
            day: d ? parseInt(d.slice(8, 10), 10) : 0,
            score: Math.max(45, 92 - i * 6),
            tori: x.tori,
            followed: cc ? cc.followed : false,
            done: true,
            sEn: x.prevEn || '',
            sJa: x.prevJa || '',
          }
        })
        setState({ ready: true, meetings })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  return state
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
