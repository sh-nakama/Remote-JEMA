// Digest citation chips: label + deep-link.
//
// The export resolves each citation to the document it cites and, where it could be located,
// the page (`policy/meetings.json` → `cites`). The deep-link is a plain `#page=N` fragment on
// the source PDF's own URL, which the browsers' built-in PDF viewers honour — no proxy, no copy
// of the PDF. A citation with no page opens the document from the top; one with no document is
// a label only.

export interface Cite {
  /** NotebookLM's citation number — the `[n]` in the digest text. */
  n: number
  /** The cited passage (truncated), shown as a tooltip. */
  text: string
  /** Short document label, e.g. `資料3`. Present once the citation is attributed to a document. */
  doc?: string
  /** The document's own URL (http/https only; the export blanks anything else). */
  url?: string
  /** 1-based PDF page the passage starts on; `pageEnd` when it runs on to a later page. */
  page?: number
  pageEnd?: number
}

const HTTP = /^https?:\/\//i

/** `url` for the cited page, or null when the citation has no usable document link. A page is
 * a physical PDF page (what `#page=` counts), not a printed page label. */
export function citeHref(c: Cite): string | null {
  if (!c.url || !HTTP.test(c.url)) return null
  const base = c.url.split('#')[0]
  return c.page && c.page > 0 ? `${base}#page=${Math.floor(c.page)}` : base
}

/** `p.18`, or `pp.18–19` for a passage that crosses a page break. */
export function pageLabel(c: Cite): string {
  if (!c.page) return ''
  return c.pageEnd && c.pageEnd > c.page ? `pp.${c.page}–${c.pageEnd}` : `p.${c.page}`
}

/** Chip text: `[3] 資料1 · p.18` once resolved; the passage's opening words otherwise. */
export function citeLabel(c: Cite): string {
  if (c.doc && citeHref(c)) {
    const p = pageLabel(c)
    return `[${c.n}] ${c.doc}${p ? ' · ' + p : ''}`
  }
  return c.text.length > 40 ? `[${c.n}] ${c.text.slice(0, 40)}…` : `[${c.n}] ${c.text}`
}

/** Chips for a meeting, preferring freshly resolved ones (from a click this session) over the
 * snapshot's, matched by citation number. */
export function mergeCites(base: Cite[] | undefined, fresh: Cite[] | undefined): Cite[] {
  if (!fresh?.length) return base ?? []
  const byN = new Map(fresh.map((c) => [c.n, c]))
  const merged = (base ?? []).map((c) => byN.get(c.n) ?? c)
  const have = new Set(merged.map((c) => c.n))
  return merged.concat(fresh.filter((c) => !have.has(c.n)))
}
