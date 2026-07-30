import { useEffect, useState } from 'react'
import { getSnapshot, useDataNonce } from './data'
import { useApp } from './app'
import { s } from './style'

/**
 * Recent policy-pipeline activity, read straight from the exported
 * policy/meetings.json snapshot.
 *
 * Shared by the "Policy Deep Dive" nav badge (on every screen) and the Market
 * Overview bell so the two can never disagree about what "new" means.
 */

export const POLICY_RECENT_DAYS = 7
const RECENT_MS = POLICY_RECENT_DAYS * 24 * 60 * 60 * 1000

interface MeetingSnap {
  key: string
  com: string
  num: number
  org: string
  en: string
  ja: string
  date: string
  updatedAt?: string | null
  status: string
  tori: boolean
}

export interface PolicyActivityItem {
  key: string
  com: string
  en: string
  ja: string
  org: string
  num: number
  date: string
  /** updatedAt in epoch ms. */
  ts: number
  tori: boolean
}

export interface PolicyActivity {
  ready: boolean
  /** Meetings that reached `done` in the window, newest first. */
  summarised: PolicyActivityItem[]
  /** Meetings detected but still awaiting a digest, newest first. */
  detected: PolicyActivityItem[]
  /** Distinct committees touched in the window. */
  committees: number
  /** summarised + detected. */
  count: number
}

/**
 * The backend stores `updated_at` as a UTC wall clock with no offset
 * ("2026-07-26 13:12:39.123456"); pin it to UTC so the window doesn't drift with
 * the viewer's timezone.
 */
export function parseDbTs(v?: string | null): number {
  if (!v) return NaN
  let t = v.replace(' ', 'T')
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(t)) t += 'Z'
  return Date.parse(t)
}

const EMPTY: PolicyActivity = { ready: false, summarised: [], detected: [], committees: 0, count: 0 }

export function usePolicyActivity(): PolicyActivity {
  const nonce = useDataNonce()
  const [state, setState] = useState<PolicyActivity>(EMPTY)
  useEffect(() => {
    let alive = true
    getSnapshot<{ meetings?: MeetingSnap[] }>('policy/meetings.json')
      .then((raw) => {
        if (!alive) return
        const now = Date.now()
        // `updatedAt` alone can't separate a newly detected meeting from an old one
        // touched by a detection sweep — a backfill bumps hundreds of rows at once.
        // So a *pending* meeting only counts as new when its meeting date is recent
        // too. (Summarised meetings need no such guard: reaching `done` is the news,
        // however old the meeting.)
        const dateIsRecent = (d: string): boolean => {
          const t = Date.parse((d || '') + 'T00:00:00Z')
          return Number.isFinite(t) && now - t <= RECENT_MS
        }
        const summarised: PolicyActivityItem[] = []
        const detected: PolicyActivityItem[] = []
        const coms = new Set<string>()
        for (const m of raw.meetings || []) {
          const ts = parseDbTs(m.updatedAt)
          if (Number.isNaN(ts) || now - ts > RECENT_MS) continue
          const item: PolicyActivityItem = {
            key: m.key,
            com: m.com,
            en: m.en,
            ja: m.ja,
            org: m.org,
            num: m.num,
            date: m.date,
            ts,
            tori: !!m.tori,
          }
          if (m.status === 'done') summarised.push(item)
          else if (m.status === 'pending' && dateIsRecent(m.date)) detected.push(item)
          else continue // `error`, or an old row swept by a backfill
          if (m.com) coms.add(m.com)
        }
        const byTs = (a: PolicyActivityItem, b: PolicyActivityItem) => b.ts - a.ts
        summarised.sort(byTs)
        detected.sort(byTs)
        setState({
          ready: true,
          summarised,
          detected,
          committees: coms.size,
          count: summarised.length + detected.length,
        })
      })
      .catch(() => alive && setState(EMPTY))
    return () => {
      alive = false
    }
  }, [nonce])
  return state
}

/** Count pill on the "Policy Deep Dive" nav row. Hidden when there's no activity. */
export function PolicyNavBadge() {
  const { lang } = useApp()
  const a = usePolicyActivity()
  if (!a.ready || a.count === 0) return null
  const title =
    lang === 'ja'
      ? `過去${POLICY_RECENT_DAYS}日 — 委員会 ${a.committees}件更新 · 要約済み ${a.summarised.length}件 · 要約待ち ${a.detected.length}件`
      : `Last ${POLICY_RECENT_DAYS} days — ${a.committees} committee${a.committees === 1 ? '' : 's'} updated · ${a.summarised.length} summarised · ${a.detected.length} awaiting digest`
  return (
    <span
      title={title}
      style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}
    >
      {a.count}
    </span>
  )
}
