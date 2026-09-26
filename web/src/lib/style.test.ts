import type React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { activateOnKey, press, s } from './style'

type KeyEv = React.KeyboardEvent<HTMLElement>

const keyEvent = (key: string, fromChild = false) => {
  const click = vi.fn()
  const self = { click } as unknown as HTMLElement
  const ev = { key, target: fromChild ? {} : self, currentTarget: self, defaultPrevented: false, preventDefault: vi.fn() }
  return { ev: ev as unknown as KeyEv, click, prevent: ev.preventDefault }
}

describe('keyboard activation', () => {
  it.each(['Enter', ' '])('%j clicks the element and stops the page from scrolling', (key) => {
    const { ev, click, prevent } = keyEvent(key)
    activateOnKey(ev)
    expect(click).toHaveBeenCalledOnce()
    expect(prevent).toHaveBeenCalledOnce()
  })
  it('ignores other keys and keys bubbling up from a nested control', () => {
    for (const [key, fromChild] of [['a', false], ['Tab', false], ['Enter', true]] as const) {
      const { ev, click } = keyEvent(key, fromChild)
      activateOnKey(ev)
      expect(click).not.toHaveBeenCalled()
    }
  })
  it('press() makes a focusable button, with aria-pressed only when a state is given', () => {
    const fn = vi.fn()
    expect(press(fn)).toEqual({ role: 'button', tabIndex: 0, onClick: fn, onKeyDown: activateOnKey })
    expect(press(fn, false)['aria-pressed' as keyof ReturnType<typeof press>]).toBe(false)
  })
})

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
