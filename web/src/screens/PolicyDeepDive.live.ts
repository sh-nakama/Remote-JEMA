// Live-data adapter for the Policy Deep Dive screen.
//
// Fetches policy/committees.json + policy/meetings.json (produced by
// `repower export-web` from the policy_committee/meeting/material tables) and
// reshapes them into the screen's fixture types. Fixtures remain the loading
// fallback so the render code is unchanged.

import { useEffect, useState } from 'react'
import { getSnapshot } from '../lib/data'
import type { Committee, DigestSection, DocRef, JpSection, Meeting } from './PolicyDeepDive.data'

interface CommitteeSnap {
  key: string
  org: 'METI' | 'OCCTO' | 'EGC'
  en: string
  ja: string
  tier: string
  followed: boolean
  last: string
  url: string
}

interface MeetingSnap {
  key: string
  com: string
  org: string
  en: string
  ja: string
  date: string
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

export interface PolicyLive {
  ready: boolean
  committees: Committee[]
  meetings: Meeting[]
}

export function usePolicyLive(): PolicyLive {
  const [state, setState] = useState<PolicyLive>({ ready: false, committees: [], meetings: [] })
  useEffect(() => {
    let alive = true
    Promise.all([
      getSnapshot<{ committees: CommitteeSnap[] }>('policy/committees.json'),
      getSnapshot<{ meetings: MeetingSnap[] }>('policy/meetings.json'),
    ])
      .then(([c, m]) => {
        if (!alive) return
        const committees: Committee[] = (c.committees || []).map((x) => ({
          key: x.key,
          org: x.org,
          en: x.en,
          ja: x.ja,
          tier: x.tier,
          followed: x.followed,
          last: x.last,
          url: x.url,
        }))
        const meetings: Meeting[] = (m.meetings || []).map((x) => ({
          key: x.key,
          com: x.com,
          org: x.org,
          en: x.en,
          ja: x.ja,
          date: x.date,
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
        setState({ ready: true, committees, meetings })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  return state
}
