// Live-data adapter for the Capacity & Auctions screen.
//
// Fetches capacity/main_auction.json + capacity/ltda.json (produced by
// `repower export-web` from the curated, source-cited capacity_data module) and
// returns them in the screen's fixture shapes. Fixtures remain the loading
// fallback so the render code and geometry are unchanged.

import { useEffect, useState } from 'react'
import { getSnapshot } from '../lib/data'
import type { LtdaRow, MaRow } from './CapacityAuctions.data'

export interface CapacityLive {
  ready: boolean
  ma: MaRow[]
  ltda: LtdaRow[]
}

export function useCapacityLive(): CapacityLive {
  const [state, setState] = useState<CapacityLive>({ ready: false, ma: [], ltda: [] })
  useEffect(() => {
    let alive = true
    Promise.all([
      getSnapshot<{ results: MaRow[] }>('capacity/main_auction.json'),
      getSnapshot<{ rows: LtdaRow[] }>('capacity/ltda.json'),
    ])
      .then(([ma, ltda]) => {
        if (!alive) return
        setState({ ready: true, ma: ma.results || [], ltda: ltda.rows || [] })
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  return state
}
