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
  en: string
  ja: string
  r1: string
  r2: string
  r3: string
  cum: string
  share: number
  c: string
  cd: string
}

export const ltdaData: LtdaRow[] = [
  { en: 'Battery storage', ja: '蓄電池', r1: '1.10', r2: '1.64', r3: '1.68', cum: '4.42', share: 31, c: '#00A5CF', cd: '#1FB6DC' },
  { en: 'Pumped hydro', ja: '揚水', r1: '0.57', r2: '0.30', r3: '0.42', cum: '1.29', share: 9, c: '#4A6FA5', cd: '#7C9CD1' },
  { en: 'LNG (decarb-ready)', ja: 'LNG（脱炭素化前提）', r1: '2.20', r2: '2.55', r3: '2.30', cum: '7.05', share: 50, c: '#E9C46A', cd: '#E9C46A' },
  { en: 'Hydrogen · Ammonia', ja: '水素・アンモニア', r1: '0.14', r2: '0.36', r3: '0.62', cum: '1.12', share: 8, c: '#2A9D8F', cd: '#2A9D8F' },
  { en: 'Other (biomass etc.)', ja: 'その他', r1: '—', r2: '—', r3: '0.22', cum: '0.22', share: 2, c: '#B4BCC9', cd: '#5D6B85' },
]

export interface PolRow {
  en: string
  ja: string
  tier: 'METI' | 'OCCTO'
  no: number
  m: number
  day: number
  sched?: boolean
  sEn: string
  sJa: string
}

export const polData: PolRow[] = [
  {
    en: 'E&G Basic Policy Subcommittee', ja: '電力・ガス基本政策小委員会', tier: 'METI', no: 84, m: 6, day: 27,
    sEn: 'Debated capacity-market linkage for long-duration storage; secretariat to draft options for August.',
    sJa: '長期蓄電池の容量市場連携を審議。8月会合に向け事務局が選択肢を整理へ。',
  },
  {
    en: 'Mid- & Long-term Power Supply WG', ja: '中長期の供給力確保ワーキンググループ', tier: 'OCCTO', no: 12, m: 6, day: 19,
    sEn: 'Reviewed LTDA auction parameters for FY2028; storage participation thresholds remain open.',
    sJa: 'FY2028長期脱炭素オークションの諸元を点検。蓄電池の参入閾値は継続審議。',
  },
  {
    en: 'E&G Basic Policy Subcommittee', ja: '電力・ガス基本政策小委員会', tier: 'METI', no: 85, m: 8, day: 5, sched: true,
    sEn: 'Agenda: 3 design options for long-duration storage capacity-market linkage.',
    sJa: '議題：長期蓄電池の容量市場連携に関する3つの設計オプション。',
  },
]

export const MONTHS = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
