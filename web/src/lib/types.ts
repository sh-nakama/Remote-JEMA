// Shared types for JEMA web-data snapshots (produced by `repower export-web`)
// and the screen models, so live data and mock fixtures share one contract.

export type Level = 'Native' | 'Daily' | 'Weekly' | 'Monthly'

export type AreaKey =
  | 'hokkaido'
  | 'tohoku'
  | 'tepco'
  | 'chubu'
  | 'hokuriku'
  | 'kansai'
  | 'chugoku'
  | 'shikoku'
  | 'kyushu'

/** A row of area demand + generation mix (MW), aggregated to a level. */
export interface SupplyRecord {
  datetime: string
  area_demand_mw: number | null
  nuclear: number | null
  lng: number | null
  coal: number | null
  oil: number | null
  thermal_other: number | null
  hydro: number | null
  geothermal: number | null
  biomass: number | null
  solar_actual: number | null
  wind_actual: number | null
  pumped: number | null
  battery: number | null
  interconnect: number | null
  other: number | null
  total_supply: number | null
}

/** A row of JEPX area price (¥/kWh). max/avg/min collapse at Native. */
export interface PriceRecord {
  datetime: string
  price_avg: number | null
  price_max: number | null
  price_min: number | null
}

export interface WholesaleSnapshot {
  schema: number
  area: AreaKey
  level: Level
  start: string
  end: string
  supply: SupplyRecord[]
  price: PriceRecord[]
}

export interface WholesaleStats {
  schema: number
  area: AreaKey
  window_days: number
  start: string
  end: string
  avg_demand_mw: number | null
  peak_demand_mw: number | null
  avg_price: number | null
}

export interface Manifest {
  schema: number
  generated_at: string
  anchor: string
  areas: AreaKey[]
  levels: Level[]
  sources: Record<string, string | null>
  datasets: Record<string, { files: number; bytes: number }>
}

/** Structured result of the auth-free catch-up refresh job. */
export interface PolicyJobResult {
  new_meetings: number
  dated: number
  upcoming: number | null
  discovered: number
  pending: number
  note: string
}

/** Status of the single-flight background policy job served by the local
 * backend (`repower web-api`) at GET/POST `/api/policy/job` — mirrors the
 * `_job` dict in `src/repower/web_api.py`. */
export interface PolicyJob {
  /** 'catchup' = in-process auth-free refresh; 'command' = `repower policy` subprocess. */
  kind: 'catchup' | 'command' | null
  /** Human label (e.g. 'run', 'backfill', 'catchup'). */
  cmd: string | null
  /** Policy CLI argv (command jobs only). */
  argv: string[] | null
  state: 'idle' | 'running' | 'done' | 'error'
  /** UTC ISO timestamps. */
  started_at: string | null
  finished_at: string | null
  /** Subprocess exit code (command jobs only). */
  exit_code: number | null
  /** Structured result (catchup jobs only). */
  result: PolicyJobResult | null
  /** Stdout tail (command jobs only). */
  output: string[]
  error: string | null
}
