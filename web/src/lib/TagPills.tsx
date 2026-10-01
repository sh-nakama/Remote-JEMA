import { s, press } from './style'
import { tagLabel, type TagVocab } from './policyTags'

/** A row of topic pills. Clickable (toggle the Topic filter) when `onPick` is given;
 * `active` marks the ones currently selected. `max` collapses the rest into "+N" so a
 * feed row stays one line. Renders nothing for no tags — an untagged row is just quiet. */
export function TagPills({
  keys,
  vocab,
  lang,
  active = [],
  onPick,
  max,
}: {
  keys: readonly string[] | undefined
  vocab: TagVocab
  lang: 'ja' | 'en'
  active?: readonly string[]
  onPick?: (key: string) => void
  max?: number
}) {
  if (!keys || !keys.length) return null
  const shown = max && keys.length > max ? keys.slice(0, max) : keys
  const rest = keys.length - shown.length
  return (
    <span style={s('display:inline-flex;flex-wrap:wrap;gap:5px;align-items:center;min-width:0')}>
      {shown.map((k) => {
        const on = active.includes(k)
        const style = s(
          `font-size:10px;font-weight:600;border-radius:999px;padding:1px 8px;white-space:nowrap;` +
            (on ? 'background:var(--acBadge);color:#FFFFFF' : 'background:var(--bg2);color:var(--tx2)') +
            (onPick ? ';cursor:pointer' : ''),
        )
        const label = tagLabel(vocab, k, lang)
        return onPick ? (
          <span
            key={k}
            style={style}
            title={lang === 'ja' ? `「${label}」で絞り込み` : `Filter by ${label}`}
            {...press((e) => {
              e.stopPropagation()
              onPick(k)
            }, on)}
          >
            {label}
          </span>
        ) : (
          <span key={k} style={style}>
            {label}
          </span>
        )
      })}
      {rest > 0 && <span style={s('font-size:10px;font-weight:600;color:var(--mut)')}>+{rest}</span>}
    </span>
  )
}
