import type { CSSProperties } from 'react'
import { useApp } from './app'
import { useManifest } from './data'
import type { Manifest } from './types'

/**
 * Data-freshness chip driven by the export manifest (`manifest.json`).
 *
 * Renders NOTHING while the manifest is loading, on fetch error, or when it is
 * null — that is the fixture-mode guard: in fixture mode the snapshot fetches
 * fail, so no chip appears next to the frozen fixture dates. Once the manifest
 * loads it shows "Data as of {generated_at}", with warn styling when the
 * export is older than 48 hours.
 */

const STALE_MS = 48 * 60 * 60 * 1000

/** "2026-07-15T17:33:13+00:00" → "2026-07-15 17:33" (same slicing as Settings). */
export function fmtStamp(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

/** Optional per-dataset counts the policy exporter adds to `datasets.policy`. */
export interface PolicyCounts {
  committees: number
  meetings: number
  summarised: number
}

/** The manifest's `datasets.policy` counts, or null when absent/incomplete. */
export function policyCounts(m: Manifest | null): PolicyCounts | null {
  const d = m?.datasets?.['policy'] as
    | { files: number; bytes: number; committees?: number; meetings?: number; summarised?: number }
    | undefined
  if (!d) return null
  const { committees, meetings, summarised } = d
  if (typeof committees !== 'number' || typeof meetings !== 'number' || typeof summarised !== 'number') return null
  return { committees, meetings, summarised }
}

export function FreshnessChip({ inverse, style }: { inverse?: boolean; style?: CSSProperties }) {
  const { lang } = useApp()
  const { data, loading, error } = useManifest()
  // Fixture-mode guard: no manifest → no chip (never a broken/frozen date).
  if (loading || error || !data || !data.generated_at) return null
  const t = Date.parse(data.generated_at)
  if (!Number.isFinite(t)) return null
  const stale = Date.now() - t > STALE_MS
  const label = lang === 'ja' ? 'データ基準' : 'Data as of'
  const value = fmtStamp(data.generated_at)
  const title = `${label} ${data.generated_at}`

  if (inverse) {
    // On the navy sidebar cards: same typography as the line it replaces.
    return (
      <div
        title={title}
        style={{ fontSize: 12, color: 'rgba(255,255,255,.78)', fontFeatureSettings: "'tnum' 1", ...style }}
      >
        {label}{' '}
        <span style={{ fontWeight: 600, color: stale ? '#F0C07A' : '#FFFFFF' }}>{value}</span>
      </div>
    )
  }
  return (
    <div
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 11.5,
        fontFeatureSettings: "'tnum' 1",
        color: stale ? 'var(--warnTx)' : 'var(--mut)',
        background: stale ? 'var(--warnBg)' : 'var(--bg1)',
        border: `1px solid ${stale ? 'var(--warnTx)' : 'var(--bd)'}`,
        borderRadius: 999,
        padding: '3px 11px',
        ...style,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: 999,
          background: stale ? 'var(--warnDot)' : 'var(--okDot)',
          flexShrink: 0,
        }}
      ></span>
      {label} <span style={{ fontWeight: 600 }}>{value}</span>
    </div>
  )
}
