import React, { useState } from 'react'

/**
 * Porting toolkit for the Claude Design hi-fi exports.
 *
 * The exports use inline `style="a:b;c:d"` strings + `style-hover="..."` +
 * raw inline SVG. To reproduce them faithfully with minimal translation:
 *   - `s()` parses an exact inline-style string into a React style object.
 *   - `<Hoverable>` reproduces `style-hover` (React can't do :hover inline).
 *   - `<RawSvg>` renders an exact `<svg>…</svg>` string via display:contents
 *     so the icon stays the real (flex) child — pixel-identical, zero rewrite.
 */

export type CSS = React.CSSProperties

/** Parse an inline CSS string ("display:flex;gap:8px") into a React style object.
 *  Custom properties (--x) are preserved; other props are camelCased. */
export function s(css?: string): CSS {
  const out: Record<string, string> = {}
  if (!css) return out as CSS
  for (const decl of css.split(';')) {
    const i = decl.indexOf(':')
    if (i < 0) continue
    const rawProp = decl.slice(0, i).trim()
    if (!rawProp) continue
    const val = decl.slice(i + 1).trim()
    const prop = rawProp.startsWith('--')
      ? rawProp
      : rawProp.replace(/-([a-z])/g, (_m, c: string) => c.toUpperCase())
    out[prop] = val
  }
  return out as CSS
}

/**
 * Expand a `border: "<width> <style> <color>"` shorthand into longhand
 * borderWidth/borderStyle/borderColor. `Hoverable` often toggles only the border
 * *color* on hover (base `border:1px solid X`, hover `border-color:Y`); having the
 * `border` shorthand in one render and a `borderColor` longhand in the next trips
 * React's shorthand/longhand conflict warning. Normalising to longhand in every
 * render keeps the property set consistent and silences it (visual result is
 * identical). Only the common 3-token form is expanded; anything else is left as-is.
 */
function expandBorderShorthand(st: Record<string, unknown>): CSS {
  const b = st.border
  if (typeof b === 'string') {
    const i1 = b.indexOf(' ')
    const i2 = i1 >= 0 ? b.indexOf(' ', i1 + 1) : -1
    if (i2 > 0) {
      if (st.borderWidth == null) st.borderWidth = b.slice(0, i1)
      if (st.borderStyle == null) st.borderStyle = b.slice(i1 + 1, i2)
      if (st.borderColor == null) st.borderColor = b.slice(i2 + 1)
      delete st.border
    }
  }
  return st as CSS
}

type HoverableProps = {
  as?: React.ElementType
  /** base inline-style string (the export's `style="…"`) */
  base?: string
  /** hover inline-style string (the export's `style-hover="…"`) */
  hover?: string
  /** extra style object merged last */
  style?: CSS
  children?: React.ReactNode
} & Omit<React.HTMLAttributes<HTMLElement>, 'style'>
// `aria-label` (and every other ARIA/HTML attribute) passes through via the
// HTMLAttributes rest props.

/** Reproduces `style="BASE" style-hover="HOVER"`.
 *
 * Accessibility: the exports render clickable *divs/spans*, and swapping them
 * for real `<button>`s would risk layout drift across dozens of call sites.
 * Instead, when an `onClick` is present the element gets `role="button"`,
 * `tabIndex=0`, a pointer cursor (unless the style already sets one) and
 * Enter/Space keyboard activation — visually identical, keyboard-operable. */
export function Hoverable({
  as,
  base,
  hover,
  style,
  children,
  onMouseEnter,
  onMouseLeave,
  onClick,
  onKeyDown,
  ...rest
}: HoverableProps) {
  const [h, setH] = useState(false)
  const El: React.ElementType = as ?? 'div'
  const merged = expandBorderShorthand({ ...s(base), ...(h && hover ? s(hover) : {}), ...style })
  if (onClick && merged.cursor == null) merged.cursor = 'pointer'
  return (
    <El
      {...(onClick ? { role: 'button', tabIndex: 0 } : {})}
      {...rest}
      onClick={onClick}
      onMouseEnter={(e: React.MouseEvent<HTMLElement>) => {
        setH(true)
        onMouseEnter?.(e)
      }}
      onMouseLeave={(e: React.MouseEvent<HTMLElement>) => {
        setH(false)
        onMouseLeave?.(e)
      }}
      onKeyDown={(e: React.KeyboardEvent<HTMLElement>) => {
        onKeyDown?.(e)
        // Enter/Space activates the click handler, but only when the key event
        // originated on this element itself — a keydown bubbling up from a
        // nested control (input, inner Hoverable) must not also activate the
        // ancestor, mirroring native <button> default-action semantics.
        if (
          onClick &&
          !e.defaultPrevented &&
          e.target === e.currentTarget &&
          (e.key === 'Enter' || e.key === ' ')
        ) {
          e.preventDefault() // Space would otherwise scroll the page
          e.currentTarget.click()
        }
      }}
      style={merged}
    >
      {children}
    </El>
  )
}

/** Render an exact inline-SVG string. `display:contents` keeps the <svg> as the
 *  effective layout child so surrounding flex/gap is unchanged. */
export function RawSvg({
  html,
  style,
  className,
}: {
  html: string
  style?: CSS
  className?: string
}) {
  return (
    <span
      className={className}
      style={{ display: 'contents', ...style }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
