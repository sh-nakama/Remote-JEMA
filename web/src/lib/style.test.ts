import { describe, expect, it } from 'vitest'
import { s } from './style'

describe('s', () => {
  it('parses an inline style string, camelCasing all but custom properties', () => {
    expect(s('display:flex; font-size:12px;--x: 1px;')).toEqual({ display: 'flex', fontSize: '12px', '--x': '1px' })
  })
  it('returns one frozen object per string, so a mutation cannot leak into other elements', () => {
    const a = s('gap:8px')
    expect(s('gap:8px')).toBe(a)
    expect(Object.isFrozen(a)).toBe(true)
    expect(() => {
      ;(a as Record<string, string>).gap = '0'
    }).toThrow(TypeError)
  })
  it('is empty and frozen for no input', () => {
    expect(s()).toEqual({})
    expect(Object.isFrozen(s(''))).toBe(true)
  })
})
