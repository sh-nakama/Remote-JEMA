import { describe, expect, it } from 'vitest'
import { AT_LIMIT, balancingFromSummary, tielineStats } from './MarketData.live'
import type { BalancingSummary, TlLine } from './MarketData.live'

const slots = (f: (i: number) => number) => Array.from({ length: 48 }, (_, i) => f(i))

describe('tielineStats', () => {
  const line = (over: Partial<TlLine> = {}): TlLine => ({
    pair: 'Tokyo → Chubu',
    key: 'fc',
    fwd: { from: ['tepco'], to: ['chubu'], reserved: slots(() => 100), limit: slots(() => 800) },
    rev: { from: ['chubu'], to: ['tepco'], reserved: slots(() => 0), limit: slots(() => 900) },
    ...over,
  })

  it('takes each slot from the direction holding the larger share of its limit', () => {
    const rev = { from: ['chubu'], to: ['tepco'], reserved: slots((i) => (i === 30 ? 891 : 0)), limit: slots(() => 900) }
    const st = tielineStats(line({ rev }))
    expect(st.slots[0]).toEqual({ share: 0.125, reserved: 100, limit: 800, rev: false })
    expect(st.peakIdx).toBe(30)
    expect(st.peak).toEqual({ share: 0.99, reserved: 891, limit: 900, rev: true })
    expect(st.atLimit).toBe(1)
    expect(st.maxLimit).toBe(900)
    // Day averages count both directions: (48·100 + 891) / 48 reserved, 800 + 900 limit.
    expect(st.avgReserved).toBeCloseTo(100 + 891 / 48)
    expect(st.avgLimit).toBe(1700)
  })

  it('reports a line with no limit in either direction as having no peak, not as 0%', () => {
    const none = { reserved: slots(() => 0), limit: slots(() => 0) }
    const st = tielineStats(line({ fwd: { from: ['kansai'], to: ['shikoku'], ...none }, rev: { from: ['shikoku'], to: ['kansai'], ...none } }))
    expect(st.peak).toBeNull()
    expect(st.peakIdx).toBe(-1)
    expect(st.atLimit).toBe(0)
    expect(st.slots.every((x) => Number.isNaN(x.share))).toBe(true)
  })

  it('treats missing slots as no data and counts only shares at or above the threshold', () => {
    const fwd = { from: ['tepco'], to: ['chubu'], reserved: slots((i) => (i < 2 ? NaN : i === 5 ? AT_LIMIT * 800 : 10)), limit: slots(() => 800) }
    const st = tielineStats(line({ fwd }))
    expect(Number.isNaN(st.slots[0].share)).toBe(false) // the reverse direction still has a limit
    expect(st.slots[0].rev).toBe(true)
    expect(st.atLimit).toBe(1)
  })
})

describe('balancingFromSummary', () => {
  const day = (contracted: number, price: number) => ({ required_mw: 100, offered_mw: 200, contracted_mw: contracted, price })
  const summary: BalancingSummary = {
    schema: 1,
    dates: ['2026-09-09', '2026-09-10'],
    national: { '2026-09-09': day(90, 2), '2026-09-10': day(95, 3) },
    products: [
      {
        code: '1-0',
        product: 'Primary',
        days: {
          '2026-09-09': { ...day(90, 2), slots: 48, short_slots: 30, max_gap_mw: 50, longest_run: null },
          '2026-09-10': { ...day(95, 3), slots: 48, short_slots: 37, max_gap_mw: 224.3, longest_run: { start: '00:00', end: '14:00', slots: 28 } },
        },
        areas: [{ area: 'tepco', ...day(40, 3.5) }],
      },
      {
        code: '2-2',
        product: 'Secondary 2',
        days: { '2026-09-09': { ...day(10, 1), slots: 48, short_slots: 0, max_gap_mw: 0, longest_run: null } },
        areas: [],
      },
    ],
  }

  it('shapes the latest day per product with the prior day for comparison', () => {
    const b = balancingFromSummary(summary)!
    expect(b.date).toBe('2026-09-10')
    expect(b.prevDate).toBe('2026-09-09')
    expect(b.day?.contracted_mw).toBe(95)
    expect(b.prev?.price).toBe(2)
    expect(b.rows['1-0']).toMatchObject({ price: 3, proc: 95, off: 200, ach: 47.5, short: 37, slots: 48, prevShort: 30 })
    expect(b.rows['1-0'].run).toEqual({ start: '00:00', end: '14:00', slots: 28 })
    expect(b.areaRows['1-0']).toEqual([{ area: 'tepco', price: 3.5, proc: 40, off: 200, ach: 20 }])
  })

  it('leaves out a product missing from the latest day instead of reusing an older one', () => {
    expect(balancingFromSummary(summary)!.rows['2-2']).toBeUndefined()
  })

  it('returns null when the summary holds no usable day', () => {
    expect(balancingFromSummary({ schema: 1, dates: [], national: {}, products: [] })).toBeNull()
    expect(balancingFromSummary({ ...summary, products: [summary.products[1]] })).toBeNull()
  })
})
