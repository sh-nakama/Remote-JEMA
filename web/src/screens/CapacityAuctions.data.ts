// Fixture data ported from screens/capacity-auctions.html (DCLogic constructor).

import type { AreaKey } from '../lib/types'

/**
 * The nine OCCTO areas the capacity market clears over, in the order every
 * OCCTO results table lists them. Okinawa sits outside the interconnected grid
 * the auction covers, so it has no clearing price.
 */
export const CAPACITY_AREAS: { key: AreaKey; en: string; ja: string }[] = [
  { key: 'hokkaido', en: 'Hokkaido', ja: '北海道' },
  { key: 'tohoku', en: 'Tohoku', ja: '東北' },
  { key: 'tepco', en: 'Tokyo', ja: '東京' },
  { key: 'chubu', en: 'Chubu', ja: '中部' },
  { key: 'hokuriku', en: 'Hokuriku', ja: '北陸' },
  { key: 'kansai', en: 'Kansai', ja: '関西' },
  { key: 'chugoku', en: 'Chugoku', ja: '中国' },
  { key: 'shikoku', en: 'Shikoku', ja: '四国' },
  { key: 'kyushu', en: 'Kyushu', ja: '九州' },
]

export interface MaRow {
  fy: string
  held: string
  /** OCCTO's national average unit price 総平均単価 (after 経過措置), formatted. */
  natl: string
  /**
   * Clearing price per OCCTO area, ¥/kW·year. The auction splits wherever an
   * interconnector binds, so the set of areas sharing a price differs every
   * year — hence a per-area map rather than fixed Hokkaido/Kyushu columns.
   */
  areas: Partial<Record<AreaKey, number>>
  proc: string
  ach: number
  /** OCCTO source URL for this year's figures (live data only). */
  source?: string
}

const px = (...v: number[]): Partial<Record<AreaKey, number>> =>
  Object.fromEntries(CAPACITY_AREAS.map((a, i) => [a.key, v[i]]))

export const maData: MaRow[] = [
  { fy: 'FY2024', held: 'Sep 2020', natl: '¥9,534', areas: px(14137, 14137, 14137, 14137, 14137, 14137, 14137, 14137, 14137), proc: '167.7 GW', ach: 97 },
  { fy: 'FY2025', held: 'Dec 2021', natl: '¥3,109', areas: px(5242, 3495, 3495, 3495, 3495, 3495, 3495, 3495, 5242), proc: '165.3 GW', ach: 93 },
  { fy: 'FY2026', held: 'Jan 2023', natl: '¥5,226', areas: px(8749, 5833, 5834, 5832, 5832, 5832, 5832, 5832, 8748), proc: '162.7 GW', ach: 92 },
  { fy: 'FY2027', held: 'Jan 2024', natl: '¥7,847', areas: px(13287, 9044, 9555, 7823, 7638, 7638, 7638, 7638, 11457), proc: '167.4 GW', ach: 98 },
  { fy: 'FY2028', held: 'Jan 2025', natl: '¥11,134', areas: px(14812, 14812, 14812, 10280, 8785, 8785, 8785, 8785, 13177), proc: '166.2 GW', ach: 97 },
  { fy: 'FY2029', held: 'Jan 2026', natl: '¥13,303', areas: px(14972, 15111, 15111, 12388, 12388, 12388, 12388, 12388, 15112), proc: '166.1 GW', ach: 96 },
]

export interface LtdaRow {
  key: string
  en: string
  ja: string
  r1: string
  r2: string
  r3: string
  cum: string
  share: number
  /** Awarded kW and plant count per round (rounds 1, 2, 3). */
  kw: number[]
  plants: number[]
  c: string
  cd: string
}

/** One LTDA round: OCCTO's results release (`capacity_data.ltda_round_rows`). */
export interface LtdaRound {
  round: number
  bid_year: number
  published: string
  kw: number
  plants: number
  /** OCCTO results PDF and its per-plant appendix (live data only). */
  source?: string
  plants_pdf?: string
}

// The curated OCCTO figures (`capacity_data.LTDA_TECH`), shown while the snapshot loads.
export const ltdaData: LtdaRow[] = [
  { key: 'lng', en: 'LNG (decarb-ready)', ja: 'LNG（脱炭素化前提）', r1: '5.76', r2: '1.31', r3: '3.04', cum: '10.11', share: 43, kw: [5756320, 1314644, 3037866], plants: [10, 4, 4], c: '#E9C46A', cd: '#E9C46A' },
  { key: 'nuclear', en: 'Nuclear', ja: '原子力', r1: '1.32', r2: '3.15', r3: '1.94', cum: '6.41', share: 27, kw: [1315707, 3153107, 1939123], plants: [1, 3, 2], c: '#7B2D8E', cd: '#C77BD8' },
  { key: 'battery', en: 'Battery storage', ja: '蓄電池', r1: '1.09', r2: '1.37', r3: '1.25', cum: '3.71', share: 16, kw: [1092076, 1370036, 1251127], plants: [30, 27, 19], c: '#00A5CF', cd: '#1FB6DC' },
  { key: 'h2nh3', en: 'Hydrogen · Ammonia', ja: '水素・アンモニア', r1: '0.83', r2: '0.09', r3: '0.52', cum: '1.44', share: 6, kw: [825582, 94600, 516687], plants: [6, 1, 4], c: '#2A9D8F', cd: '#2A9D8F' },
  { key: 'pumped', en: 'Pumped hydro', ja: '揚水', r1: '0.58', r2: '0.36', r3: '0.45', cum: '1.39', share: 6, kw: [576937, 360646, 453439], plants: [3, 2, 2], c: '#4A6FA5', cd: '#7C9CD1' },
  { key: 'biomass', en: 'Biomass', ja: 'バイオマス', r1: '0.20', r2: '—', r3: '0.10', cum: '0.30', share: 1, kw: [199258, 0, 100926], plants: [2, 0, 1], c: '#8AB17D', cd: '#8AB17D' },
  { key: 'hydro', en: 'Conventional hydro', ja: '一般水力', r1: '—', r2: '0.05', r3: '—', cum: '0.05', share: 0, kw: [0, 51800, 0], plants: [0, 1, 0], c: '#B4BCC9', cd: '#5D6B85' },
]

export const ltdaRounds: LtdaRound[] = [
  { round: 1, bid_year: 2023, published: '2024-04-26', kw: 9765880, plants: 52 },
  { round: 2, bid_year: 2024, published: '2025-04-28', kw: 6344833, plants: 38 },
  { round: 3, bid_year: 2025, published: '2026-05-13', kw: 7299168, plants: 32 },
]

