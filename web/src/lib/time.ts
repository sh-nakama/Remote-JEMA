// The three time conventions in the exported data. Each parser returns epoch ms, or NaN.

const HAS_OFFSET = /(?:[zZ]|[+-]\d\d:?\d\d)$/

/** A DB timestamp such as `updated_at` ("2026-07-26 13:12:39.123456"): a UTC wall clock with no offset. */
export function parseDbTs(v?: string | null): number {
  if (!v) return NaN
  const s = v.replace(' ', 'T')
  return Date.parse(HAS_OFFSET.test(s) ? s : s + 'Z')
}

/** A day ("2026-07-26") as UTC midnight; a full timestamp without an offset is read as UTC too, never local. */
export function parseDay(v?: string | null): number {
  if (!v) return NaN
  if (v.length === 10) return Date.parse(v + 'T00:00:00Z')
  return parseDbTs(v)
}

/**
 * A market datetime ("2026-07-11T22:30:00", JST) kept as its wall clock: the digits are read as if
 * UTC, so charts label the JST slot whatever the viewer's timezone. NaN for non-ISO fixture labels.
 */
export function parseWallClock(v: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(v)
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], m[4] ? +m[4] : 0, m[5] ? +m[5] : 0) : NaN
}
