// Client-side file exports for the working Export / .ics menus.
//
// In the static-snapshot architecture there is no server, and pre-generating a
// CSV per (area × product × level × range) selection would be a combinatorial
// explosion. Since the live adapters already hold the exact data on screen, we
// build CSV / iCalendar text in the browser and download it via a Blob — this
// exports whatever the user is actually looking at, for any selection.

function triggerDownload(filename: string, mime: string, text: string): void {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Revoke on the next tick so the download has started.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** Quote a CSV field only when it needs it (comma, quote, or newline). */
function csvField(v: unknown): string {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

/**
 * Download an array of flat records as CSV. Columns come from `headers` (or the
 * union of keys in row order). A UTF-8 BOM is prepended so Excel opens the
 * Japanese labels correctly.
 */
export function downloadCsv(filename: string, rows: Record<string, unknown>[], headers?: string[]): void {
  const cols = headers ?? (rows[0] ? Object.keys(rows[0]) : [])
  const lines = [cols.map(csvField).join(',')]
  for (const r of rows) lines.push(cols.map((c) => csvField(r[c])).join(','))
  triggerDownload(filename, 'text/csv', '﻿' + lines.join('\r\n'))
}

// ── iCalendar (RFC 5545) ─────────────────────────────────────────────────────
export interface IcsEvent {
  uid: string
  /** All-day date as YYYY-MM-DD (or a Date). */
  date: string | Date
  summary: string
  description?: string
  url?: string
}

function icsEscape(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')
}

function ymd(d: string | Date): string {
  // A date-only string ('YYYY-MM-DD') is a calendar date, not an instant —
  // read its digits directly. `new Date('YYYY-MM-DD')` would parse it as UTC
  // midnight and then local getters could shift it a day (off-by-one west of UTC).
  if (typeof d === 'string') {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d)
    if (m) return m[1] + m[2] + m[3]
  }
  const dt = typeof d === 'string' ? new Date(d) : d
  if (Number.isNaN(dt.getTime())) return ''
  const y = dt.getFullYear()
  const mo = String(dt.getMonth() + 1).padStart(2, '0')
  const day = String(dt.getDate()).padStart(2, '0')
  return `${y}${mo}${day}`
}

/** RFC 5545 §3.1 content-line folding: no line exceeds 75 octets; continuation
 *  lines begin with a single space. Splits on code-point boundaries so multi-byte
 *  (CJK) characters are never cut. */
function foldLine(line: string): string {
  const enc = new TextEncoder()
  if (enc.encode(line).length <= 75) return line
  const segments: string[] = []
  let cur = ''
  let bytes = 0
  for (const ch of line) {
    const b = enc.encode(ch).length
    const limit = segments.length === 0 ? 75 : 74 // continuation lines carry a leading space
    if (bytes + b > limit) {
      segments.push(cur)
      cur = ''
      bytes = 0
    }
    cur += ch
    bytes += b
  }
  if (cur) segments.push(cur)
  return segments.join('\r\n ')
}

/** Build an iCalendar document (all-day VEVENTs) from `events`. */
export function buildIcs(events: IcsEvent[]): string {
  const stamp = ymd(new Date()) + 'T000000Z'
  const lines: string[] = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//JEMA//Japan Energy Market Analytics//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
  ]
  for (const e of events) {
    const d = ymd(e.date)
    if (!d) continue
    lines.push('BEGIN:VEVENT')
    lines.push(`UID:${icsEscape(e.uid)}@jema`)
    lines.push(`DTSTAMP:${stamp}`)
    lines.push(`DTSTART;VALUE=DATE:${d}`)
    lines.push(`SUMMARY:${icsEscape(e.summary)}`)
    if (e.description) lines.push(`DESCRIPTION:${icsEscape(e.description)}`)
    if (e.url) lines.push(`URL:${icsEscape(e.url)}`)
    lines.push('END:VEVENT')
  }
  lines.push('END:VCALENDAR')
  return lines.map(foldLine).join('\r\n')
}

/** Build + download an .ics from `events`. Returns the number of events written. */
export function downloadIcs(filename: string, events: IcsEvent[]): number {
  const usable = events.filter((e) => ymd(e.date))
  triggerDownload(filename, 'text/calendar', buildIcs(usable))
  return usable.length
}
