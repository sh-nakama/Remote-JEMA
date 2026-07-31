// Shared SVG chart frame for the Market Data screens: crosshair hover with an
// anchored tooltip, plus click-and-drag range selection (brush) and gap-aware
// geometry helpers.
//
// Charts are drawn in a fixed 480-wide viewBox with `preserveAspectRatio="none"`,
// so all geometry below is in viewBox units and `PLOT_X0`/`PLOT_W` define the
// plotting band inside it.
import { useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { s } from './style'

export const VIEW_W = 480
export const PLOT_X0 = 8
export const PLOT_W = 464

/** Minimum drag distance (viewBox units) that counts as a brush rather than a click. */
const BRUSH_MIN = 6

/**
 * Contiguous index runs of a time series, split wherever the gap between two
 * consecutive samples exceeds `factor` x the series' median cadence.
 *
 * Real snapshots have multi-week holes (one TSO's supply feed can lag a month).
 * Drawing them as a single polyline bridges the hole with a straight segment that
 * reads as genuine flat data, so each run is drawn as its own polyline/polygon.
 */
export function gapSegments(t: number[], factor = 2.5): [number, number][] {
  const n = t.length
  if (n === 0) return []
  if (n < 3) return [[0, n - 1]]
  const deltas: number[] = []
  for (let i = 1; i < n; i++) {
    const d = t[i] - t[i - 1]
    if (Number.isFinite(d) && d > 0) deltas.push(d)
  }
  if (deltas.length === 0) return [[0, n - 1]]
  const sorted = [...deltas].sort((a, b) => a - b)
  const median = sorted[Math.floor(sorted.length / 2)] || 0
  const tol = median > 0 ? median * factor : Infinity
  const out: [number, number][] = []
  let start = 0
  for (let i = 1; i < n; i++) {
    const d = t[i] - t[i - 1]
    if (Number.isFinite(d) && d > tol) {
      out.push([start, i - 1])
      start = i
    }
  }
  out.push([start, n - 1])
  // Single points can't be stroked; keep them so callers can render a dot, but
  // drop empty runs.
  return out.filter(([a, b]) => b >= a)
}

/** `points` string for one segment of a line, from per-index x/y accessors. */
export function segPoints(
  seg: [number, number],
  xOf: (i: number) => number,
  yOf: (i: number) => number,
): string {
  const out: string[] = []
  for (let i = seg[0]; i <= seg[1]; i++) out.push(xOf(i).toFixed(1) + ',' + yOf(i).toFixed(1))
  return out.join(' ')
}

/** `points` string for a band polygon: upper edge left→right, lower edge right→left. */
export function bandPoints(
  seg: [number, number],
  xOf: (i: number) => number,
  upper: (i: number) => number,
  lower: (i: number) => number,
): string {
  const out: string[] = []
  for (let i = seg[0]; i <= seg[1]; i++) out.push(xOf(i).toFixed(1) + ',' + upper(i).toFixed(1))
  for (let i = seg[1]; i >= seg[0]; i--) out.push(xOf(i).toFixed(1) + ',' + lower(i).toFixed(1))
  return out.join(' ')
}

export interface ChartFrameProps {
  /** Number of plotted points (hover is inert below 2). */
  n: number
  /** Hover labels aligned to the points (already formatted). */
  label: (i: number) => string
  /** Per-point viewBox x positions. */
  xs: number[]
  /** y position of the crosshair dot for point i (omit for no dot). */
  dotY?: (i: number) => number
  /** Tooltip body for point i. */
  tip: (i: number) => ReactNode
  /** viewBox height (default 160). */
  height?: number
  /** Optional CSS pixel height. `preserveAspectRatio="none"` means the drawing
   *  stretches to fit, so this constrains on-screen size without touching the
   *  geometry — needed for the tall expanded chart, which would otherwise render
   *  ~800px tall at full width. */
  cssHeight?: number
  /** Called with the selected viewBox x-range once a drag wider than ~6 units ends. */
  onBrush?: (x0: number, x1: number) => void
  /** Optional caption rendered while dragging (e.g. the selected time span). */
  brushLabel?: (x0: number, x1: number) => string
  /** Called on double-click — used to clear an active zoom. */
  onReset?: () => void
  children: ReactNode
}

/**
 * Chart frame: renders `children` inside the SVG and layers interaction on top —
 * a dashed crosshair + anchored value tooltip for the nearest point, and (when
 * `onBrush` is supplied) a drag-to-select rectangle that reports the chosen
 * x-range. When `n < 2` (e.g. fixtures) the chart renders but is inert.
 */
export function ChartFrame({
  n,
  label,
  xs,
  dotY,
  tip,
  height = 160,
  cssHeight,
  onBrush,
  brushLabel,
  onReset,
  children,
}: ChartFrameProps) {
  const [iRaw, setI] = useState<number | null>(null)
  const [drag, setDrag] = useState<{ a: number; b: number } | null>(null)
  // Held in a ref as well so the window-level mouseup handler sees the live value
  // without re-subscribing on every mousemove.
  const dragRef = useRef<{ a: number; b: number } | null>(null)

  const useXs = xs.length === n && n > 0
  const xOf = (k: number) => (useXs ? xs[k] : PLOT_X0 + (k / Math.max(1, n - 1)) * PLOT_W)

  const vbX = (e: ReactMouseEvent<SVGSVGElement>): number => {
    const r = e.currentTarget.getBoundingClientRect()
    return ((e.clientX - r.left) / r.width) * VIEW_W
  }

  const nearest = (px: number): number => {
    if (useXs) {
      let k = 0
      let best = Infinity
      for (let j = 0; j < n; j++) {
        const d = Math.abs(xs[j] - px)
        if (d < best) {
          best = d
          k = j
        }
      }
      return k
    }
    return Math.max(0, Math.min(n - 1, Math.round(((px - PLOT_X0) / PLOT_W) * (n - 1))))
  }

  const endDrag = (px: number | null) => {
    const d = dragRef.current
    dragRef.current = null
    setDrag(null)
    // Committing a brush re-windows the series, so the hovered point no longer
    // exists. Drop the hover rather than carry an index into the new, shorter data.
    setI(null)
    if (!d || !onBrush) return
    const b = px == null ? d.b : px
    const lo = Math.min(d.a, b)
    const hi = Math.max(d.a, b)
    if (hi - lo >= BRUSH_MIN) onBrush(lo, hi)
  }

  const onDown = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (!onBrush || n < 2 || e.button !== 0) return
    const px = vbX(e)
    dragRef.current = { a: px, b: px }
    setDrag({ a: px, b: px })
    e.preventDefault() // suppress the browser's native text/image drag
  }

  const onMove = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (n < 2) return
    const px = vbX(e)
    if (dragRef.current) {
      dragRef.current = { a: dragRef.current.a, b: px }
      setDrag({ a: dragRef.current.a, b: px })
    }
    const k = nearest(px)
    if (k !== iRaw) setI(k)
  }

  const onUp = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (dragRef.current) endDrag(vbX(e))
  }

  const onLeave = () => {
    // Releasing outside the chart still commits the selection made inside it.
    if (dragRef.current) endDrag(null)
    setI(null)
  }

  // `n` shrinks whenever the series is re-windowed (brush commit, range change, a
  // background snapshot refresh). The hover index is local state, so clamp it at
  // the point of use: `label`/`tip`/`dotY` index caller arrays of length `n` and
  // would otherwise read past the end and throw.
  const i = iRaw != null && iRaw < n ? iRaw : null
  const x = i != null ? xOf(i) : 0
  // dotY is caller-supplied; a non-finite result would emit cy="NaN" and be
  // rejected by the SVG DOM, so suppress the dot instead.
  const dy = i != null && dotY ? dotY(i) : NaN
  const showDot = Number.isFinite(dy) && Number.isFinite(x)
  const leftPct = i != null ? Math.max(0, Math.min(100, (x / VIEW_W) * 100)) : 0
  const dragging = drag != null && Math.abs(drag.b - drag.a) >= BRUSH_MIN
  const dLo = drag ? Math.min(drag.a, drag.b) : 0
  const dHi = drag ? Math.max(drag.a, drag.b) : 0
  const tipTxt = dragging && brushLabel ? brushLabel(dLo, dHi) : null

  return (
    <div style={s(`position:relative${dragging ? ';user-select:none' : ''}`)}>
      <svg
        viewBox={`0 0 ${VIEW_W} ${height}`}
        style={s(
          `width:100%;height:${cssHeight ? cssHeight + 'px' : 'auto'};display:block;margin-top:10px${onBrush && n >= 2 ? ';cursor:crosshair' : ''}`,
        )}
        preserveAspectRatio="none"
        onMouseMove={onMove}
        onMouseLeave={onLeave}
        onMouseDown={onDown}
        onMouseUp={onUp}
        onDoubleClick={onReset}
      >
        {children}
        {i != null && !dragging && Number.isFinite(x) && (
          <g>
            <line
              x1={x}
              y1="6"
              x2={x}
              y2={height - 8}
              stroke="var(--mut)"
              strokeWidth="0.8"
              strokeDasharray="3 3"
            ></line>
            {showDot ? <circle cx={x} cy={dy} r="2.6" fill="var(--tx)"></circle> : null}
          </g>
        )}
        {dragging && (
          <rect
            x={dLo}
            y="6"
            width={dHi - dLo}
            height={Math.max(0, height - 14)}
            fill="var(--ac)"
            fillOpacity="0.14"
            stroke="var(--ac)"
            strokeWidth="0.7"
          ></rect>
        )}
      </svg>
      {(i != null || tipTxt) && (() => {
        // Anchor proportionally: translateX(-p%) at left:p% left-aligns the tooltip
        // at p=0, centres it at p=50 and right-aligns it at p=100, so a wide
        // tooltip stays inside the card at both edges. A fixed -50% overflowed.
        const p = tipTxt ? Math.max(0, Math.min(100, ((dLo + dHi) / 2 / VIEW_W) * 100)) : leftPct
        return (
          <div
            style={s(
              `position:absolute;top:2px;left:${p}%;transform:translateX(-${p}%);background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:4px 9px;font-size:11px;white-space:nowrap;pointer-events:none;color:var(--tx);box-shadow:var(--sh1);z-index:5;font-feature-settings:'tnum' 1`,
            )}
          >
            {tipTxt ? (
              <span>{tipTxt}</span>
            ) : (
              <>
                <span style={s('color:var(--mut);margin-right:6px')}>{label(i as number)}</span>
                {tip(i as number)}
              </>
            )}
          </div>
        )
      })()}
    </div>
  )
}
