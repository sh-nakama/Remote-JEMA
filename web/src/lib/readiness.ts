/**
 * Whether a policy meeting is worth summarising yet — the `readiness` the export derives for
 * every meeting (`store.meeting_readiness`). `policy/meetings.json` reuses the three not-ready
 * values as a not-yet-summarised meeting's `status`, so every list that names them shares the
 * labels below instead of spelling them out again.
 */
export type Readiness = 'ready' | 'upcoming' | 'awaiting' | 'no_papers'

/** The readiness values that keep a meeting out of the summarising worklist. */
export type Unready = Exclude<Readiness, 'ready'>

/**
 * Keyed on the type, so adding a value to `Readiness` without a label here fails `tsc` instead of
 * leaving a chip blank.
 */
export const UNREADY_LABEL: Record<Unready, { en: string; ja: string }> = {
  upcoming: { en: 'upcoming', ja: '開催前' },
  awaiting: { en: 'awaiting materials', ja: '資料待ち' },
  no_papers: { en: 'no papers published', ja: '資料なし' },
}

/**
 * Own keys only: a snapshot can carry any string, and `'toString' in UNREADY_LABEL` would
 * call an `Object.prototype` member "unready" and index a label that does not exist.
 */
export function isUnready(r: unknown): r is Unready {
  return typeof r === 'string' && Object.prototype.hasOwnProperty.call(UNREADY_LABEL, r)
}
