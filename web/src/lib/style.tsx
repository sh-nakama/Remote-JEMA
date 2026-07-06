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

/** Merge several inline-style strings / objects left-to-right. */
export function sx(...parts: Array<string | CSS | false | null | undefined>): CSS {
  let acc: Record<string, unknown> = {}
  for (const p of parts) {
    if (!p) continue
    acc = { ...acc, ...(typeof p === 'string' ? s(p) : p) }
  }
  return acc as CSS
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

/** Reproduces `style="BASE" style-hover="HOVER"`. */
export function Hoverable({
  as,
  base,
  hover,
  style,
  children,
  onMouseEnter,
  onMouseLeave,
  ...rest
}: HoverableProps) {
  const [h, setH] = useState(false)
  const El: React.ElementType = as ?? 'div'
  return (
    <El
      {...rest}
      onMouseEnter={(e: React.MouseEvent<HTMLElement>) => {
        setH(true)
        onMouseEnter?.(e)
      }}
      onMouseLeave={(e: React.MouseEvent<HTMLElement>) => {
        setH(false)
        onMouseLeave?.(e)
      }}
      style={{ ...s(base), ...(h && hover ? s(hover) : {}), ...style }}
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
