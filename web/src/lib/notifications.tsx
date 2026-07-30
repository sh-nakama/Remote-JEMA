import { useCallback, useState } from 'react'
import { s, Hoverable, RawSvg } from './style'

/**
 * Shared notifications popover (the top-bar bell).
 *
 * There is no notification *service* behind JEMA — the app is a static snapshot
 * reader. So each screen derives its own items from data it has already loaded
 * (the export manifest, the wholesale series, the capacity results) and passes
 * them in here. This module owns only the chrome plus the read/unread bookkeeping.
 */

export type NotifKind = 'new' | 'done' | 'warn' | 'info'

export interface NotifItem {
  key: string
  title: string
  meta?: string
  kind?: NotifKind
  /** Small pill on the right (e.g. "New"). */
  badge?: string
  /**
   * Event time in ms. Items newer than the last "mark all read" are unread and
   * drive the bell dot. Items WITHOUT a timestamp (standing facts like a
   * cumulative total) are never unread — that keeps the dot meaningful.
   */
  ts?: number
  onClick?: () => void
}

export interface NotifSection {
  key: string
  label: string
  items: NotifItem[]
}

/**
 * Last-read timestamp for one bell, persisted per screen so marking Market Data
 * read doesn't silence Capacity Auctions.
 */
export function useNotifSeen(storeKey: string): { seenAt: number; markSeen: () => void } {
  const [seenAt, setSeenAt] = useState<number>(() => {
    try {
      return Number(localStorage.getItem(storeKey)) || 0
    } catch {
      return 0 // private mode / storage disabled
    }
  })
  const markSeen = useCallback(() => {
    const now = Date.now()
    try {
      localStorage.setItem(storeKey, String(now))
    } catch {
      /* ignore — read state is a nicety, not data */
    }
    setSeenAt(now)
  }, [storeKey])
  return { seenAt, markSeen }
}

/** How many items are newer than the last "mark all read". */
export function unreadCount(sections: NotifSection[], seenAt: number): number {
  let n = 0
  for (const sec of sections) for (const it of sec.items) if (it.ts != null && it.ts > seenAt) n += 1
  return n
}

const WARN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;color:#F4A261;margin-top:2px;flex-shrink:0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`

function Marker({ kind }: { kind: NotifKind }) {
  if (kind === 'warn') return <RawSvg html={WARN_ICON} />
  if (kind === 'done')
    return (
      <span style={s('width:16px;height:16px;border-radius:999px;background:var(--acTint);color:var(--acT);display:flex;align-items:center;justify-content:center;margin-top:1px;flex-shrink:0;font-size:10px;font-weight:700')}>✓</span>
    )
  return (
    <span style={s(`width:7px;height:7px;border-radius:999px;background:${kind === 'new' ? 'var(--ac)' : 'var(--fnt2)'};margin-top:6px;flex-shrink:0`)}></span>
  )
}

export interface NotificationsPopoverProps {
  open: boolean
  lang: 'en' | 'ja'
  sections: NotifSection[]
  seenAt: number
  /** Right-hand note in the header (e.g. the window the items cover). */
  note?: string
  onClose: () => void
  onMarkRead: () => void
  /** Optional footer link, e.g. "View all →". */
  action?: { label: string; onClick: () => void }
}

export function NotificationsPopover({
  open,
  lang,
  sections,
  seenAt,
  note,
  onClose,
  onMarkRead,
  action,
}: NotificationsPopoverProps) {
  if (!open) return null
  const ja = lang === 'ja'
  const shown = sections.filter((sec) => sec.items.length > 0)
  return (
    <div style={s('position:absolute;right:24px;top:66px;width:360px;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shPop);padding:16px;z-index:60')}>
      <div style={s('display:flex;align-items:center;justify-content:space-between')}>
        <div style={s('font-size:14px;font-weight:600')}>Notifications <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>通知</span></div>
        {note && <span style={s('font-size:11px;color:var(--mut)')}>{note}</span>}
      </div>
      {shown.length === 0 ? (
        <div style={s('font-size:12.5px;color:var(--mut);padding:18px 4px;text-align:center')}>
          {ja ? '新着はありません — 最新の状態です' : 'You’re all caught up · no recent activity'}
        </div>
      ) : (
        shown.map((sec) => (
          <div key={sec.key}>
            <div style={s('font-size:11px;font-weight:600;letter-spacing:.05em;color:var(--mut);margin:12px 0 6px')}>{sec.label}</div>
            <div style={s('display:flex;flex-direction:column;gap:2px')}>
              {sec.items.map((it) => {
                const unread = it.ts != null && it.ts > seenAt
                return (
                  <Hoverable
                    key={it.key}
                    base={`display:flex;gap:9px;align-items:flex-start;padding:8px;border-radius:10px${it.onClick ? ';cursor:pointer' : ''}`}
                    hover={it.onClick ? 'background:var(--hov)' : ''}
                    onClick={it.onClick}
                  >
                    <Marker kind={it.kind || 'info'} />
                    <div style={s('flex:1;min-width:0')}>
                      <div style={s(`font-size:12.5px;font-weight:${unread ? 600 : 500}`)}>{it.title}</div>
                      {it.meta && (
                        <div style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>{it.meta}</div>
                      )}
                    </div>
                    {it.badge && (
                      <span style={s('font-size:10px;font-weight:600;background:var(--acTint);color:var(--acT);border-radius:6px;padding:1px 6px;flex-shrink:0')}>{it.badge}</span>
                    )}
                  </Hoverable>
                )
              })}
            </div>
          </div>
        ))
      )}
      <div style={s('display:flex;justify-content:space-between;border-top:1px solid var(--dv);margin-top:12px;padding-top:10px')}>
        <Hoverable
          as="span"
          base="font-size:12px;color:var(--tx2);cursor:pointer"
          hover="color:var(--acT)"
          onClick={() => {
            onMarkRead()
            onClose()
          }}
        >
          {ja ? 'すべて既読に' : 'Mark all read'}
        </Hoverable>
        {action && (
          <span style={s('font-size:12px;font-weight:600;color:var(--acT);cursor:pointer')} onClick={action.onClick}>{action.label}</span>
        )}
      </div>
    </div>
  )
}

/** "2026-07-27" / ISO timestamp → ms, or NaN. Dates are treated as UTC midnight. */
export function tsOfDate(v: string | null | undefined): number {
  if (!v) return NaN
  return Date.parse(v.length === 10 ? v + 'T00:00:00Z' : v)
}
