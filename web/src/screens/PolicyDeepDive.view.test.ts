import { describe, expect, it } from 'vitest'
import { POLICY_RECENT_MS } from '../lib/policyActivity'
import { parseDbTs } from '../lib/time'
import { isNotifNew, stChip } from './PolicyDeepDive.view'

// The wording is pinned as literals, not read back from the readiness record, so a change to what a
// user sees fails here.
const BASE = { fontSize: 10, fontWeight: 600, borderRadius: 999, padding: '1px 8px', flexShrink: 0, whiteSpace: 'nowrap' }
const MUTED = { ...BASE, background: 'var(--bg2)', color: 'var(--mut)' }
const GOOD = { ...BASE, background: 'var(--upBg)', color: 'var(--up)' }
const BAD = { ...BASE, background: 'var(--dnBg)', color: 'var(--dn)' }

describe('stChip', () => {
  it.each([
    ['upcoming', 'Upcoming 開催前'],
    ['awaiting', 'Awaiting materials 資料待ち'],
    ['no_papers', 'No papers published 資料なし'],
  ])('writes a %s meeting as "%s", in the muted pill', (status, txt) => {
    expect(stChip(status)).toEqual({ txt, s: MUTED })
  })

  it('leaves every other status as it was', () => {
    expect(stChip('done')).toEqual({ txt: 'Summarised 済', s: GOOD })
    expect(stChip('scheduled')).toEqual({ txt: 'Scheduled 開催予定', s: GOOD })
    expect(stChip('running')).toEqual({ txt: 'Summarising…', s: { ...BASE, background: 'var(--acTint)', color: 'var(--acT)' } })
    expect(stChip('failed')).toEqual({ txt: 'Failed — retry', s: BAD })
    expect(stChip('error')).toEqual({ txt: 'Errored 要約エラー', s: BAD })
    expect(stChip('untracked')).toEqual({
      txt: 'Untracked 未追跡',
      s: { ...BASE, border: '1px dashed var(--fnt2)', color: 'var(--mut)', background: 'transparent' },
    })
    // `pending`, and anything unrecognised, is the queued pill.
    for (const status of ['pending', 'ready', '', 'toString', 'something-new']) {
      expect(stChip(status)).toEqual({ txt: 'Pending · Queued', s: MUTED })
    }
  })
})

describe('isNotifNew', () => {
  const NOW = Date.parse('2026-11-02T00:00:00Z')
  // A DB timestamp: naive UTC, as `updated_at` is exported.
  const stamp = (ms: number) => new Date(ms).toISOString().replace('T', ' ').replace('Z', '')
  const meeting = (status: string, updatedAt = stamp(NOW - 1000)) => ({ status, updatedAt })

  // The status clauses of the filter this replaced, a deny-list of everything but a pending meeting.
  const oldChain = (status: string) =>
    status !== 'done' &&
    status !== 'error' &&
    status !== 'scheduled' &&
    status !== 'upcoming' &&
    status !== 'awaiting' &&
    status !== 'no_papers'

  it('agrees with the old chain on every status the export emits, and on "scheduled"', () => {
    // meetings.json: done | error | pending | upcoming | awaiting | no_papers. `scheduled` only
    // reaches the screen through the separate calendar list, never this one.
    for (const status of ['done', 'error', 'pending', 'upcoming', 'awaiting', 'no_papers', 'scheduled']) {
      expect(isNotifNew(meeting(status), NOW), status).toBe(oldChain(status))
    }
    expect(isNotifNew(meeting('pending'), NOW)).toBe(true)
  })

  it('is an allow-list: a status the export never emits no longer gets through', () => {
    // The chain let anything it did not name pass. Nothing emits '' or an unknown status, so what
    // the bell shows is unchanged; this pins the one place the two shapes differ.
    for (const status of ['', 'queued']) {
      expect(oldChain(status), status).toBe(true)
      expect(isNotifNew(meeting(status), NOW), status).toBe(false)
    }
  })

  it('still needs the meeting touched inside the recent window, edge included', () => {
    expect(isNotifNew(meeting('pending', stamp(NOW - POLICY_RECENT_MS)), NOW)).toBe(true)
    expect(isNotifNew(meeting('pending', stamp(NOW - POLICY_RECENT_MS - 1000)), NOW)).toBe(false)
    expect(parseDbTs(stamp(NOW))).toBe(NOW) // the stamps above really are what the screen parses
  })

  it('leaves out a meeting with no readable update time', () => {
    for (const updatedAt of [null, undefined, '', 'not a date']) {
      expect(isNotifNew({ status: 'pending', updatedAt }, NOW), String(updatedAt)).toBe(false)
    }
  })
})
