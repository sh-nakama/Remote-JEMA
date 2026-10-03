import { describe, expect, it } from 'vitest'
import {
  bestTopic,
  committeesWithTopicMeetings,
  matchesTags,
  pct,
  rankByFit,
  tagCounts,
  tagLabel,
  tagsByGroup,
  toggleTag,
  topicFit,
  type TagCoverage,
  type TagVocab,
} from './policyTags'

const vocab: TagVocab = {
  groups: [
    { key: 'generation', ja: '発電', en: 'Generation' },
    { key: 'grid', ja: '系統設備', en: 'Grid' },
    { key: 'unused', ja: '空', en: 'Empty' },
  ],
  tags: [
    { key: 'wind_offshore', group: 'generation', ja: '洋上風力', en: 'Offshore wind' },
    { key: 'solar_utility', group: 'generation', ja: '事業用太陽光', en: 'Grid-scale solar' },
    { key: 'grid_cost', group: 'grid', ja: '託送料金・費用負担', en: 'Network charges' },
  ],
}

describe('matchesTags', () => {
  it('matches everything when nothing is selected, even an untagged row', () => {
    expect(matchesTags([], undefined)).toBe(true)
    expect(matchesTags([], [])).toBe(true)
  })
  it('is "any of" the selected topics', () => {
    expect(matchesTags(['wind_offshore', 'grid_cost'], ['grid_cost'])).toBe(true)
    expect(matchesTags(['wind_offshore'], ['solar_utility', 'grid_cost'])).toBe(false)
  })
  it('never matches an untagged row once a topic is selected', () => {
    expect(matchesTags(['wind_offshore'], undefined)).toBe(false)
    expect(matchesTags(['wind_offshore'], [])).toBe(false)
  })
})

describe('toggleTag', () => {
  it('adds, removes, and does not mutate', () => {
    const a = ['wind_offshore']
    expect(toggleTag(a, 'grid_cost')).toEqual(['wind_offshore', 'grid_cost'])
    expect(toggleTag(a, 'wind_offshore')).toEqual([])
    expect(a).toEqual(['wind_offshore'])
  })
})

describe('tagCounts', () => {
  it('counts rows per tag, once per row', () => {
    expect(tagCounts([{ tags: ['a', 'b'] }, { tags: ['a', 'a'] }, {}, { tags: [] }])).toEqual({ a: 2, b: 1 })
  })
})

describe('tagLabel', () => {
  it('uses the requested language and falls back to the key for a retired tag', () => {
    expect(tagLabel(vocab, 'wind_offshore', 'ja')).toBe('洋上風力')
    expect(tagLabel(vocab, 'wind_offshore', 'en')).toBe('Offshore wind')
    expect(tagLabel(vocab, 'retired_tag', 'en')).toBe('retired_tag')
  })
})

describe('tagsByGroup', () => {
  it('keeps vocabulary order and drops groups with no tags', () => {
    const g = tagsByGroup(vocab)
    expect(g.map((x) => x.group.key)).toEqual(['generation', 'grid'])
    expect(g[0].tags.map((t) => t.key)).toEqual(['wind_offshore', 'solar_utility'])
  })
})

describe('committeesWithTopicMeetings', () => {
  const meetings = [
    { com: 'a', tags: ['wind_offshore'] },
    { com: 'b', tags: ['grid_cost'] },
    { com: 'c' },
    { tags: ['wind_offshore'] },
  ]
  it('finds committees that hold a matching meeting', () => {
    expect([...committeesWithTopicMeetings(['wind_offshore'], meetings)]).toEqual(['a'])
  })
  it('is empty with no selection', () => {
    expect(committeesWithTopicMeetings([], meetings).size).toBe(0)
  })
})

describe('topic fit', () => {
  const cov: TagCoverage[] = [
    { tag: 'wind_offshore', score: 0.8, n: 8, of: 10, last: '2026-09-27' },
    { tag: 'grid_cost', score: 0.3, n: 3, of: 10, last: '2026-08-01' },
  ]
  it('is the strongest coverage among the selected topics', () => {
    expect(topicFit(['grid_cost'], cov)).toBe(0.3)
    expect(topicFit(['grid_cost', 'wind_offshore'], cov)).toBe(0.8)
    expect(bestTopic(['grid_cost', 'wind_offshore'], cov)?.tag).toBe('wind_offshore')
  })
  it('is 0 / undefined when the committee covers none of them, or has no coverage data', () => {
    expect(topicFit(['nuclear'], cov)).toBe(0)
    expect(bestTopic(['nuclear'], cov)).toBeUndefined()
    expect(topicFit(['nuclear'], undefined)).toBe(0)
    expect(topicFit([], cov)).toBe(0)
  })
})

describe('rankByFit', () => {
  it('orders best first and keeps the incoming order for ties', () => {
    const items = [
      { k: 'a', f: 0 },
      { k: 'b', f: 0.5 },
      { k: 'c', f: 0 },
      { k: 'd', f: 0.9 },
    ]
    expect(rankByFit(items, (x) => x.f).map((x) => x.k)).toEqual(['d', 'b', 'a', 'c'])
  })
  it('is a no-op when everything ties (nothing selected) and does not mutate', () => {
    const items = ['x', 'y', 'z']
    expect(rankByFit(items, () => 0)).toEqual(['x', 'y', 'z'])
    expect(items).toEqual(['x', 'y', 'z'])
  })
})

describe('pct', () => {
  it('rounds to a whole percent', () => {
    expect(pct(0.824)).toBe('82%')
    expect(pct(0.005)).toBe('1%')
    expect(pct(0)).toBe('0%')
  })
})
