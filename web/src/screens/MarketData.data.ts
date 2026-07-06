// Fixture data + generators ported from screens/market-data.html DCLogic.

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
  c: string
  cd: string
}

export interface IcDef {
  key: string
  ja: string
  en: string
  from: string
  to: string
  cap: number
  base: number
  sol: number
  eve: number
  ph: number
  short: string
}

export interface DrDef {
  key: 'jkm' | 'ncl' | 'fx'
  en: string
  ja: string
  unit: string
  src: string
  color: string
  corr: number
  dec: number
}

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
  { jp: '一次調整力', en: 'Primary (FCR)', price: '6.84', proc: '1,208', off: '1,542', ach: 78, c: '#7B2D8E', cd: '#C77BD8' },
  { jp: '二次調整力①', en: 'Secondary I', price: '7.12', proc: '1,046', off: '1,180', ach: 89, c: '#E76F51', cd: '#E76F51' },
  { jp: '二次調整力②', en: 'Secondary II', price: '5.63', proc: '892', off: '1,004', ach: 89, c: '#2A9D8F', cd: '#2A9D8F' },
  { jp: '三次調整力①', en: 'Tertiary I', price: '4.98', proc: '2,315', off: '2,780', ach: 83, c: '#4A6FA5', cd: '#7C9CD1' },
  { jp: '三次調整力②', en: 'Tertiary II', price: '3.41', proc: '3,860', off: '4,510', ach: 86, c: '#00A5CF', cd: '#1FB6DC' },
]

export const icDefs: IcDef[] = [
  { key: 'hh', ja: '北海道本州間連系設備', en: 'Hokkaido–Honshu HVDC', from: 'hokkaido', to: 'tohoku', cap: 900, base: 0.5, sol: 0.28, eve: 0.3, ph: 0.5, short: 'Hokkaido–Tohoku 北本' },
  { key: 'st', ja: '相馬双葉幹線ほか', en: 'Tohoku–Tokyo', from: 'tohoku', to: 'tepco', cap: 6050, base: 0.68, sol: 0.3, eve: 0.22, ph: 1.2, short: 'Tohoku–Tokyo 相双' },
  { key: 'fc', ja: '周波数変換設備（FC）', en: 'Tokyo–Chubu 50/60Hz FC', from: 'chubu', to: 'tepco', cap: 2100, base: 0.82, sol: 0.28, eve: 0.18, ph: 2.0, short: 'FC Tokyo–Chubu 周波数変換' },
  { key: 'kc', ja: '三重東近江線ほか', en: 'Kansai–Chubu', from: 'kansai', to: 'chubu', cap: 2500, base: 0.4, sol: 0.22, eve: 0.18, ph: 2.8, short: 'Kansai–Chubu' },
  { key: 'hc', ja: '南福光連系所', en: 'Hokuriku–Chubu', from: 'hokuriku', to: 'chubu', cap: 300, base: 0.3, sol: 0.14, eve: 0.1, ph: 3.4, short: 'Hokuriku–Chubu 南福光' },
  { key: 'hk', ja: '越前嶺南線ほか', en: 'Hokuriku–Kansai', from: 'hokuriku', to: 'kansai', cap: 1900, base: 0.34, sol: 0.15, eve: 0.12, ph: 4.1, short: 'Hokuriku–Kansai' },
  { key: 'ck', ja: '山崎智頭線ほか', en: 'Chugoku–Kansai', from: 'chugoku', to: 'kansai', cap: 4160, base: 0.46, sol: 0.2, eve: 0.16, ph: 4.9, short: 'Chugoku–Kansai' },
  { key: 'sk', ja: '阿南紀北直流幹線', en: 'Shikoku–Kansai HVDC', from: 'shikoku', to: 'kansai', cap: 1400, base: 0.56, sol: 0.22, eve: 0.14, ph: 5.6, short: 'Shikoku–Kansai 阿南紀北' },
  { key: 'cs', ja: '本四連系線', en: 'Chugoku–Shikoku', from: 'chugoku', to: 'shikoku', cap: 1200, base: 0.18, sol: 0.11, eve: 0.08, ph: 0.9, short: 'Chugoku–Shikoku 本四' },
  { key: 'kq', ja: '関門連系線', en: 'Kyushu–Chugoku (Kanmon)', from: 'kyushu', to: 'chugoku', cap: 2780, base: 0.72, sol: 0.42, eve: 0.1, ph: 1.6, short: 'Kyushu–Chugoku 関門' },
]

export const icUtil: number[][] = icDefs.map((l) =>
  mk((i, t) =>
    Math.min(
      1,
      Math.max(0.04, l.base + l.sol * G(t, 13, 4.5) + l.eve * G(t, 18.6, 4) + 0.02 * Math.sin(i * 0.9 + l.ph)),
    ),
  ),
)

export const drv = {
  spot: Array.from(
    { length: 365 },
    (_, d) => 11 + 1.8 * Math.sin(d / 58) + 0.5 * Math.sin(d / 72 + 1) + 1.1 * Math.sin(d / 9.7 + 2) + 0.6 * Math.sin(d / 3.3),
  ),
  jkm: Array.from(
    { length: 365 },
    (_, d) => 11.9 + 1.6 * Math.sin(d / 72 + 1) + 0.8 * Math.sin(d / 13 + 0.5) + 0.35 * Math.sin(d / 4.1),
  ),
  ncl: Array.from(
    { length: 365 },
    (_, d) => 138 + 9 * Math.sin(d / 85 + 2.2) + 4 * Math.sin(d / 16 + 1.1) + 1.8 * Math.sin(d / 5.2),
  ),
  fx: Array.from(
    { length: 365 },
    (_, d) => 155.5 + 3.2 * Math.sin(d / 95 + 0.4) + 1.2 * Math.sin(d / 21 + 2.4) + 0.5 * Math.sin(d / 6.3),
  ),
}

export const drDefs: DrDef[] = [
  { key: 'jkm', en: 'JKM LNG', ja: 'JKM（LNG）', unit: '$/MMBtu', src: 'ICE · yfinance', color: '#E76F51', corr: 0.72, dec: 2 },
  { key: 'ncl', en: 'Newcastle coal', ja: 'NC石炭', unit: '$/t', src: 'ICE · yfinance', color: '#B08968', corr: 0.41, dec: 1 },
  { key: 'fx', en: 'USD/JPY', ja: 'ドル円', unit: '', src: 'TTM · yfinance', color: '#8AB17D', corr: 0.33, dec: 2 },
]

export const gaussian = G
