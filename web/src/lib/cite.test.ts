import { describe, expect, it } from 'vitest'
import { citeHref, citeLabel, mergeCites, pageLabel, type Cite } from './cite'

const base: Cite = { n: 3, text: 'passage', doc: '資料1', url: 'https://www.meti.go.jp/a/005_01.pdf', page: 18 }

describe('citeHref', () => {
  it('deep-links to the cited page', () => {
    expect(citeHref(base)).toBe('https://www.meti.go.jp/a/005_01.pdf#page=18')
  })
  it('opens the document from the top when the page is unknown', () => {
    expect(citeHref({ ...base, page: undefined })).toBe('https://www.meti.go.jp/a/005_01.pdf')
  })
  it('replaces a fragment already on the URL rather than stacking one', () => {
    expect(citeHref({ ...base, url: 'https://x/a.pdf#zoom=50' })).toBe('https://x/a.pdf#page=18')
  })
  it('refuses anything that is not http(s) — the href ends up in window.open', () => {
    expect(citeHref({ ...base, url: 'javascript:alert(1)' })).toBeNull()
    expect(citeHref({ ...base, url: 'data:text/html,x' })).toBeNull()
    expect(citeHref({ ...base, url: undefined })).toBeNull()
  })
  it('ignores a nonsense page instead of emitting #page=0', () => {
    expect(citeHref({ ...base, page: 0 })).toBe('https://www.meti.go.jp/a/005_01.pdf')
  })
})

describe('labels', () => {
  it('shows document and page once resolved', () => {
    expect(citeLabel(base)).toBe('[3] 資料1 · p.18')
  })
  it('shows a range for a passage that crosses a page break', () => {
    expect(pageLabel({ ...base, pageEnd: 19 })).toBe('pp.18–19')
    expect(pageLabel({ ...base, pageEnd: 18 })).toBe('p.18')
  })
  it('names the document alone when only the page is unknown', () => {
    expect(citeLabel({ ...base, page: undefined })).toBe('[3] 資料1')
  })
  it('falls back to the passage when there is no document, and truncates it', () => {
    expect(citeLabel({ n: 2, text: 'short' })).toBe('[2] short')
    expect(citeLabel({ n: 2, text: 'x'.repeat(60) })).toBe(`[2] ${'x'.repeat(40)}…`)
  })
  it('does not claim a document whose link is unusable', () => {
    expect(citeLabel({ ...base, url: 'javascript:x' })).toBe('[3] passage')
  })
})

describe('mergeCites', () => {
  const snap: Cite[] = [{ n: 1, text: 'a' }, { n: 2, text: 'b' }]
  it('keeps the snapshot when nothing was resolved this session', () => {
    expect(mergeCites(snap, undefined)).toBe(snap)
    expect(mergeCites(undefined, undefined)).toEqual([])
  })
  it('replaces by citation number and appends the new', () => {
    const fresh: Cite[] = [{ n: 2, text: 'b', doc: '資料2', url: 'https://x/b.pdf', page: 4 }, { n: 3, text: 'c' }]
    expect(mergeCites(snap, fresh).map((c) => [c.n, c.page])).toEqual([[1, undefined], [2, 4], [3, undefined]])
  })
})
