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
  areas_today: Record<string, (number | null)[]>
  areas_yday: Record<string, number>
}

export interface SystemLive {
  ready: boolean
  today: number[]
  yday: number[]
  avg7: number[]
  areasNow: Record<string, number>
  areasToday: Record<string, (number | null)[]>
  areasYday: Record<string, number>
  now: { system: number | null; tokyo: number | null; slot: string | null }
  dateToday: string | null
  dateYday: string | null
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
      areasToday: {},
      areasYday: {},
      now: { system: null, tokyo: null, slot: null },
      dateToday: null,
      dateYday: null,
    }
  }
  return {
    ready: true,
    today: fill(snap.system_today, fxToday),
    yday: fill(snap.system_yday, fxYday),
    avg7: fill(snap.system_avg7, fxAvg7),
    areasNow: snap.areas_now || {},
    areasToday: snap.areas_today || {},
    areasYday: snap.areas_yday || {},
    now: snap.now || { system: null, tokyo: null, slot: null },
    dateToday: snap.date_today,
    dateYday: snap.date_yday,
  }
}

// ── Policy committee radar (live done meetings) ─────────────────────────────

interface PComSnap {
  key: string
  org: 'METI' | 'OCCTO' | 'EGC'
  en: string
  ja: string
}
interface PMtgSnap {
  com: string
  num: number
  org: string
  date: string
  dateReal?: boolean
  status: string
  tori: boolean
  prevEn?: string
  prevJa?: string
}
interface PUpcomingSnap {
  date: string
  org: string
  committee_key: string | null
  en: string
  ja: string
  num: number | null
  url: string
  matched: boolean
}

export interface PolicyMeetingsLive {
  ready: boolean
  meetings: Meeting[]
  upcoming: Meeting[]
}

const TIER = (org: string): 'METI' | 'OCCTO' | 'EGC' =>
  org === 'OCCTO' || org === 'EGC' ? org : 'METI'

/** The latest meeting of every tracked committee (newest first) for the radar,
 * plus the scheduled (future) meetings for the "Recent & Scheduled" timeline.
 * Both carry the real meeting date + committee key. The caller filters and caps
 * the list; ordering is pure recency. */
export function usePolicyMeetings(): PolicyMeetingsLive {
  const [state, setState] = useState<PolicyMeetingsLive>({ ready: false, meetings: [], upcoming: [] })
  useEffect(() => {
    let alive = true
    Promise.all([
      getSnapshot<{ committees: PComSnap[] }>('policy/committees.json'),
      getSnapshot<{ meetings: PMtgSnap[]; upcoming?: PUpcomingSnap[] }>('policy/meetings.json'),
    ])
      .then(([c, m]) => {
        if (!alive) return
        const com: Record<string, PComSnap> = {}
        for (const x of c.committees || []) com[x.key] = x
        // latest meeting per committee (summarised or pending) — the committee radar.
        const all = (m.meetings || []).slice()
        // newest first (date desc, then meeting number desc)
        all.sort((a, b) => (a.date !== b.date ? (a.date < b.date ? 1 : -1) : (b.num || 0) - (a.num || 0)))
        const seen = new Set<string>()
        const reps: PMtgSnap[] = []
        for (const x of all) {
          if (seen.has(x.com)) continue
          seen.add(x.com)
          reps.push(x)
        }
        const meetings: Meeting[] = reps.map((x) => {
          const cc = com[x.com]
          const d = x.date || ''
          const isDone = x.status === 'done'
          return {
            en: cc ? cc.en : x.com,
            ja: cc ? cc.ja : x.com,
            tier: TIER(x.org),
            no: x.num,
            m: d ? parseInt(d.slice(5, 7), 10) : 0,
            day: d ? parseInt(d.slice(8, 10), 10) : 0,
            tori: x.tori,
            done: isDone,
            sEn: isDone ? x.prevEn || '' : '',
            sJa: isDone ? x.prevJa || '' : '',
            date: d || undefined,
            dateReal: !!x.dateReal,
            key: x.com,
          }
        })
        const upcoming: Meeting[] = (m.upcoming || []).map((u) => {
          const d = u.date || ''
          const cc = u.committee_key ? com[u.committee_key] : undefined
          return {
            en: cc ? cc.en : u.en,
            ja: cc ? cc.ja : u.ja,
            tier: TIER(u.org),
            no: u.num || 0,
            m: d ? parseInt(d.slice(5, 7), 10) : 0,
            day: d ? parseInt(d.slice(8, 10), 10) : 0,
            sched: true,
            done: false,
            date: d || undefined,
            dateReal: true,
            key: u.committee_key || undefined,
          }
        })
        setState({ ready: true, meetings, upcoming })
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
