// Manage → Queue: which meetings are waiting to be summarised, in the order the next daily run
// takes them, and what the last runs have already worked through.
//
// Everything here is read-only except an optional "move to the front" arrow in the local app. The
// order comes from the server (`store.queue_snapshot` — the worklist `policy run --committee all`
// itself uses), so the cap line is where a run stops by count; the NotebookLM daily quota often
// stops it sooner, which the intro says rather than hides.

import { useState } from 'react'
import { s, Hoverable, press } from './style'
import { useApp } from './app'
import {
  agoText, committeesByBacklog, KIND_META, positionLabel, runsUntil, selectItems, splitAtCap, withGaps,
  type DrainedItem, type QueueFilter, type QueueItem, type QueueKind, type QueuePayload,
} from './policyQueue'

const CHIP = 'font-size:9.5px;font-weight:700;letter-spacing:.04em;border-radius:5px;padding:1px 6px;white-space:nowrap;flex-shrink:0'
const HEAD = 'font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:18px 2px 6px'
const ROW = 'display:grid;grid-template-columns:34px minmax(150px,1.6fr) 62px 88px 150px minmax(0,1fr) 28px;gap:8px;align-items:center;padding:5px 6px;border-top:1px solid var(--dv)'

export function QueueView({
  queue,
  loading,
  nameOf,
  interactive,
  onQueueMeeting,
}: {
  queue: QueuePayload | null | undefined
  loading: boolean
  /** Committee key → display name in the current language. */
  nameOf: (key: string) => string
  interactive: boolean
  onQueueMeeting: (key: string, num: number, queued: boolean) => void
}) {
  const app = useApp()
  const ja = app.lang === 'ja'
  const pick = (en: string, jp: string) => (ja ? jp : en)
  const [filter, setFilter] = useState<QueueFilter>('all')
  const [com, setCom] = useState<string | null>(null)

  if (!queue) {
    return (
      <div style={s('padding:26px;text-align:center;color:var(--mut);font-size:13px')}>
        {loading
          ? pick('Loading…', '読み込み中…')
          : pick('No queue data yet — this snapshot predates the queue view. It appears after the next export.', 'キューのデータがありません。次回のエクスポート後に表示されます。')}
      </div>
    )
  }

  const { cap, totals, items, recent } = queue
  const shown = selectItems(items, { filter, com })
  const { next, waiting } = splitAtCap(shown, cap)
  const filtered = filter !== 'all' || com !== null
  const committees = committeesByBacklog(queue.byCom)

  const kindChip = (k: QueueKind) => {
    const m = KIND_META[k]
    return (
      <span style={s(`${CHIP};background:${m.bg};color:${m.fg}`)} title={ja ? m.tipJa : m.tipEn}>
        {ja ? m.ja : m.en}
      </span>
    )
  }

  const filters: [QueueFilter, string, number, string][] = [
    ['all', pick('All', 'すべて'), queue.total, ''],
    ['new', pick('New', '新規'), totals.new, ja ? KIND_META.new.tipJa : KIND_META.new.tipEn],
    ['update', pick('Update', '更新'), totals.update, ja ? KIND_META.update.tipJa : KIND_META.update.tipEn],
    ['retry', pick('Retry', '再試行'), totals.retry, ja ? KIND_META.retry.tipJa : KIND_META.retry.tipEn],
    ['requested', pick('Moved to front', '先頭指定'), totals.requested, pick('Someone moved these to the front of the queue.', '手動でキュー先頭に指定された会合。')],
  ]

  const row = (it: QueueItem, waitingRow: boolean) => {
    const pos = positionLabel(it, cap, ja)
    const day = runsUntil(it.rank, cap)
    return (
      <div key={`${it.com}:${it.num}`} style={s(`${ROW}${waitingRow ? ';opacity:.72' : ''}`)}>
        <span style={s(`font-size:11px;font-weight:700;text-align:right;font-feature-settings:'tnum' 1;color:${pos.soon ? 'var(--acT)' : 'var(--mut)'}`)}>{it.rank}</span>
        <div style={s('min-width:0')}>
          <div style={s('font-size:12px;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{nameOf(it.com)}</div>
          <div style={s('font-size:10.5px;color:var(--mut)')}>{it.com}</div>
        </div>
        <span style={s('font-size:11.5px;font-weight:600;color:var(--tx)')}>第{it.num}回</span>
        <span style={s("font-size:11.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{it.date || '—'}</span>
        <span style={s('display:flex;gap:5px;align-items:center;min-width:0')}>
          {kindChip(it.kind)}
          {it.requested && (
            <span style={s(`${CHIP};border:1px solid var(--ac);color:var(--acT)`)} title={pick('Moved to the front of the queue', 'キュー先頭に指定済み')}>
              {pick('FRONT', '先頭')}
            </span>
          )}
          {it.retries > 0 && <span style={s('font-size:10.5px;color:var(--warnTx)')}>{it.retries}×</span>}
        </span>
        <span style={s(`font-size:11px;color:${pos.soon ? 'var(--acT)' : 'var(--mut)'};font-weight:${pos.soon ? 600 : 400}`)}
              title={pos.soon ? pick('Inside the daily cap: the next run takes it, if the NotebookLM quota allows.', '日次の上限内: クォータが許せば次回の実行で処理されます。')
                              : pick('At the cap per day, roughly this many daily runs away — a floor, since the quota usually stops a run sooner.', '1日の上限で換算した目安の実行回数（クォータにより実際はこれ以上）。')}>
          {pos.soon ? pos.text : pick(`~day ${day}`, `約${day}日目`)}
        </span>
        {interactive ? (
          <Hoverable
            as="span"
            base="width:22px;height:22px;border-radius:999px;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;color:var(--mut);border:1px solid var(--bd2);font-size:11px"
            hover="border-color:var(--ac);color:var(--acT)"
            title={it.requested ? pick('Moved to the front — click to take it off', '先頭指定中 — クリックで解除') : pick('Move to the front of the queue', 'キューの先頭へ')}
            aria-label={it.requested ? 'Remove from the front of the queue' : 'Move to the front of the queue'}
            {...press(() => onQueueMeeting(it.com, it.num, !it.requested))}
          >↑</Hoverable>
        ) : <span></span>}
      </div>
    )
  }

  const drained = (d: DrainedItem) => (
    <div key={`${d.com}:${d.num}:${d.at}`} style={s('display:grid;grid-template-columns:78px minmax(150px,1.6fr) 62px 110px;gap:8px;align-items:center;padding:5px 6px;border-top:1px solid var(--dv)')}>
      <span style={s('font-size:11px;color:var(--mut)')} title={d.at}>{agoText(d.at, ja)}</span>
      <div style={s('min-width:0')}>
        <div style={s('font-size:12px;font-weight:600;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{nameOf(d.com)}</div>
        <div style={s('font-size:10.5px;color:var(--mut)')}>{d.com}</div>
      </div>
      <span style={s('font-size:11.5px;font-weight:600;color:var(--tx)')}>第{d.num}回</span>
      <span>
        {d.kind ? kindChip(d.kind) : (
          <span style={s(`${CHIP};background:var(--bg2);color:var(--mut)`)} title={pick('Summarised before first-vs-repeat was recorded.', '初回か再作成かの記録開始前に要約されたもの。')}>
            {pick('SUMMARISED', '要約済み')}
          </span>
        )}
      </span>
    </div>
  )

  const chipBase = (on: boolean, dim: boolean) =>
    `font-size:11.5px;font-weight:600;border-radius:999px;padding:3px 12px;white-space:nowrap;cursor:pointer;${
      on ? 'background:var(--acTint);border:1px solid var(--ac);color:var(--acT)'
         : `border:1px solid var(--bd2);color:var(--mut)${dim ? ';opacity:.55' : ''}`}`

  const lastDrained = recent[0]?.at

  return (
    <div style={s('min-width:760px;padding-top:6px')}>
      <div style={s('font-size:11.5px;color:var(--tx2);line-height:1.55;margin:2px 4px 8px')}>
        {pick(
          `The daily run takes the first ${cap} of this list, breadth-first across tracked committees — and stops sooner if NotebookLM's daily quota runs out. Everything below the line waits for a later day. This is the expected order: a committee whose source site is blocked that day is skipped.`,
          `日次の実行は、追跡中の委員会を横断して、このリストの先頭 ${cap} 件を処理します（NotebookLMの日次クォータに達すると、それより早く停止）。線より下は後日の処理です。これは想定順で、配信元がブロックされた委員会はその日スキップされます。`,
        )}
      </div>

      <div style={s('display:flex;flex-wrap:wrap;gap:6px;align-items:center')}>
        {filters.map(([f, label, n, tip]) => (
          <Hoverable
            as="span"
            key={f}
            base={chipBase(filter === f, n === 0 && f !== 'all')}
            hover={filter === f ? '' : 'border-color:var(--ac);color:var(--acT)'}
            title={tip || undefined}
            {...press(() => setFilter(f), filter === f)}
          >
            {label} {n}
          </Hoverable>
        ))}
        <span style={s('font-size:11px;color:var(--mut);margin-left:auto')}>
          {pick(`Drained in the last ${queue.recentDays} days: ${recent.length}`, `直近${queue.recentDays}日で処理: ${recent.length}件`)}
          {lastDrained ? ` · ${pick('last', '最終')} ${agoText(lastDrained, ja)}` : ''}
        </span>
      </div>

      <div style={s('display:flex;flex-wrap:wrap;gap:5px;align-items:center;margin-top:8px')}>
        <span style={s('font-size:10px;font-weight:700;letter-spacing:.06em;color:var(--mut);margin-right:2px')}>{pick('COMMITTEE', '委員会')}</span>
        {committees.map(({ com: key, counts, n }) => (
          <Hoverable
            as="span"
            key={key}
            base={chipBase(com === key, false) + ';font-size:11px;padding:2px 10px'}
            hover={com === key ? '' : 'border-color:var(--ac);color:var(--acT)'}
            title={`${nameOf(key)} — ${counts.new} ${pick('new', '新規')} · ${counts.update} ${pick('update', '更新')} · ${counts.retry} ${pick('retry', '再試行')}`}
            {...press(() => setCom(com === key ? null : key), com === key)}
          >
            {key} {n}
          </Hoverable>
        ))}
        {com !== null && (
          <Hoverable as="span" base="font-size:11px;color:var(--acT);cursor:pointer;margin-left:4px" hover="text-decoration:underline"
            {...press(() => setCom(null))}>{pick('clear', '解除')}</Hoverable>
        )}
      </div>

      <div style={s(HEAD)}>
        {pick('UP NEXT', '次に処理')}
        {filtered ? <span style={s('font-weight:500;letter-spacing:0')}>{` · ${pick('filtered', '絞り込み中')} (${shown.length})`}</span> : null}
      </div>
      {shown.length === 0 && (
        <div style={s('padding:16px 6px;color:var(--mut);font-size:12.5px;border-top:1px solid var(--dv)')}>
          {queue.total === 0
            ? pick('Nothing is queued: every tracked committee is up to date.', '待ちはありません。追跡中の委員会はすべて最新です。')
            : pick('Nothing matches that filter in the first entries of the queue.', '絞り込みに合う会合が、表示範囲内にありません。')}
        </div>
      )}
      {next.map((it) => row(it, false))}
      {next.length > 0 && waiting.length > 0 && (
        <div style={s('display:flex;align-items:center;gap:8px;margin:4px 0;color:var(--acT);font-size:10.5px;font-weight:700;letter-spacing:.05em')}>
          <span style={s('flex:1;border-top:1px dashed var(--ac)')}></span>
          {pick(`DAILY RUN TAKES THE FIRST ${cap}`, `日次の処理は先頭${cap}件まで`)}
          <span style={s('flex:1;border-top:1px dashed var(--ac)')}></span>
        </div>
      )}
      {withGaps(waiting, next.length ? next[next.length - 1].rank : cap).map(({ item, gap }) => (
        <div key={`${item.com}:${item.num}`}>
          {gap > 0 && !filtered && (
            <div style={s('padding:5px 6px 5px 42px;color:var(--mut);font-size:11px;border-top:1px solid var(--dv);font-style:italic')}>
              {pick(`… ${gap} more new meeting(s) …`, `… 他 ${gap} 件の新規 …`)}
            </div>
          )}
          {row(item, true)}
        </div>
      ))}
      {queue.truncated > 0 && !filtered && (
        <div style={s('padding:8px 6px;color:var(--mut);font-size:11.5px;border-top:1px solid var(--dv)')}>
          {pick(`${queue.truncated} more new meeting(s) not listed — updates, retries and moved-to-front ones are always listed; the committee chips count the whole queue`, `新規の ${queue.truncated} 件は一覧外です（更新・再試行・先頭指定は常に表示。委員会チップは全体の件数）`)}
        </div>
      )}

      <div style={s(HEAD)}>{pick(`DRAINED · last ${queue.recentDays} days`, `処理済み · 直近${queue.recentDays}日`)}</div>
      {recent.length === 0 && (
        <div style={s('padding:12px 6px;color:var(--mut);font-size:12.5px;border-top:1px solid var(--dv)')}>
          {pick('Nothing summarised in this window.', 'この期間に要約された会合はありません。')}
        </div>
      )}
      {recent.filter((d) => com === null || d.com === com).map(drained)}
    </div>
  )
}
