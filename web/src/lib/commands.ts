// The Commands pane's data: the registry served by `repower web-api` (GET /api/commands) and the
// rules that turn it into forms and confirmation warnings. Pure logic lives here, apart from the
// component, so the pull/push ordering rules can be unit-tested.
//
// The registry itself is Python (`repower/commands.py`) — the same list the backend uses as its
// allowlist — so what the pane offers and what the server will run cannot drift apart.

import { useCallback, useEffect, useState } from 'react'
import type { Lang } from './app'

export type Level = 'safe' | 'writes' | 'dangerous'
export type Group = 'backflow' | 'inspect' | 'automated'
export type Bi = [string, string]

export interface ParamSpec {
  name: string
  kind: 'committee' | 'int' | 'bool' | 'choice'
  label: Bi
  required: boolean
  default?: string | number | boolean
  lo?: number
  hi?: number
  choices?: string[]
}

export interface CommandInfo {
  id: string
  group: Group
  level: Level
  /** Position within its group; in `backflow` it is the step number to run in. */
  order: number
  title: Bi
  summary: Bi
  when: Bi
  params: ParamSpec[]
  needsNotebooklm: boolean
  warning: Bi | null
  /** The equivalent terminal command, e.g. `repower policy detect`. */
  cli: string
}

export interface Recipe {
  id: string
  title: Bi
  summary: Bi
  steps: string[]
  optional: string[]
}

/** What the server remembers about pulls and pushes made from this app. */
export interface Guards {
  lastPull: string | null
  lastPush: string | null
  unpushed: { cmd: string; at: string }[]
  pullAgeHours: number | null
  pullStale: boolean
  freshHours: number
}

export interface CommandsPayload {
  commands: CommandInfo[]
  recipes: Recipe[]
  guards: Guards
  committees: { key: string; en: string; ja: string }[]
}

export type Values = Record<string, string | number | boolean>

export const pickBi = (b: Bi, lang: Lang): string => (lang === 'ja' ? b[1] : b[0])

export function inGroup(cmds: CommandInfo[], group: Group): CommandInfo[] {
  return cmds.filter((c) => c.group === group).sort((a, b) => a.order - b.order)
}

/** Form values a command starts with: each parameter's default (`''` where it has none). */
export function defaultValues(cmd: CommandInfo): Values {
  const v: Values = {}
  for (const p of cmd.params) {
    if (p.default !== undefined) v[p.name] = p.default
    else v[p.name] = p.kind === 'bool' ? false : ''
  }
  return v
}

/** Names of required parameters that have no usable value yet. */
export function missingRequired(cmd: CommandInfo, values: Values): string[] {
  return cmd.params
    .filter((p) => p.required)
    .filter((p) => {
      const v = values[p.name]
      return v === undefined || v === '' || (p.kind === 'committee' && v === 'all')
    })
    .map((p) => p.name)
}

/** The POST body for `/api/policy/job`. Empty fields are left out so the server applies its default. */
export function requestBody(cmd: CommandInfo, values: Values): Record<string, unknown> {
  const body: Record<string, unknown> = { cmd: cmd.id }
  for (const p of cmd.params) {
    const v = values[p.name]
    if (v === undefined || v === '') continue
    body[p.name] = p.kind === 'int' ? Number(v) : v
  }
  return body
}

/** `3 h ago` / `2 d ago` — coarse on purpose; the point is "today or not". */
export function agoLabel(iso: string, now: number, lang: Lang): string {
  const mins = Math.max(0, Math.round((now - Date.parse(iso)) / 60000))
  if (Number.isNaN(mins)) return ''
  if (mins < 60) return lang === 'ja' ? `${mins}分前` : `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return lang === 'ja' ? `${hours}時間前` : `${hours} h ago`
  const days = Math.round(hours / 24)
  return lang === 'ja' ? `${days}日前` : `${days} d ago`
}

export interface ConfirmLine {
  /** `danger` blocks nothing but is shown in red and must be acknowledged with the rest. */
  tone: 'danger' | 'warn' | 'info'
  text: string
}

/** What to tell the user before a dangerous command runs, from what the server has recorded.
 *
 * The order is the whole point. A pull replaces the local database, so un-pushed local work is
 * lost; a push replaces the shared one, so a copy older than the daily runs' writes erases them.
 * Neither is detectable from the files themselves, hence the server-side log. It only knows
 * about commands run from this app, and says so instead of implying a clean bill of health. */
export function confirmLines(
  cmd: CommandInfo,
  guards: Guards | null,
  titles: Record<string, Bi>,
  now: number,
  lang: Lang,
): ConfirmLine[] {
  const ja = lang === 'ja'
  const lines: ConfirmLine[] = []
  if (cmd.warning) lines.push({ tone: 'danger', text: pickBi(cmd.warning, lang) })
  if (!guards) {
    lines.push({
      tone: 'warn',
      text: ja ? '前回のpull/pushの記録を取得できませんでした。順序を確認してから実行してください。'
        : 'Could not read the pull/push history — check the order yourself before running.',
    })
    return lines
  }
  const name = (id: string) => (titles[id] ? pickBi(titles[id], lang) : id)
  if (cmd.id === 'pull-hf') {
    if (guards.unpushed.length > 0) {
      const what = guards.unpushed.map((u) => `${name(u.cmd)} (${agoLabel(u.at, now, lang)})`).join(', ')
      lines.push({
        tone: 'danger',
        text: ja ? `未pushのローカル作業があります: ${what}。pullするとこれらは失われます。先にpushしてください。`
          : `You have local work that has not been pushed: ${what}. A pull discards it — push first.`,
      })
    } else {
      lines.push({
        tone: 'info',
        text: ja ? 'このアプリから実行した未pushの作業は記録されていません（ターミナルで実行したコマンドは記録されません）。'
          : 'No un-pushed work is recorded from this app (commands typed in a terminal are not tracked).',
      })
    }
  }
  if (cmd.id === 'push-hf') {
    if (guards.lastPull === null) {
      lines.push({
        tone: 'danger',
        text: ja ? 'このアプリからのpullの記録がありません。古いコピーをpushすると、日次実行が追加した内容を上書きします。先にpullしてください。'
          : 'This app has no record of a pull. Pushing a stale copy overwrites what the daily runs added — pull first.',
      })
    } else if (guards.pullStale) {
      const ago = agoLabel(guards.lastPull, now, lang)
      lines.push({
        tone: 'danger',
        text: ja ? `最後のpullは${ago}で、${guards.freshHours}時間より前です。その後の日次実行の更新を上書きする恐れがあります。先にpullしてください。`
          : `Your last pull was ${ago}, more than ${guards.freshHours} h ago. The daily runs may have written since, and this push would overwrite that — pull first.`,
      })
    } else {
      lines.push({
        tone: 'info',
        text: ja ? `最後のpullは${agoLabel(guards.lastPull, now, lang)}です。` : `Last pull: ${agoLabel(guards.lastPull, now, lang)}.`,
      })
    }
    if (guards.unpushed.length === 0) {
      lines.push({
        tone: 'warn',
        text: ja ? '前回のpull/push以降、このアプリから実行した書き込み作業は記録されていません。pushしても内容は変わらない可能性があります。'
          : 'No local writes are recorded since the last pull/push, so this push may change nothing.',
      })
    }
  }
  return lines
}

/** Fetch the registry from the local API. Only call it while the backend is reachable. */
export function useCommands(enabled: boolean): {
  data: CommandsPayload | null
  error: boolean
  reload: () => void
} {
  const [data, setData] = useState<CommandsPayload | null>(null)
  const [error, setError] = useState(false)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!enabled) return
    let alive = true
    fetch('/api/commands')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('commands ' + r.status))))
      .then((j: CommandsPayload) => {
        if (!alive) return
        setData(j)
        setError(false)
      })
      .catch(() => {
        if (alive) setError(true)
      })
    return () => {
      alive = false
    }
  }, [enabled, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, reload }
}
