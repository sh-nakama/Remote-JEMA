import { describe, expect, it } from 'vitest'
import {
  agoText,
  committeesByBacklog,
  indexQueue,
  positionLabel,
  queueKey,
  runsUntil,
  selectItems,
  splitAtCap,
  withGaps,
  type QueueItem,
  type QueuePayload,
} from './policyQueue'

const item = (rank: number, com: string, num: number, over: Partial<QueueItem> = {}): QueueItem => ({
  rank, com, num, date: null, kind: 'new', requested: false, state: 'detected', retries: 0, ...over,
})

const ITEMS: QueueItem[] = [
  item(1, 'santeii', 109, { requested: true }),
  item(2, 'saisei_kano', 66),
  item(3, 'santeii', 108),
  item(4, 'youryou_kentoukai', 74, { kind: 'update', state: 'done' }),
  item(5, 'saisei_kano', 65, { kind: 'retry', state: 'error', retries: 2 }),
]

describe('selectItems', () => {
  it('returns everything for all/all', () => {
    expect(selectItems(ITEMS, { filter: 'all', com: null })).toHaveLength(5)
  })
  it('filters by kind', () => {
    expect(selectItems(ITEMS, { filter: 'update', com: null }).map((i) => i.num)).toEqual([74])
    expect(selectItems(ITEMS, { filter: 'retry', com: null }).map((i) => i.num)).toEqual([65])
    expect(selectItems(ITEMS, { filter: 'new', com: null }).map((i) => i.num)).toEqual([109, 66, 108])
  })
  it('"requested" cuts across kinds', () => {
    expect(selectItems(ITEMS, { filter: 'requested', com: null }).map((i) => i.num)).toEqual([109])
  })
  it('restricts to a committee and combines with a kind', () => {
    expect(selectItems(ITEMS, { filter: 'all', com: 'saisei_kano' }).map((i) => i.num)).toEqual([66, 65])
    expect(selectItems(ITEMS, { filter: 'retry', com: 'saisei_kano' }).map((i) => i.num)).toEqual([65])
    expect(selectItems(ITEMS, { filter: 'update', com: 'saisei_kano' })).toEqual([])
  })
  it('keeps the server order', () => {
    expect(selectItems(ITEMS, { filter: 'all', com: null }).map((i) => i.rank)).toEqual([1, 2, 3, 4, 5])
  })
})

describe('splitAtCap', () => {
  it('splits at the daily cap by rank, not by position in a filtered list', () => {
    const { next, waiting } = splitAtCap(ITEMS, 3)
    expect(next.map((i) => i.rank)).toEqual([1, 2, 3])
    expect(waiting.map((i) => i.rank)).toEqual([4, 5])
  })
  it('a filtered list keeps its ranks, so the cap line lands in the right place', () => {
    const onlySaisei = selectItems(ITEMS, { filter: 'all', com: 'saisei_kano' })
    const { next, waiting } = splitAtCap(onlySaisei, 2)
    expect(next.map((i) => i.rank)).toEqual([2])
    expect(waiting.map((i) => i.rank)).toEqual([5])
  })
  it('handles an empty queue and a cap larger than the queue', () => {
    expect(splitAtCap([], 8)).toEqual({ next: [], waiting: [] })
    expect(splitAtCap(ITEMS, 99).waiting).toEqual([])
  })
})

describe('committeesByBacklog', () => {
  it('sorts by total queued, biggest first, ties by key', () => {
    const out = committeesByBacklog({
      b: { new: 2, update: 0, retry: 0, requested: 0 },
      a: { new: 1, update: 1, retry: 0, requested: 0 },
      c: { new: 5, update: 0, retry: 1, requested: 1 },
    })
    expect(out.map((o) => [o.com, o.n])).toEqual([['c', 6], ['a', 2], ['b', 2]])
  })
})

describe('positionLabel / runsUntil', () => {
  it('names the run when a meeting is inside the cap', () => {
    expect(positionLabel(item(3, 'x', 1), 8, false)).toEqual({ text: 'next run #3', soon: true })
    expect(positionLabel(item(3, 'x', 1), 8, true)).toEqual({ text: '次回 #3', soon: true })
  })
  it('shows a bare rank beyond the cap', () => {
    expect(positionLabel(item(41, 'x', 1), 8, false)).toEqual({ text: '#41', soon: false })
    expect(positionLabel(item(9, 'x', 1), 8, false).soon).toBe(false) // the cap is inclusive of 8 only
  })
  it('counts daily runs at the cap, at least one', () => {
    expect(runsUntil(1, 8)).toBe(1)
    expect(runsUntil(8, 8)).toBe(1)
    expect(runsUntil(9, 8)).toBe(2)
    expect(runsUntil(291, 8)).toBe(37)
    expect(runsUntil(5, 0)).toBe(0) // an unset cap must not divide by zero
  })
})

describe('indexQueue', () => {
  it('looks a meeting up by committee and number', () => {
    const q = { items: ITEMS } as QueuePayload
    const m = indexQueue(q)
    expect(m.get(queueKey('youryou_kentoukai', 74))?.kind).toBe('update')
    expect(m.get(queueKey('santeii', 1))).toBeUndefined()
  })
  it('tolerates a missing queue (an older snapshot)', () => {
    expect(indexQueue(undefined).size).toBe(0)
    expect(indexQueue(null).size).toBe(0)
  })
})

describe('agoText', () => {
  const now = Date.parse('2026-10-16T12:00:00Z')
  it('reads DB timestamps as UTC and phrases the gap', () => {
    expect(agoText('2026-10-16 11:59:50', false, now)).toBe('just now')
    expect(agoText('2026-10-16 11:30:00', false, now)).toBe('30m ago')
    expect(agoText('2026-10-16 09:00:00.123456', false, now)).toBe('3h ago')
    expect(agoText('2026-10-13 12:00:00', true, now)).toBe('3日前')
  })
  it('is a dash for nothing, and never negative for a clock-skewed future stamp', () => {
    expect(agoText(null, false, now)).toBe('—')
    expect(agoText('not a date', false, now)).toBe('—')
    expect(agoText('2026-10-16 12:00:30', false, now)).toBe('just now')
  })
})

describe('withGaps', () => {
  const r = (rank: number) => ({ rank })
  it('reports how many ranks were skipped before each item', () => {
    expect(withGaps([r(9), r(10), r(100), r(291)], 8).map((x) => x.gap)).toEqual([0, 0, 89, 190])
  })
  it('has no gap for a contiguous run, and none before the first item when it follows the cap', () => {
    expect(withGaps([r(9), r(10), r(11)], 8).map((x) => x.gap)).toEqual([0, 0, 0])
  })
  it('never goes negative if the list overlaps its start', () => {
    expect(withGaps([r(5)], 8)[0].gap).toBe(0)
  })
  it('is empty for no items', () => {
    expect(withGaps([], 8)).toEqual([])
  })
})
