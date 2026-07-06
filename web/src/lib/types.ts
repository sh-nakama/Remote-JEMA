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
