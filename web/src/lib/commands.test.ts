import { describe, expect, it } from 'vitest'
import {
  agoLabel, confirmLines, defaultValues, inGroup, missingRequired, requestBody,
  type Bi, type CommandInfo, type Guards,
} from './commands'

const cmd = (over: Partial<CommandInfo>): CommandInfo => ({
  id: 'detect', group: 'backflow', level: 'writes', order: 1, title: ['Detect', '検出'], summary: ['s', 's'],
  when: ['w', 'w'], params: [], needsNotebooklm: false, warning: null, cli: 'repower policy detect', ...over,
})
const pull = cmd({ id: 'pull-hf', level: 'dangerous', warning: ['This REPLACES your local database.', '置き換えます'] })
const push = cmd({ id: 'push-hf', level: 'dangerous', warning: ['This REPLACES the shared dataset.', '置き換えます'] })
const titles: Record<string, Bi> = { 'resolve-citations': ['Resolve citation pages', '引用ページを解決'], detect: ['Detect new meetings', '新規会合を検出'] }
const NOW = Date.parse('2026-10-03T12:00:00Z')
const guards = (over: Partial<Guards>): Guards => ({
  lastPull: '2026-10-03T08:00:00+00:00', lastPush: null, unpushed: [], pullAgeHours: 4, pullStale: false, freshHours: 12, ...over,
})

describe('confirmLines — pull', () => {
  it('always leads with the command’s own warning', () => {
    expect(confirmLines(pull, guards({}), titles, NOW, 'en')[0]).toEqual({ tone: 'danger', text: 'This REPLACES your local database.' })
  })
  it('names the un-pushed local work a pull would discard', () => {
    const g = guards({ unpushed: [{ cmd: 'resolve-citations', at: '2026-10-03T09:00:00+00:00' }, { cmd: 'detect', at: '2026-10-03T11:30:00+00:00' }] })
    const l = confirmLines(pull, g, titles, NOW, 'en')
    expect(l[1].tone).toBe('danger')
    expect(l[1].text).toContain('Resolve citation pages (3 h ago)')
    expect(l[1].text).toContain('Detect new meetings (30 min ago)')
    expect(l[1].text).toContain('push first')
  })
  it('does not claim a clean slate: terminal commands are not tracked', () => {
    const l = confirmLines(pull, guards({}), titles, NOW, 'en')
    expect(l[1].tone).toBe('info')
    expect(l[1].text).toContain('terminal')
  })
})

describe('confirmLines — push', () => {
  const dirty = { unpushed: [{ cmd: 'detect', at: '2026-10-03T11:00:00+00:00' }] }
  it('is danger when this app has never pulled', () => {
    const l = confirmLines(push, guards({ lastPull: null, pullAgeHours: null, pullStale: true, ...dirty }), titles, NOW, 'en')
    expect(l.some((x) => x.tone === 'danger' && x.text.includes('no record of a pull'))).toBe(true)
  })
  it('is danger when the last pull is stale, and says how old', () => {
    const l = confirmLines(push, guards({ lastPull: '2026-10-02T08:00:00+00:00', pullAgeHours: 28, pullStale: true, ...dirty }), titles, NOW, 'en')
    const d = l.find((x) => x.tone === 'danger' && x.text.includes('last pull'))
    expect(d?.text).toContain('28 h ago')
    expect(d?.text).toContain('more than 12 h')
  })
  it('is only informational after a recent pull', () => {
    const l = confirmLines(push, guards(dirty), titles, NOW, 'en')
    expect(l.filter((x) => x.tone === 'danger')).toHaveLength(1) // just the base warning
    expect(l.some((x) => x.text === 'Last pull: 4 h ago.')).toBe(true)
  })
  it('notes when there is nothing recorded to push', () => {
    expect(confirmLines(push, guards({}), titles, NOW, 'en').some((x) => x.tone === 'warn' && x.text.includes('may change nothing'))).toBe(true)
  })
  it('speaks Japanese', () => {
    const l = confirmLines(push, guards({ lastPull: null, pullStale: true, pullAgeHours: null }), titles, NOW, 'ja')
    expect(l[0].text).toBe('置き換えます')
    expect(l.some((x) => x.text.includes('先にpullしてください'))).toBe(true)
  })
})

describe('confirmLines — degraded', () => {
  it('still warns, and says the history is unavailable, when the guards could not be read', () => {
    const l = confirmLines(pull, null, titles, NOW, 'en')
    expect(l.map((x) => x.tone)).toEqual(['danger', 'warn'])
  })
  it('adds nothing about order to other commands', () => {
    expect(confirmLines(cmd({}), guards({}), titles, NOW, 'en')).toEqual([])
  })
})

describe('forms', () => {
  const backfill = cmd({
    id: 'backfill',
    params: [
      { name: 'committee', kind: 'committee', label: ['Committee', ''], required: true },
      { name: 'since_meeting', kind: 'int', label: ['From', ''], required: true, lo: 1, hi: 100000 },
      { name: 'max_per_run', kind: 'int', label: ['Max', ''], required: false, default: 10, lo: 1, hi: 30 },
    ],
  })
  it('starts from the defaults', () => {
    expect(defaultValues(backfill)).toEqual({ committee: '', since_meeting: '', max_per_run: 10 })
  })
  it('lists required fields still missing — and treats "all" as missing for a required committee', () => {
    expect(missingRequired(backfill, defaultValues(backfill))).toEqual(['committee', 'since_meeting'])
    expect(missingRequired(backfill, { committee: 'all', since_meeting: 3, max_per_run: 10 })).toEqual(['committee'])
    expect(missingRequired(backfill, { committee: 'x', since_meeting: 3, max_per_run: 10 })).toEqual([])
  })
  it('sends numbers as numbers and leaves empty fields out', () => {
    expect(requestBody(backfill, { committee: 'system_review', since_meeting: '40', max_per_run: 10 }))
      .toEqual({ cmd: 'backfill', committee: 'system_review', since_meeting: 40, max_per_run: 10 })
    expect(requestBody(backfill, { committee: '', since_meeting: '', max_per_run: '' })).toEqual({ cmd: 'backfill' })
  })
  it('keeps an unticked bool (false is a real answer, not "empty")', () => {
    const tag = cmd({ id: 'tag', params: [{ name: 'apply', kind: 'bool', label: ['Apply', ''], required: false, default: true }] })
    expect(requestBody(tag, { apply: false })).toEqual({ cmd: 'tag', apply: false })
  })
})

describe('helpers', () => {
  it('orders a group by position', () => {
    const cs = [cmd({ id: 'b', order: 2 }), cmd({ id: 'a', order: 1 }), cmd({ id: 'z', group: 'inspect', order: 0 })]
    expect(inGroup(cs, 'backflow').map((c) => c.id)).toEqual(['a', 'b'])
  })
  it('labels ages coarsely', () => {
    expect(agoLabel('2026-10-03T11:55:00Z', NOW, 'en')).toBe('5 min ago')
    expect(agoLabel('2026-10-03T07:00:00Z', NOW, 'en')).toBe('5 h ago')
    expect(agoLabel('2026-09-30T12:00:00Z', NOW, 'ja')).toBe('3日前')
    expect(agoLabel('not a date', NOW, 'en')).toBe('')
  })
})
