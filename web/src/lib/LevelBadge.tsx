// The safety badge shared by the Commands pane and the guide. Colour is never the only signal:
// the word is always there.
import { s } from './style'
import type { Lang } from './app'
import type { Level } from './commands'

const LEVEL: Record<Level, { en: string; ja: string; style: string }> = {
  safe: { en: 'SAFE', ja: '安全', style: 'background:var(--upBg);color:var(--up)' },
  writes: { en: 'WRITES LOCAL DATA', ja: 'ローカル更新', style: 'background:var(--warnBg);color:var(--warnTx)' },
  dangerous: { en: 'DANGEROUS', ja: '危険', style: 'background:var(--dn);color:#FFFFFF' },
}

export const BADGE = 'font-size:9.5px;font-weight:700;letter-spacing:.04em;border-radius:6px;padding:1px 7px;white-space:nowrap'

export function LevelBadge({ level, lang }: { level: Level; lang: Lang }) {
  const l = LEVEL[level]
  return <span style={s(`${BADGE};${l.style}`)}>{lang === 'ja' ? l.ja : l.en}</span>
}
