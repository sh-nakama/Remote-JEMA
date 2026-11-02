import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { StateChip } from './menus'
import { isUnready, UNREADY_LABEL, type Unready } from './readiness'

// The wording is pinned as literals, not read back from UNREADY_LABEL: these tests exist to catch
// the text a user sees changing, which a test that reuses the record could never notice.
const LABELS: Record<Unready, { en: string; ja: string }> = {
  upcoming: { en: 'upcoming', ja: '開催前' },
  awaiting: { en: 'awaiting materials', ja: '資料待ち' },
  no_papers: { en: 'no papers published', ja: '資料なし' },
}
const UNREADY = Object.keys(LABELS) as Unready[]

describe('isUnready', () => {
  it('accepts exactly the three values that keep a meeting out of the worklist', () => {
    expect(Object.keys(UNREADY_LABEL).sort()).toEqual(['awaiting', 'no_papers', 'upcoming'])
    for (const r of UNREADY) expect(isUnready(r)).toBe(true)
  })
  it('rejects ready, nothing, and anything the type does not know', () => {
    // Includes Object.prototype members: a lookup by `in` would call those unready.
    for (const r of ['ready', '', 'removed', 'Upcoming', 'toString', 'constructor', '__proto__', 'hasOwnProperty']) {
      expect(isUnready(r)).toBe(false)
    }
    for (const r of [undefined, null, 3, {}, ['upcoming']]) expect(isUnready(r)).toBe(false)
  })
})

describe('StateChip', () => {
  const chip = (state: string, readiness: string | undefined, lang: 'en' | 'ja' = 'en') => {
    const html = renderToStaticMarkup(createElement(StateChip, { state, readiness, lang }))
    return {
      text: html.replace(/<[^>]*>/g, ''),
      // The label's colour (the dot's is a `background`, so `;color:` only matches the text).
      color: /;color:([^;"]+)/.exec(html)?.[1],
    }
  }

  it.each(UNREADY)('labels a %s meeting in both languages, in the muted colour', (r) => {
    expect(chip('detected', r, 'en')).toEqual({ text: LABELS[r].en, color: 'var(--mut)' })
    expect(chip('detected', r, 'ja')).toEqual({ text: LABELS[r].ja, color: 'var(--mut)' })
  })

  it('lets readiness speak for any state that is not done, errors included', () => {
    for (const state of ['detected', 'error', 'generating', '']) {
      expect(chip(state, 'awaiting').text).toBe('awaiting materials')
    }
  })

  it('shows a summarised meeting as summarised whatever its readiness says', () => {
    for (const r of [...UNREADY, 'ready', undefined]) {
      expect(chip('done', r, 'en')).toEqual({ text: 'Summarised', color: 'var(--up)' })
      expect(chip('done', r, 'ja').text).toBe('要約済み')
    }
  })

  it('falls back to the state for ready, none, or a value this build has no label for', () => {
    for (const r of ['ready', undefined, '', 'removed', 'toString', 'constructor']) {
      expect(chip('detected', r, 'en')).toEqual({ text: 'Pending', color: 'var(--mut)' })
      expect(chip('error', r, 'ja')).toEqual({ text: 'エラー', color: 'var(--dn)' })
    }
  })
})
