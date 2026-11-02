// Pure pieces of the Policy Deep Dive that are tested on their own: a feed card's status pill and the
// rule for which meetings the bell calls new. Kept out of PolicyDeepDive.tsx, as MarketData.view.ts is
// out of MarketData.tsx, so the screen file exports only its component (Fast Refresh) and the tests
// need not load it.
import { POLICY_RECENT_MS } from '../lib/policyActivity'
import { isUnready, UNREADY_LABEL } from '../lib/readiness'
import type { CSS } from '../lib/style'
import { parseDbTs } from '../lib/time'
import type { Meeting } from './PolicyDeepDive.data'

const capitalise = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)

/** The status pill on a feed card. */
export function stChip(st: string): { txt: string; s: CSS } {
  const base: CSS = { fontSize: 10, fontWeight: 600, borderRadius: 999, padding: '1px 8px', flexShrink: 0, whiteSpace: 'nowrap' }
  if (st === 'done') return { txt: 'Summarised 済', s: { ...base, background: 'var(--upBg)', color: 'var(--up)' } }
  if (st === 'scheduled') return { txt: 'Scheduled 開催予定', s: { ...base, background: 'var(--upBg)', color: 'var(--up)' } }
  if (isUnready(st)) {
    const l = UNREADY_LABEL[st]
    return { txt: `${capitalise(l.en)} ${l.ja}`, s: { ...base, background: 'var(--bg2)', color: 'var(--mut)' } }
  }
  if (st === 'running') return { txt: 'Summarising…', s: { ...base, background: 'var(--acTint)', color: 'var(--acT)' } }
  if (st === 'failed') return { txt: 'Failed — retry', s: { ...base, background: 'var(--dnBg)', color: 'var(--dn)' } }
  if (st === 'error') return { txt: 'Errored 要約エラー', s: { ...base, background: 'var(--dnBg)', color: 'var(--dn)' } }
  if (st === 'untracked') return { txt: 'Untracked 未追跡', s: { ...base, border: '1px dashed var(--fnt2)', color: 'var(--mut)', background: 'transparent' } }
  return { txt: 'Pending · Queued', s: { ...base, background: 'var(--bg2)', color: 'var(--mut)' } }
}

/**
 * A meeting the bell lists as "new · awaiting digest": `pending` (detected, no briefing yet) and
 * touched within the recent window. The export's `status` is `done`, `error`, `pending` or — while a
 * meeting is not worth summarising yet — its readiness (`upcoming` / `awaiting` / `no_papers`);
 * `scheduled` exists only in the separate calendar list. Naming `pending` rather than excluding the
 * rest means a status added later stays out of the bell until someone decides it belongs there.
 * `usePolicyActivity` (the nav badge) also asks for a recent meeting *date*; this list never did, so
 * folding the two together would change what the bell shows.
 */
export function isNotifNew(m: Pick<Meeting, 'status' | 'updatedAt'>, nowMs: number): boolean {
  return m.status === 'pending' && nowMs - parseDbTs(m.updatedAt) <= POLICY_RECENT_MS
}
