// Shared chart/UI helpers for the JEMA screens (Market Overview, Market Data,
// Capacity & Auctions). Each hi-fi port originally carried its own copy of these
// and they had drifted; this module is the single source of truth now.
import type { CSS } from './style'

export interface Chip {
  txt: string
  style: CSS
}

/** Base style shared by the KPI delta chips (and their neutral variants). */
export const CHIP_BASE: CSS = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  fontSize: 11.5,
  fontWeight: 600,
  padding: '3px 9px',
  borderRadius: 999,
  marginTop: 9,
  fontFeatureSettings: "'tnum' 1",
}

/**
 * Flat-chip threshold in percent. The two hi-fi exports disagreed
 * (screens/market-overview.html used 0.5, screens/market-data.html 0.05); the
 * design spec is explicit — docs/design/JEMA-product-design-spec.md, "Delta
 * chips: … neutral grey `--chip-flat` when |Δ|<0.5%" — so 0.5% is the design
 * intent and both screens now share it.
 */
export const CHIP_FLAT_PCT = 0.5

/** Delta chip from an absolute change `d` and its percent change `p`. */
export function makeChip(d: number, p: number): Chip {
  if (Math.abs(p) < CHIP_FLAT_PCT)
    return {
      txt: '— ±0.0%',
      style: { ...CHIP_BASE, background: 'rgba(138,147,163,.14)', color: 'var(--mut)' },
    }
  const up = d > 0
  const sgn = up ? '+' : '−'
  return {
    txt: (up ? '▲ ' : '▼ ') + sgn + Math.abs(d).toFixed(2) + ' (' + sgn + Math.abs(p).toFixed(1) + '%)',
    style: {
      ...CHIP_BASE,
      background: up ? 'var(--upBg)' : 'var(--dnBg)',
      color: up ? 'var(--up)' : 'var(--dn)',
    },
  }
}

/** Delta chip from current/previous values (percent computed vs `prev`). */
export function chip(cur: number, prev: number): Chip {
  const d = cur - prev
  return makeChip(d, prev ? (d / prev) * 100 : 0)
}

/** Segmented-control button (range / granularity / language toggles). */
export const segBase = (on: boolean): CSS => ({
  padding: '4px 13px',
  borderRadius: 999,
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
  background: on ? 'var(--ac)' : 'transparent',
  color: on ? '#FFFFFF' : 'var(--mut)',
  transition: 'all .15s',
  whiteSpace: 'nowrap',
})

/** Toggleable filter chip (area selection chips, radar filters). */
export const filterChipBase = (on: boolean): CSS => ({
  fontSize: 11.5,
  fontWeight: 600,
  padding: '3px 11px',
  borderRadius: 999,
  cursor: 'pointer',
  border: on ? '1px solid var(--ac)' : '1px solid var(--bd2)',
  background: on ? 'var(--acTint)' : 'var(--bg1)',
  color: on ? 'var(--acT)' : 'var(--mut)',
  whiteSpace: 'nowrap',
})

/**
 * Per-area series colour, `[light, dark]`. Same palette the Market screens
 * paint their area series with, so an area keeps one identity across the app.
 * `dark` entries only differ where the light tone lacks contrast on the dark
 * canvas.
 */
export const AREA_COLORS: Record<string, [string, string]> = {
  hokkaido: ['#1B2A4A', '#8FA7D9'],
  tohoku: ['#00A5CF', '#1FB6DC'],
  tepco: ['#7B2D8E', '#C77BD8'],
  chubu: ['#2A9D8F', '#2A9D8F'],
  hokuriku: ['#4A6FA5', '#7C9CD1'],
  kansai: ['#E76F51', '#E76F51'],
  chugoku: ['#C1440E', '#E8794B'],
  shikoku: ['#E9C46A', '#E9C46A'],
  kyushu: ['#8AB17D', '#8AB17D'],
}

/** Resolve an area's colour for the active theme. */
export function areaColor(key: string, dark: boolean): string {
  const c = AREA_COLORS[key]
  return c ? c[dark ? 1 : 0] : dark ? '#5D6B85' : '#B4BCC9'
}

/** 30-min slot index (0–47) → "HH:MM". */
export function slotLabel(i: number): string {
  return String(Math.floor(i / 2)).padStart(2, '0') + ':' + (i % 2 ? '30' : '00')
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** ISO datetime/date → short axis label ("Jul 2"). */
export function fmtDate(iso: string): string {
  const p = iso.slice(0, 10).split('-')
  if (p.length < 3) return iso
  return MONTHS[Number(p[1]) - 1] + ' ' + Number(p[2])
}
