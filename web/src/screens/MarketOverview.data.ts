// Fixture data + chart geometry ported verbatim from screens/market-overview.html
// (the DCLogic constructor + renderVals math). All numbers/labels/colors match.

export interface AreaDef {
  key: string
  en: string
  ja: string
  color: string
  dk?: string
  off: number
  ph: number
  solar?: number
}

export interface Meeting {
  en: string
  ja: string
  tier: 'METI' | 'OCCTO' | 'EGC'
  no: number
  m: number
  day: number
  tori?: boolean
  followed?: boolean
  watch?: boolean
  sched?: boolean
  done: boolean
  sEn?: string
  sJa?: string
  /** Real ISO meeting date (YYYY-MM-DD) when known — set by the live adapter.
   * Fixtures use m/day (year 2026); live rows carry the true date. */
  date?: string
  /** True when `date` is the committee's real published meeting date (not a
   * fallback timestamp). Only real-dated meetings are placed on the timeline. */
  dateReal?: boolean
  /** Tracked-committee key this meeting belongs to (for follow state); null for
   * an unmatched scheduled meeting. */
  key?: string
}

export interface FreshRow {
  en: string
  ja: string
  subEn: string
  subJa: string
  v: string
  ok: boolean
  delayed?: boolean
}

// ---- synthetic price series (48 half-hour slots) ----
const G = (t: number, c: number, w: number) => Math.exp(-((t - c) * (t - c)) / w)
const mk = (f: (i: number, t: number) => number): number[] =>
  Array.from({ length: 48 }, (_, i) => f(i, i / 2))

export const today: number[] = mk(
  (i, t) =>
    9.6 +
    3.1 * G(t, 8.1, 2.4) -
    4.2 * G(t, 12.6, 7.5) +
    12.1 * G(t, 18.7, 2.9) +
    0.38 * Math.sin(i * 1.63) +
    0.24 * Math.sin(i * 0.71 + 2.1),
)
export const yday: number[] = mk(
  (i, t) =>
    10.05 +
    2.8 * G(t, 8.3, 2.6) -
    3.4 * G(t, 12.4, 7.0) +
    10.4 * G(t, 18.9, 3.2) +
    0.42 * Math.sin(i * 1.31 + 1.2) +
    0.2 * Math.sin(i * 0.57 + 0.4),
)
export const avg7: number[] = mk(
  (i, t) =>
    9.85 +
    2.9 * G(t, 8.2, 2.5) -
    3.7 * G(t, 12.5, 7.2) +
    11.1 * G(t, 18.8, 3.0) +
    0.15 * Math.sin(i * 0.9),
)

export const areaDefs: AreaDef[] = [
  { key: 'tepco', en: 'Tokyo', ja: '東京', color: '#7B2D8E', dk: '#C77BD8', off: 1.32, ph: 0.4 },
  { key: 'hokkaido', en: 'Hokkaido', ja: '北海道', color: '#1B2A4A', dk: '#8FA7D9', off: 0.85, ph: 1.1 },
  { key: 'kansai', en: 'Kansai', ja: '関西', color: '#E76F51', off: 0.55, ph: 2.2 },
  { key: 'chubu', en: 'Chubu', ja: '中部', color: '#2A9D8F', off: 0.38, ph: 3.0 },
  { key: 'tohoku', en: 'Tohoku', ja: '東北', color: '#00A5CF', off: -0.12, ph: 3.9 },
  { key: 'hokuriku', en: 'Hokuriku', ja: '北陸', color: '#4A6FA5', dk: '#7C9CD1', off: -0.35, ph: 4.7 },
  { key: 'chugoku', en: 'Chugoku', ja: '中国', color: '#C1440E', dk: '#E8794B', off: 0.08, ph: 5.5 },
  { key: 'shikoku', en: 'Shikoku', ja: '四国', color: '#E9C46A', off: -0.22, ph: 0.9 },
  { key: 'kyushu', en: 'Kyushu', ja: '九州', color: '#8AB17D', off: -0.55, solar: -2.2, ph: 1.7 },
]

export interface Area extends AreaDef {
  series: number[]
}

export const areas: Area[] = areaDefs.map((a) => ({
  ...a,
  series: mk(
    (i, t) =>
      today[i] + a.off + (a.solar ? a.solar * G(t, 12.5, 6) : 0) + 0.18 * Math.sin(i * 0.83 + a.ph),
  ),
}))

// ---- chart geometry (viewBox 960x320, domain ¥4–24, plot x 46–944, y 14–290) ----
export const X = (i: number): number => 46 + (i / 47) * 898
export const Y = (v: number): number => 14 + (24 - Math.max(2, Math.min(25, v))) / 20 * 276

const r1 = (n: number) => Math.round(n * 10) / 10
const stepPath = (arr: number[]): string => {
  let d = 'M' + r1(X(0)) + ',' + r1(Y(arr[0]))
  for (let i = 1; i < 48; i++) d += 'H' + r1(X(i)) + 'V' + r1(Y(arr[i]))
  return d + 'H944'
}

export const paths = {
  today: stepPath(today),
  yday: stepPath(yday),
  avg7: stepPath(avg7),
  todayA: stepPath(today) + 'V290H46Z',
  ydayA: stepPath(yday) + 'V290H46Z',
  avg7A: stepPath(avg7) + 'V290H46Z',
}

export const meetings: Meeting[] = [
  {
    en: 'E&G Market Surveillance Commission',
    ja: '電力・ガス取引監視等委員会',
    tier: 'EGC',
    no: 58,
    m: 6,
    day: 24,
    tori: true,
    followed: true,
    done: true,
    sEn: 'Adopted the interim report on the wheeling-charge review; FY2027 tariff-reform framework now fixed.',
    sJa: '託送料金制度見直しの中間とりまとめを採択。FY2027の料金改革枠組みが確定。',
  },
  {
    en: 'E&G Basic Policy Subcommittee',
    ja: '電力・ガス基本政策小委員会',
    tier: 'METI',
    no: 84,
    m: 6,
    day: 27,
    followed: true,
    done: true,
    sEn: 'Debated capacity-market linkage for long-duration storage; secretariat to draft options for August.',
    sJa: '長期蓄電池の容量市場連携を審議。8月会合に向け事務局が選択肢を整理へ。',
  },
  {
    en: 'Mid- & Long-term Power Supply WG',
    ja: '中長期の供給力確保ワーキンググループ',
    tier: 'OCCTO',
    no: 12,
    m: 6,
    day: 19,
    watch: true,
    done: true,
    sEn: 'Reviewed LTDA auction parameters for FY2028; storage participation thresholds remain open.',
    sJa: 'FY2028長期脱炭素オークションの諸元を点検。蓄電池の参入閾値は継続審議。',
  },
  {
    en: 'Institutional Design Subcommittee',
    ja: '制度設計専門会合',
    tier: 'EGC',
    no: 91,
    m: 6,
    day: 13,
    followed: true,
    done: true,
    sEn: 'Discussed imbalance-penalty recalibration and EPRX bidding-guideline amendments for tertiary products.',
    sJa: 'インバランス料金の再調整と三次調整力の入札ガイドライン改定を議論。',
  },
  {
    en: 'Balancing Market Review Subcommittee',
    ja: '需給調整市場検討小委員会',
    tier: 'OCCTO',
    no: 47,
    m: 6,
    day: 10,
    watch: true,
    done: false,
  },
  {
    en: 'Renewable Integration & Next-gen Grid',
    ja: '再エネ大量導入・次世代電力NW小委員会',
    tier: 'METI',
    no: 63,
    m: 6,
    day: 5,
    done: true,
    sEn: 'Progress check on non-firm connection expansion and curtailment forecasting accuracy.',
    sJa: 'ノンファーム接続拡大と出力制御予測の精度を確認。',
  },
]

export const upcomingMeetings: Meeting[] = [
  {
    en: 'System Review WG',
    ja: '制度検討作業部会',
    tier: 'METI',
    no: 61,
    m: 7,
    day: 10,
    followed: true,
    sched: true,
    done: true,
    sEn: 'Agenda: simultaneous-market detailed design — settlement & bidding interactions (資料 published).',
    sJa: '議題：同時市場の詳細設計 — 精算・入札の相互作用（資料公表済み）。',
  },
  {
    en: 'Balancing Market Review Subcommittee',
    ja: '需給調整市場検討小委員会',
    tier: 'OCCTO',
    no: 48,
    m: 7,
    day: 17,
    watch: true,
    sched: true,
    done: true,
    sEn: 'Agenda: FY2026 procurement review & tertiary② shortfall countermeasures.',
    sJa: '議題：FY2026調達実績の点検と三次②不足対策。',
  },
  {
    en: 'E&G Market Surveillance Commission',
    ja: '電力・ガス取引監視等委員会',
    tier: 'EGC',
    no: 59,
    m: 7,
    day: 22,
    followed: true,
    sched: true,
    done: true,
    sEn: 'Agenda: final wheeling-charge report put to public comment; retail-market monitoring update.',
    sJa: '議題：託送料金最終報告案のパブコメ付議、小売市場モニタリング報告。',
  },
  {
    en: 'E&G Basic Policy Subcommittee',
    ja: '電力・ガス基本政策小委員会',
    tier: 'METI',
    no: 85,
    m: 8,
    day: 5,
    followed: true,
    sched: true,
    done: true,
    sEn: 'Agenda: 3 design options for long-duration storage capacity-market linkage.',
    sJa: '議題：長期蓄電池の容量市場連携に関する3つの設計オプション。',
  },
]

export const freshData: FreshRow[] = [
  { en: 'JEPX spot', ja: 'JEPXスポット', subEn: 'day-ahead · daily', subJa: '前日約定', v: '2026-07-02', ok: true },
  { en: 'Area prices', ja: 'エリア価格', subEn: '', subJa: '', v: '2026-07-02', ok: true },
  { en: 'Balancing (EPRX)', ja: '需給調整市場', subEn: 'FY2025+ · daily', subJa: '', v: '2026-07-01', ok: true },
  { en: 'Interconnectors', ja: '連系線', subEn: '', subJa: '', v: '2026-07-01', ok: true },
  { en: 'Fuels / FX', ja: '燃料・為替', subEn: 'yfinance close', subJa: '', v: '2026-07-01', ok: true },
  { en: 'Auction results', ja: 'オークション結果', subEn: 'OCCTO · per event', subJa: '', v: '2026-06-27', ok: true },
  { en: 'Policy detection', ja: '政策検知', subEn: '', subJa: '', v: '07-02 06:10', ok: true },
  { en: 'Policy summaries', ja: '政策要約', subEn: 'lags days', subJa: '', v: '2026-06-28', ok: false, delayed: true },
]

export const MO = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export const enShort: Record<number, string> = { 61: 'System Review WG', 48: 'Balancing Review', 59: 'EGMSC', 85: 'Basic Policy' }
export const jaShort: Record<number, string> = { 61: '制度検討WG', 48: '需給調整小委', 59: '監視等委', 85: '基本政策小委' }
export const calRows: Array<'top' | 'bottom'> = ['top', 'bottom', 'top', 'top']
