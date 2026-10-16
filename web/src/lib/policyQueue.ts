// The summarisation queue, as the Manage → Queue view and the Status table's meeting rows show it.
//
// The data is `queue` in the status payload (GET /api/policy/status · policy/status.json), built
// server-side by `store.queue_snapshot` from the very function `policy run --committee all` uses
// for its worklist — so what is shown here is the order the next daily run will take, not a
// second opinion about it. Pure logic lives here, apart from the components, so it can be tested.

import { parseDbTs } from './time'

export type QueueKind = 'new' | 'update' | 'retry'

export interface QueueItem {
  /** 1-based position in the expected order. */
  rank: number
  com: string
  num: number
  date: string | null
  /** new: no briefing yet · update: summarised, a late paper means it is written again ·
   *  retry: errored, still under the retry cap. */
  kind: QueueKind
  /** Someone moved it to the front of the queue. */
  requested: boolean
  state: string
  retries: number
}

export interface DrainedItem {
  com: string
  num: number
  at: string
  /** null: summarised before the drain stamps existed, so first-vs-repeat is not known. */
  kind: 'new' | 'update' | null
}

export interface KindCounts {
  new: number
  update: number
  retry: number
  requested: number
}

export interface QueuePayload {
  /** Meetings one daily run takes (`policy run --max-per-run`). */
  cap: number
  /** The whole worklist; `items` is capped, so this can exceed `items.length`. */
  total: number
  totals: KindCounts
  byCom: Record<string, KindCounts>
  items: QueueItem[]
  truncated: number
  recent: DrainedItem[]
  recentDays: number
}

export const queueKey = (com: string, num: number): string => `${com}:${num}`

/** `com:num` → its place in the queue, for the Status table's per-meeting chips. */
export function indexQueue(q: QueuePayload | null | undefined): Map<string, QueueItem> {
  const m = new Map<string, QueueItem>()
  for (const it of q?.items ?? []) m.set(queueKey(it.com, it.num), it)
  return m
}

export interface KindMeta {
  en: string
  ja: string
  /** Chip colours, as CSS custom properties from the app theme. */
  bg: string
  fg: string
  /** One-sentence explanation, for the tooltip. */
  tipEn: string
  tipJa: string
}

export const KIND_META: Record<QueueKind, KindMeta> = {
  new: {
    en: 'NEW', ja: '新規', bg: 'var(--bg2)', fg: 'var(--tx2)',
    tipEn: 'Never summarised — it will get its first briefing.',
    tipJa: '未要約 — 初めての要約を作成します。',
  },
  update: {
    en: 'UPDATE', ja: '更新', bg: 'var(--acTint)', fg: 'var(--acT)',
    tipEn: 'Already summarised (and still showing that summary). A paper arrived afterwards — usually the minutes — so the briefing is written again.',
    tipJa: '要約済み（現在の要約は表示されたまま）。要約後に資料（多くは議事録）が追加されたため、再度作成します。',
  },
  retry: {
    en: 'RETRY', ja: '再試行', bg: 'var(--warnBg)', fg: 'var(--warnTx)',
    tipEn: 'An earlier attempt failed; it is retried until the retry cap.',
    tipJa: '前回の処理が失敗。再試行の上限まで繰り返します。',
  },
}

/** What one chip filter selects: a kind, "requested" (moved to the front), or everything. */
export type QueueFilter = 'all' | QueueKind | 'requested'

export interface QueueSelection {
  filter: QueueFilter
  /** Restrict to one committee key; null = all. */
  com: string | null
}

export function selectItems(items: QueueItem[], sel: QueueSelection): QueueItem[] {
  return items.filter(
    (it) =>
      (sel.com === null || it.com === sel.com) &&
      (sel.filter === 'all' ? true : sel.filter === 'requested' ? it.requested : it.kind === sel.filter),
  )
}

/** The first `cap` ranks are what one daily run takes; the rest wait for a later day. */
export function splitAtCap<T extends { rank: number }>(items: T[], cap: number): { next: T[]; waiting: T[] } {
  return { next: items.filter((it) => it.rank <= cap), waiting: items.filter((it) => it.rank > cap) }
}

/** Committees with something queued, biggest backlog first (ties by key). */
export function committeesByBacklog(byCom: Record<string, KindCounts>): { com: string; counts: KindCounts; n: number }[] {
  return Object.entries(byCom)
    .map(([com, counts]) => ({ com, counts, n: counts.new + counts.update + counts.retry }))
    .sort((a, b) => b.n - a.n || a.com.localeCompare(b.com))
}

/** A short position label for a meeting row: "next run #3" inside the cap, "#41" beyond it. */
export function positionLabel(it: QueueItem, cap: number, ja: boolean): { text: string; soon: boolean } {
  const soon = it.rank <= cap
  if (soon) return { text: ja ? `次回 #${it.rank}` : `next run #${it.rank}`, soon }
  return { text: `#${it.rank}`, soon }
}

/**
 * How many daily runs until this rank is reached, at `cap` per run. A floor, not a promise:
 * the NotebookLM daily quota usually stops a run before the cap, and a new meeting detected
 * tomorrow queues ahead of anything behind it.
 */
export function runsUntil(rank: number, cap: number): number {
  return cap > 0 ? Math.max(1, Math.ceil(rank / cap)) : 0
}

/** "3h ago" for a DB timestamp (UTC wall clock, no offset); "—" when absent. `now` is injectable for tests. */
export function agoText(dbTs: string | null | undefined, ja: boolean, now: number = Date.now()): string {
  const t = parseDbTs(dbTs)
  if (Number.isNaN(t)) return '—'
  const secs = Math.max(0, Math.round((now - t) / 1000))
  if (secs < 45) return ja ? 'たった今' : 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return ja ? `${mins}分前` : `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return ja ? `${hrs}時間前` : `${hrs}h ago`
  const days = Math.round(hrs / 24)
  return ja ? `${days}日前` : `${days}d ago`
}

/**
 * Pair each item with how many ranks were skipped just before it. The server lists the first
 * N meetings plus every update/retry/moved-to-front one wherever it ranks, so a long backlog
 * of ordinary new meetings can sit between two listed rows; the view says so instead of
 * letting rank 291 look like it follows rank 100. `after` is the rank the list continues from.
 */
export function withGaps<T extends { rank: number }>(items: T[], after: number): { item: T; gap: number }[] {
  let prev = after
  return items.map((item) => {
    const gap = Math.max(0, item.rank - prev - 1)
    prev = item.rank
    return { item, gap }
  })
}
