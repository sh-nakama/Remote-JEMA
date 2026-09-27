// Fixture data + generators ported from screens/market-data.html DCLogic.
import { gaussian as G, slots as mk, today } from '../lib/fixtures'

export interface AreaDef {
  key: string
  en: string
  ja: string
  off: number
  ph: number
  peak: number
  solarF: number
  solar?: number
}

export interface Area extends AreaDef {
  intraday: number[]
  dailyAvg: number[]
  dailyMax: number[]
  dailyMin: number[]
}

export interface BalProduct {
  jp: string
  en: string
  price: string
  proc: string
  off: string
  ach: number
  short: number
  c: string
  cd: string
}

/** The seven physically distinct interconnectors (keys match `export_web.PAIR_TO_IC`). The
 *  Chubu/Hokuriku/Kansai lines are published as combined zones and have no entry here. */
export interface IcDef {
  key: string
  ja: string
  en: string
  short: string
}

/** A sample day of one EPRX pair's reservations (loading/fallback state only). */
export interface IcSample {
  pair: string
  key: string | null
  from: string[]
  to: string[]
  limit: number
  base: number
  sol: number
  eve: number
  ph: number
}

export interface DrDef {
  key: 'lng' | 'brent' | 'fx'
  en: string
  ja: string
  unit: string
  src: string
  color: string
  corr: number
  dec: number
}

export const areaDefs: AreaDef[] = [
  { key: 'hokkaido', en: 'Hokkaido', ja: '北海道', off: 0.85, ph: 1.1, peak: 5210, solarF: 0.55 },
  { key: 'tohoku', en: 'Tohoku', ja: '東北', off: -0.12, ph: 3.9, peak: 14890, solarF: 0.8 },
  { key: 'tepco', en: 'Tokyo', ja: '東京', off: 1.32, ph: 0.4, peak: 55340, solarF: 0.7 },
  { key: 'chubu', en: 'Chubu', ja: '中部', off: 0.38, ph: 3.0, peak: 26120, solarF: 0.9 },
  { key: 'hokuriku', en: 'Hokuriku', ja: '北陸', off: -0.35, ph: 4.7, peak: 5230, solarF: 0.7 },
  { key: 'kansai', en: 'Kansai', ja: '関西', off: 0.55, ph: 2.2, peak: 28460, solarF: 0.8 },
  { key: 'chugoku', en: 'Chugoku', ja: '中国', off: 0.08, ph: 5.5, peak: 11020, solarF: 1.0 },
  { key: 'shikoku', en: 'Shikoku', ja: '四国', off: -0.22, ph: 0.9, peak: 5060, solarF: 1.2 },
  { key: 'kyushu', en: 'Kyushu', ja: '九州', off: -0.55, solar: -2.2, ph: 1.7, peak: 16210, solarF: 1.5 },
]

export const areas: Area[] = areaDefs.map((a) => ({
  ...a,
  intraday: mk(
    (i, t) =>
      today[i] +
      a.off +
      (a.solar ? a.solar * G(t, 12.5, 6) : 0) +
      0.18 * Math.sin(i * 0.83 + a.ph),
  ),
  dailyAvg: Array.from(
    { length: 365 },
    (_, d) =>
      11 +
      a.off +
      1.8 * Math.sin(d / 58) +
      1.1 * Math.sin(d / 9.7 + a.ph) +
      0.7 * Math.sin(d / 3.1 + a.ph * 2),
  ),
  dailyMax: Array.from(
    { length: 365 },
    (_, d) =>
      11 +
      a.off +
      1.8 * Math.sin(d / 58) +
      1.1 * Math.sin(d / 9.7 + a.ph) +
      5.6 +
      2.6 * Math.abs(Math.sin(d / 7.3 + a.ph)),
  ),
  dailyMin: Array.from({ length: 365 }, (_, d) =>
    Math.max(
      0.05,
      11 +
        a.off +
        1.8 * Math.sin(d / 58) +
        1.1 * Math.sin(d / 9.7 + a.ph) -
        4.3 -
        1.7 * Math.abs(Math.sin(d / 11 + a.ph)),
    ),
  ),
}))

export const balProducts: BalProduct[] = [
  { jp: '一次調整力', en: 'Primary (FCR)', price: '6.84', proc: '1,208', off: '1,542', ach: 78, short: 3, c: '#7B2D8E', cd: '#C77BD8' },
  { jp: '二次調整力①', en: 'Secondary I', price: '7.12', proc: '1,046', off: '1,180', ach: 89, short: 0, c: '#E76F51', cd: '#E76F51' },
  { jp: '二次調整力②', en: 'Secondary II', price: '5.63', proc: '892', off: '1,004', ach: 89, short: 0, c: '#2A9D8F', cd: '#2A9D8F' },
  { jp: '三次調整力①', en: 'Tertiary I', price: '4.98', proc: '2,315', off: '2,780', ach: 83, short: 1, c: '#4A6FA5', cd: '#7C9CD1' },
  { jp: '三次調整力②', en: 'Tertiary II', price: '3.41', proc: '3,860', off: '4,510', ach: 86, short: 3, c: '#00A5CF', cd: '#1FB6DC' },
]

export const icDefs: IcDef[] = [
  { key: 'hh', ja: '北海道本州間連系設備', en: 'Hokkaido–Honshu HVDC', short: 'Hokkaido–Tohoku 北本' },
  { key: 'st', ja: '相馬双葉幹線ほか', en: 'Tohoku–Tokyo', short: 'Tohoku–Tokyo 相双' },
  { key: 'fc', ja: '周波数変換設備（FC）', en: 'Tokyo–Chubu 50/60Hz FC', short: 'FC Tokyo–Chubu 周波数変換' },
  { key: 'ck', ja: '山崎智頭線ほか', en: 'Chugoku–Kansai', short: 'Chugoku–Kansai' },
  { key: 'sk', ja: '阿南紀北直流幹線', en: 'Shikoku–Kansai HVDC', short: 'Shikoku–Kansai 阿南紀北' },
  { key: 'cs', ja: '本四連系線', en: 'Chugoku–Shikoku', short: 'Chugoku–Shikoku 本四' },
  { key: 'kq', ja: '関門連系線', en: 'Kyushu–Chugoku (Kanmon)', short: 'Kyushu–Chugoku 関門' },
]

export const icSample: IcSample[] = [
  { pair: 'Hokkaido → Tohoku', key: 'hh', from: ['hokkaido'], to: ['tohoku'], limit: 75, base: 0.5, sol: 0.28, eve: 0.3, ph: 0.5 },
  { pair: 'Tohoku → Tokyo', key: 'st', from: ['tohoku'], to: ['tepco'], limit: 2300, base: 0.08, sol: 0.1, eve: 0.06, ph: 1.2 },
  { pair: 'Tokyo → Chubu', key: 'fc', from: ['tepco'], to: ['chubu'], limit: 900, base: 0.42, sol: 0.24, eve: 0.18, ph: 2.0 },
  { pair: 'Chubu → Hokuriku-Kansai', key: null, from: ['chubu'], to: ['hokuriku', 'kansai'], limit: 2650, base: 0.04, sol: 0.03, eve: 0.02, ph: 2.8 },
  { pair: 'Chubu-Hokuriku → Kansai', key: null, from: ['chubu', 'hokuriku'], to: ['kansai'], limit: 2650, base: 0.05, sol: 0.03, eve: 0.02, ph: 3.4 },
  { pair: 'Chubu-Kansai → Hokuriku', key: null, from: ['chubu', 'kansai'], to: ['hokuriku'], limit: 1300, base: 0.02, sol: 0.01, eve: 0.01, ph: 4.1 },
  { pair: 'Kansai → Chugoku', key: 'ck', from: ['kansai'], to: ['chugoku'], limit: 4500, base: 0.08, sol: 0.03, eve: 0.02, ph: 4.9 },
  { pair: 'Kansai → Shikoku', key: 'sk', from: ['kansai'], to: ['shikoku'], limit: 0, base: 0, sol: 0, eve: 0, ph: 5.6 },
  { pair: 'Chugoku → Shikoku', key: 'cs', from: ['chugoku'], to: ['shikoku'], limit: 1200, base: 0.01, sol: 0.01, eve: 0.0, ph: 0.9 },
  { pair: 'Chugoku → Kyushu', key: 'kq', from: ['chugoku'], to: ['kyushu'], limit: 915, base: 0.36, sol: 0.18, eve: 0.1, ph: 1.6 },
]

/** Sample per-slot share of each pair's limit (0–1), aligned to `icSample`. */
export const icSampleUtil: number[][] = icSample.map((l) =>
  mk((i, t) =>
    l.limit > 0
      ? Math.min(1, Math.max(0, l.base + l.sol * G(t, 13, 4.5) + l.eve * G(t, 18.6, 4) + 0.02 * Math.sin(i * 0.9 + l.ph)))
      : 0,
  ),
)

export const drv = {
  spot: Array.from(
    { length: 365 },
    (_, d) => 11 + 1.8 * Math.sin(d / 58) + 0.5 * Math.sin(d / 72 + 1) + 1.1 * Math.sin(d / 9.7 + 2) + 0.6 * Math.sin(d / 3.3),
  ),
  lng: Array.from(
    { length: 365 },
    (_, d) => 11.9 + 1.6 * Math.sin(d / 72 + 1) + 0.8 * Math.sin(d / 13 + 0.5) + 0.35 * Math.sin(d / 4.1),
  ),
  brent: Array.from(
    { length: 365 },
    (_, d) => 74 + 5 * Math.sin(d / 85 + 2.2) + 2.2 * Math.sin(d / 16 + 1.1) + 1 * Math.sin(d / 5.2),
  ),
  fx: Array.from(
    { length: 365 },
    (_, d) => 155.5 + 3.2 * Math.sin(d / 95 + 0.4) + 1.2 * Math.sin(d / 21 + 2.4) + 0.5 * Math.sin(d / 6.3),
  ),
}

export const drDefs: DrDef[] = [
  { key: 'lng', en: 'JKM LNG', ja: 'JKM（LNG）', unit: '$/MMBtu', src: 'JKM=F futures · yfinance', color: '#E76F51', corr: 0.72, dec: 2 },
  { key: 'brent', en: 'Brent crude', ja: 'ブレント原油', unit: '$/bbl', src: 'BZ=F futures · yfinance', color: '#B08968', corr: 0.41, dec: 2 },
  { key: 'fx', en: 'USD/JPY', ja: 'ドル円', unit: '', src: 'JPY=X spot · yfinance', color: '#8AB17D', corr: 0.33, dec: 2 },
]

