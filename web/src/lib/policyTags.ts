// Topic tags for the Policy Deep Dive. The vocabulary (keys, groups, JA/EN labels) is
// exported by the backend as `tagVocab` beside the committees, so there is one copy of
// it — see src/repower/policy/tags.py. Logic only here; the pill component is in TagPills.tsx.

export interface TagDef {
  key: string
  group: string
  ja: string
  en: string
}

export interface TagGroup {
  key: string
  ja: string
  en: string
}

export interface TagVocab {
  groups: TagGroup[]
  tags: TagDef[]
}

/** What a snapshot older than the tags feature (no `tagVocab`) reads as: no Topic filter. */
export const EMPTY_VOCAB: TagVocab = { groups: [], tags: [] }

/** True when `tags` carries at least one of the selected topics. Selecting nothing matches everything. */
export function matchesTags(selected: readonly string[], tags: readonly string[] | undefined): boolean {
  if (!selected.length) return true
  if (!tags || !tags.length) return false
  return selected.some((k) => tags.includes(k))
}

/** The selection with `key` flipped on or off (a new array; order = order selected). */
export function toggleTag(selected: readonly string[], key: string): string[] {
  return selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]
}

/** How many of `items` carry each tag. */
export function tagCounts(items: ReadonlyArray<{ tags?: readonly string[] }>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const it of items) for (const k of new Set(it.tags ?? [])) out[k] = (out[k] ?? 0) + 1
  return out
}

/** Display label for a tag key. A key the vocabulary no longer has falls back to the key itself. */
export function tagLabel(vocab: TagVocab, key: string, lang: 'ja' | 'en'): string {
  const t = vocab.tags.find((x) => x.key === key)
  return t ? t[lang] : key
}

/** The vocabulary grouped for the dropdown, in vocabulary order, dropping empty groups. */
export function tagsByGroup(vocab: TagVocab): Array<{ group: TagGroup; tags: TagDef[] }> {
  return vocab.groups
    .map((group) => ({ group, tags: vocab.tags.filter((t) => t.group === group.key) }))
    .filter((g) => g.tags.length > 0)
}

/** Committee keys with at least one meeting matching the selection. A committee whose own
 * (standing-mandate) tags are still empty — it takes recurring meetings to roll one up —
 * should still surface under a topic one of its meetings is about. */
export function committeesWithTopicMeetings(
  selected: readonly string[],
  meetings: ReadonlyArray<{ com?: string; tags?: readonly string[] }>,
): Set<string> {
  const out = new Set<string>()
  if (!selected.length) return out
  for (const m of meetings) if (m.com && matchesTags(selected, m.tags)) out.add(m.com)
  return out
}

/** How much of a committee's recent work one topic is (see `tagCoverage` in the export):
 * `score` is graded 0-1 (recency-weighted, shrunk on thin evidence); `n` of `of` are the
 * plain meeting counts behind it and `last` the newest meeting carrying the topic. */
export interface TagCoverage {
  tag: string
  score: number
  n: number
  of: number
  last: string | null
}

/** The selected topic a committee covers most, or undefined when it covers none of them. */
export function bestTopic(selected: readonly string[], coverage: readonly TagCoverage[] | undefined): TagCoverage | undefined {
  let best: TagCoverage | undefined
  for (const c of coverage ?? []) {
    if (selected.includes(c.tag) && c.score > 0 && (!best || c.score > best.score)) best = c
  }
  return best
}

/** How well a committee fits the selected topics: its strongest coverage among them (0 if none). */
export function topicFit(selected: readonly string[], coverage: readonly TagCoverage[] | undefined): number {
  return bestTopic(selected, coverage)?.score ?? 0
}

/** `items` best fit first. Stable, so equal fits (and everything, when nothing is selected)
 * keep their incoming order. */
export function rankByFit<T>(items: readonly T[], fit: (item: T) => number): T[] {
  return items
    .map((item, i) => ({ item, i, f: fit(item) }))
    .sort((a, b) => b.f - a.f || a.i - b.i)
    .map((x) => x.item)
}

/** A score as a whole percent, e.g. 0.824 -> "82%". */
export function pct(score: number): string {
  return Math.round(score * 100) + '%'
}
