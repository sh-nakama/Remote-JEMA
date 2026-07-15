// Live-data adapter for the Policy Deep Dive screen.
//
// Two sources, one shape:
//  - Local master (interactive): GET /api/policy/deepdive — straight from the DB,
//    so tracking / backfilling a committee shows immediately without a re-export.
//  - Read-only deploy: the static policy/committees.json + policy/meetings.json
//    snapshots produced by `repower export-web`.
// Both carry the identical payload ({committees, meetings, upcoming}), so they are
// reshaped by the same code into the screen's fixture types. Fixtures remain the
// loading fallback so the render code is unchanged.

import { useEffect, useState } from 'react'
import { getSnapshot } from '../lib/data'
import type { Committee, DigestSection, DocRef, JpSection, Meeting, Upcoming } from './PolicyDeepDive.data'

interface CommitteeSnap {
  key: string
  org: 'METI' | 'OCCTO' | 'EGC'
  en: string
  ja: string
  tier: string
  tracked: boolean
  discovered?: boolean
  last: string
  url: string
  source_count?: number
  meetings?: number
  last_date?: string | null
  synthesisEn?: string | null
  synthesisJa?: string | null
  lastSynth?: number | null
  done?: number
  pending?: number
  error?: number
}

interface MeetingSnap {
  key: string
  com: string
  num: number
  org: string
  en: string
  ja: string
  date: string
  dateReal?: boolean
  status: string
  tori: boolean
  title: string
  titleJa: string
  sub: string
  docs: DocRef[]
  digest?: DigestSection[]
  jp?: JpSection[]
  refs?: string[]
  prevEn?: string
  prevJa?: string
  emptyTitle?: string
  emptySub?: string
}

interface UpcomingSnap {
  date: string | null
  org: string
  committee_key: string | null
  en: string
  ja: string
  num: number | null
  url: string
  source?: string
  matched?: boolean
}

export interface PolicyLive {
  ready: boolean
  /** True when interactive mode had to fall back to the static snapshot because
   * the live API failed (after retries) — the data shown may be stale. */
  stale: boolean
  committees: Committee[]
  meetings: Meeting[]
  upcoming: Upcoming[]
}

interface Raw {
  committees?: CommitteeSnap[]
  meetings?: MeetingSnap[]
  upcoming?: UpcomingSnap[]
}

function reshape(raw: Raw): Omit<PolicyLive, 'ready' | 'stale'> {
  const committees: Committee[] = (raw.committees || []).map((x) => ({
    key: x.key,
    org: x.org,
    en: x.en,
    ja: x.ja,
    tier: x.tier,
    // `followed` is now a client-side preference (see AppProvider); the export only
    // says whether we *track* it. Default false and let the screen overlay real
    // follow state from context.
    followed: false,
    tracked: x.tracked,
    discovered: x.discovered ?? false,
    last: x.last,
    url: x.url,
    sourceCount: x.source_count ?? 0,
    meetings: x.meetings ?? 0,
    lastDate: x.last_date ?? null,
    synthesisEn: x.synthesisEn ?? null,
    synthesisJa: x.synthesisJa ?? null,
    lastSynth: x.lastSynth ?? null,
    done: x.done ?? 0,
    pending: x.pending ?? 0,
    error: x.error ?? 0,
  }))
  const meetings: Meeting[] = (raw.meetings || []).map((x) => ({
    key: x.key,
    com: x.com,
    num: x.num,
    org: x.org,
    en: x.en,
    ja: x.ja,
    date: x.date,
    dateReal: x.dateReal ?? true,
    status: x.status,
    tori: x.tori,
    title: x.title,
    titleJa: x.titleJa,
    sub: x.sub,
    prevEn: x.prevEn,
    prevJa: x.prevJa,
    digest: x.digest,
    jp: x.jp,
    refs: x.refs,
    emptyTitle: x.emptyTitle,
    emptySub: x.emptySub,
    docs: x.docs || [],
  }))
  const upcoming: Upcoming[] = (raw.upcoming || []).map((u) => ({
    key: 'u_' + (u.committee_key || u.org) + '_' + (u.num ?? ''),
    com: u.committee_key || '',
    status: 'scheduled',
    prevKey: '',
    en: u.en,
    ja: u.ja,
    date: u.date || '',
    title: u.en,
    titleJa: u.ja,
    sub: (u.org || 'METI') + (u.num ? ' · 第' + u.num + '回' : ''),
    prevEn: '',
    prevJa: '',
    agendaEn: [],
    agendaJa: [],
    docs: [],
  }))
  return { committees, meetings, upcoming }
}

export function usePolicyLive(interactive: boolean): PolicyLive {
  const [state, setState] = useState<PolicyLive>({ ready: false, stale: false, committees: [], meetings: [], upcoming: [] })
  useEffect(() => {
    let alive = true
    const loadStatic = (): Promise<Raw> =>
      Promise.all([
        getSnapshot<{ committees: CommitteeSnap[] }>('policy/committees.json'),
        getSnapshot<{ meetings: MeetingSnap[]; upcoming?: UpcomingSnap[] }>('policy/meetings.json'),
      ]).then(([c, m]) => ({ committees: c.committees, meetings: m.meetings, upcoming: m.upcoming }))
    // The live endpoint can transiently fail right after the backend starts, so
    // retry before giving up — and if it still fails, fall back to the static
    // snapshot but say so (`stale`) instead of silently presenting old data as live.
    const loadLive = (attempt = 0): Promise<Raw> =>
      fetch('/api/policy/deepdive')
        .then((r) => {
          if (!r.ok) throw new Error('deepdive ' + r.status)
          return r.json() as Promise<Raw>
        })
        .catch((e) => {
          if (attempt >= 2) throw e
          return new Promise<Raw>((res) => setTimeout(() => res(loadLive(attempt + 1)), 500 * (attempt + 1)))
        })
    const apply = (raw: Raw, stale: boolean) => {
      if (alive) setState({ ready: true, stale, ...reshape(raw) })
    }
    if (interactive) {
      loadLive()
        .then((raw) => apply(raw, false))
        .catch(() => loadStatic().then((raw) => apply(raw, true)).catch(() => {}))
    } else {
      loadStatic()
        .then((raw) => apply(raw, false))
        .catch(() => {})
    }
    return () => {
      alive = false
    }
  }, [interactive])
  return state
}
