import { describe, expect, it } from 'vitest'
import { parseDay, parseDbTs, parseWallClock } from './time'

const utc = (...a: [number, number, number, number?, number?, number?, number?]) =>
  Date.UTC(a[0], a[1] - 1, a[2], a[3] ?? 0, a[4] ?? 0, a[5] ?? 0, a[6] ?? 0)

describe('parseDbTs', () => {
  it('reads a naive DB timestamp as UTC', () => {
    expect(parseDbTs('2026-07-26 13:12:39.123456')).toBe(utc(2026, 7, 26, 13, 12, 39, 123))
  })
  it('keeps an explicit offset', () => {
    expect(parseDbTs('2026-07-26T13:12:39+09:00')).toBe(utc(2026, 7, 26, 4, 12, 39))
    expect(parseDbTs('2026-07-26T13:12:39Z')).toBe(utc(2026, 7, 26, 13, 12, 39))
  })
  it('is NaN for nothing or garbage', () => {
    expect(parseDbTs(null)).toBeNaN()
    expect(parseDbTs('')).toBeNaN()
    expect(parseDbTs('soon')).toBeNaN()
  })
})

describe('parseDay', () => {
  it('reads a day as UTC midnight', () => {
    expect(parseDay('2026-07-02')).toBe(utc(2026, 7, 2))
  })
  it('reads a full timestamp without an offset as UTC, not local', () => {
    expect(parseDay('2026-07-02T09:30:00')).toBe(utc(2026, 7, 2, 9, 30))
    expect(parseDay('2026-07-02 09:30:00')).toBe(utc(2026, 7, 2, 9, 30))
  })
  it('keeps an explicit offset', () => {
    expect(parseDay('2026-09-09T07:47:33+00:00')).toBe(utc(2026, 9, 9, 7, 47, 33))
  })
  it('is NaN for nothing', () => {
    expect(parseDay(undefined)).toBeNaN()
  })
})

describe('parseWallClock', () => {
  it('keeps the wall clock digits', () => {
    expect(parseWallClock('2026-07-11T22:30:00')).toBe(utc(2026, 7, 11, 22, 30))
    expect(parseWallClock('2026-07-11 22:30')).toBe(utc(2026, 7, 11, 22, 30))
    expect(parseWallClock('2026-07-11')).toBe(utc(2026, 7, 11))
  })
  it('is NaN for fixture day labels', () => {
    expect(parseWallClock('Jun 12')).toBeNaN()
  })
})
