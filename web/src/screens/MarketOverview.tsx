import React, { useMemo, useRef, useState } from 'react'
import { s, Hoverable, RawSvg } from '../lib/style'
import { useApp } from '../lib/app'
import { downloadIcs } from '../lib/download'
import {
  today as fxToday,
  yday as fxYday,
  avg7 as fxAvg7,
  areas,
  paths as fxPaths,
  X,
  Y,
  meetings as fxMeetings,
  upcomingMeetings,
  freshData,
  MO,
  type Meeting,
} from './MarketOverview.data'
import { useSystemLive, buildPaths, usePolicyMeetings } from './MarketOverview.live'

const NOW = 29 // 14:30 slot

// ---- helpers ported from the DCLogic ----
function slotLabel(i: number): string {
  return String(Math.floor(i / 2)).padStart(2, '0') + ':' + (i % 2 ? '30' : '00')
}

const chipBaseStyle = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  fontSize: 11.5,
  fontWeight: 600,
  padding: '3px 9px',
  borderRadius: 999,
  marginTop: 9,
  fontFeatureSettings: "'tnum' 1",
} as const

interface Chip {
  txt: string
  style: React.CSSProperties
}

function chip(cur: number, prev: number): Chip {
  const d = cur - prev
  const p = prev ? (d / prev) * 100 : 0
  if (Math.abs(p) < 0.5) {
    return {
      txt: '— ±0.0%',
      style: { ...chipBaseStyle, background: 'rgba(138,147,163,.14)', color: 'var(--mut)' },
    }
  }
  const up = d > 0
  const sgn = up ? '+' : '−'
  return {
    txt: (up ? '▲ ' : '▼ ') + sgn + Math.abs(d).toFixed(2) + ' (' + sgn + Math.abs(p).toFixed(1) + '%)',
    style: {
      ...chipBaseStyle,
      background: up ? 'var(--upBg)' : 'var(--dnBg)',
      color: up ? 'var(--up)' : 'var(--dn)',
    },
  }
}

const segBase = (on: boolean): React.CSSProperties => ({
  padding: '4px 13px',
  borderRadius: 999,
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
  background: on ? 'var(--ac)' : 'transparent',
  color: on ? '#FFFFFF' : 'var(--mut)',
  transition: 'all .15s',
  whiteSpace: 'nowrap',
})

const filterChipBase = (on: boolean): React.CSSProperties => ({
  fontSize: 11.5,
  fontWeight: 600,
  padding: '3px 11px',
  borderRadius: 999,
  cursor: 'pointer',
  border: on ? '1px solid var(--ac)' : '1px solid var(--bd2)',
  background: on ? 'var(--acTint)' : 'var(--bg1)',
  color: on ? 'var(--acT)' : 'var(--mut)',
  whiteSpace: 'nowrap',
})

const avg = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length

/** A meeting's date as a Date. Live rows carry a real ISO date; fixtures fall
 * back to m/day (year 2026). */
const meetingDate = (m: Meeting): Date =>
  m.date ? new Date(m.date + 'T00:00:00') : new Date(2026, m.m - 1, m.day)

/** Short committee label for the compact timeline chips (full name is in the
 * hover title). Adds 第N回 / #N when a meeting number is known. */
const shortLabel = (m: Meeting, ja: boolean): string => {
  const base = ja ? m.ja : m.en
  const short = base.length > 20 ? base.slice(0, 19) + '…' : base
  return m.no ? short + (ja ? ` 第${m.no}回` : ` #${m.no}`) : short
}

export function MarketOverviewScreen() {
  const { lang, setLang, theme, toggleTheme, setScreen, toast, openOverlay, collapsed, toggleCollapsed, watch, isFollowing, toggleFollow } = useApp()
  const dark = theme === 'dark'
  const L = lang

  // local UI state (defaults from DCLogic)
  const [seg, setSeg] = useState<'today' | 'yday' | 'avg7'>('today')
  const [ghostOn, setGhostOn] = useState<boolean>(true) // ghostDefault
  const [hover, setHover] = useState<number | null>(null)
  const [showWhy, setShowWhy] = useState(false)
  const [showNotif, setShowNotif] = useState(false)
  const [filter, setFilter] = useState<'all' | 'followed' | 'upcoming'>('all')
  const chartRef = useRef<HTMLDivElement>(null)

  const showBrief = false // props.showAiBrief default

  // ---- live system-price data (falls back to fixtures while loading) ----
  const liveSys = useSystemLive(fxToday, fxYday, fxAvg7)
  const today = liveSys.today
  const yday = liveSys.yday
  const avg7 = liveSys.avg7
  const paths = useMemo(
    () => (liveSys.ready ? buildPaths(today, yday, avg7) : fxPaths),
    [liveSys.ready, today, yday, avg7],
  )
  const polMtg = usePolicyMeetings()
  const meetings = polMtg.ready ? polMtg.meetings : fxMeetings
  const upcoming = polMtg.ready ? polMtg.upcoming : upcomingMeetings

  // Days from today (local midnight): negative = past, positive = scheduled.
  const todayMid = useMemo(() => {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    return d
  }, [])
  const daysFrom = (m: Meeting) => Math.round((+meetingDate(m) - +todayMid) / 864e5)

  // ---- handlers ----
  const tMarket = () => setScreen('market')
  const tPolicy = () => setScreen('policy')
  const tCapacity = () => setScreen('capacity')
  const tRefresh = () => toast('Data refreshed · データを更新しました')
  const tIcs = () => {
    if (upcoming.length === 0) {
      toast(L === 'ja' ? '開催予定の会合はありません' : 'No scheduled meetings to export')
      return
    }
    const n = downloadIcs(
      'jema-upcoming-meetings.ics',
      upcoming.map((m) => ({
        uid: `${m.tier}-${m.no}-${m.date || `${m.m}-${m.day}`}`,
        date: meetingDate(m),
        summary: `${L === 'ja' ? m.ja : m.en}${m.no ? ` · No.${m.no}` : ''}`,
        description: (L === 'ja' ? m.sJa : m.sEn) || '',
      })),
    )
    toast(L === 'ja' ? `${n}件をカレンダー(.ics)に保存しました` : `Saved ${n} meeting(s) to calendar (.ics)`)
  }
  const toggleGhost = () => setGhostOn((g) => !g)
  const toggleWhy = () => setShowWhy((w) => !w)
  const toggleNotif = () => setShowNotif((n) => !n)
  const fs = () => {
    const el = chartRef.current
    if (!el) return
    if (document.fullscreenElement) document.exitFullscreen()
    else if (el.requestFullscreen) el.requestFullscreen()
  }
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * 960
    let i = Math.round(((px - 46) / 898) * 47)
    i = Math.max(0, Math.min(47, i))
    if (i !== hover) setHover(i)
  }
  const onLeave = () => setHover(null)

  // ---- KPIs ----
  const hiI = today.indexOf(Math.max(...today))
  const loI = today.indexOf(Math.min(...today))
  const k1 = chip(today[NOW], yday[NOW])
  const k2 = chip(avg(today), avg(yday))
  const k3 = chip(today[hiI], Math.max(...yday))
  const k4 = chip(today[loI], Math.min(...yday))

  // ---- chart ----
  const main = seg === 'today' ? today : seg === 'yday' ? yday : avg7
  const mainPath = seg === 'today' ? paths.today : seg === 'yday' ? paths.yday : paths.avg7
  const mainArea = seg === 'today' ? paths.todayA : seg === 'yday' ? paths.ydayA : paths.avg7A
  const ghostVis = ghostOn && seg === 'today'
  const mainLegend =
    seg === 'today'
      ? L === 'ja'
        ? '本日 Today'
        : 'Today 本日'
      : seg === 'yday'
        ? 'Yesterday 前日'
        : '7-day avg 7日平均'
  const tipOn = hover !== null && hover !== undefined
  const tipMainLabel = seg === 'today' ? 'Today' : seg === 'yday' ? 'Yesterday' : '7-day avg'

  let tip: {
    slot: string
    main: string
    ghost: string
    delta: string
    deltaS: React.CSSProperties
    style: React.CSSProperties
  } | null = null
  if (tipOn && hover !== null) {
    const d = chip(main[hover], yday[hover])
    tip = {
      slot: slotLabel(hover) + '–' + slotLabel(Math.min(47, hover + 1)),
      main: main[hover].toFixed(2),
      ghost: yday[hover].toFixed(2),
      delta: d.txt,
      deltaS: { ...d.style, marginTop: 0, padding: '1px 7px' },
      style: {
        position: 'absolute',
        top: 10,
        left: (X(hover) / 960) * 100 + '%',
        transform: 'translateX(-50%)',
        background: 'var(--tipBg)',
        color: '#FFFFFF',
        borderRadius: 8,
        padding: '8px 12px',
        fontSize: 12,
        pointerEvents: 'none',
        whiteSpace: 'nowrap',
        boxShadow: '0 8px 24px rgba(0,0,0,.3)',
        zIndex: 5,
      },
    }
  }

  const ghostOp = ghostVis ? 0.75 : 0
  const markerOp = seg === 'today' ? 1 : 0
  const markerCy = Math.round(Y(today[NOW]) * 10) / 10
  const tipOp = tipOn ? 1 : 0
  const guideX = tipOn && hover !== null ? Math.round(X(hover) * 10) / 10 : 0

  const ghostLegS: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    fontSize: 12,
    color: 'var(--tx2)',
    cursor: 'pointer',
    opacity: ghostVis ? 1 : 0.4,
    textDecoration: ghostVis ? 'none' : 'line-through',
  }

  // ---- pulse rows ----
  const pulse = useMemo(() => {
    return [...areas]
      .map((a) => ({ ...a, latest: liveSys.areasNow[a.key] ?? a.series[NOW], prev: yday[NOW] + a.off }))
      .sort((a, b) => b.latest - a.latest)
      .map((a, i) => {
        const mn = Math.min(...a.series)
        const mx = Math.max(...a.series)
        const pts = a.series
          .map(
            (v, j) =>
              ((j / 47) * 64).toFixed(1) + ',' + (15.5 - ((v - mn) / (mx - mn || 1)) * 13).toFixed(1),
          )
          .join(' ')
        const d = a.latest - a.prev
        const up = d > 0
        const col = dark ? a.dk || a.color : a.color
        return {
          key: a.key,
          n1: L === 'ja' ? a.ja : a.en,
          n2: L === 'ja' ? a.en : a.ja,
          color: col,
          price: a.latest.toFixed(2),
          points: pts,
          dTxt: (up ? '▲' : '▼') + Math.abs(d).toFixed(2),
          dStyle: {
            fontSize: 10.5,
            fontWeight: 600,
            color: up ? 'var(--up)' : 'var(--dn)',
            width: 44,
            textAlign: 'right' as const,
            fontFeatureSettings: "'tnum' 1",
            flexShrink: 0,
          },
          dotStyle: { width: 8, height: 8, borderRadius: 999, background: col, flexShrink: 0 },
          rowStyle: {
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '4px 6px',
            borderRadius: 8,
            cursor: 'pointer',
            background: i === 0 ? 'rgba(231,111,81,.10)' : 'transparent',
            minWidth: 0,
          } as React.CSSProperties,
        }
      })
  }, [L, dark, liveSys, yday])

  // ---- radar rows ----
  const tierColors: Record<string, string> = {
    METI: 'var(--ac)',
    OCCTO: dark ? '#7C9CD1' : '#4A6FA5',
    EGC: dark ? '#C77BD8' : '#7B2D8E',
  }
  const radarList =
    filter === 'upcoming'
      ? // only still-future meetings — a stale static snapshot can hold a meeting
        // whose date has since passed; don't present it as forthcoming.
        upcoming.filter((m) => daysFrom(m) >= 0)
      : meetings.filter((m) => (filter === 'followed' ? !!m.key && isFollowing(m.key) : true))
  const radar = radarList.map((m, i) => {
    const d = meetingDate(m)
    // Show a date only when it's the real published meeting date; a pending
    // meeting with no parsed date shows just its number (no misleading fallback).
    const dateStr = m.dateReal
      ? L === 'ja'
        ? `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
        : `${d.getDate()} ${MO[d.getMonth() + 1]} ${d.getFullYear()}`
      : ''
    const numStr = m.no ? (L === 'ja' ? `第${m.no}回` : `No. ${m.no}`) : ''
    const dd = daysFrom(m)
    const rel = m.sched && m.dateReal && dd >= 0 ? (L === 'ja' ? `あと${dd}日` : `in ${dd}d`) : ''
    const meta = [numStr, dateStr, rel].filter(Boolean).join(' · ')
    const following = !!m.key && isFollowing(m.key)
    return {
    key: (m.key || m.tier) + '-' + m.no + '-' + (m.date || i),
    rank: i + 1,
    comKey: m.key ?? null,
    following,
    n1: L === 'ja' ? m.ja : m.en,
    n2: L === 'ja' ? m.en : m.ja,
    meta,
    tier: m.tier,
    tori: !!m.tori,
    sched: !!m.sched,
    done: !!m.done,
    pending: !m.done && !m.sched,
    score: m.score,
    summary: m.done ? (L === 'ja' ? m.sJa : m.sEn) : '',
    cta: m.sched
      ? L === 'ja'
        ? '議題を見る →'
        : 'View agenda →'
      : m.done
        ? L === 'ja'
          ? '詳細を見る →'
          : 'Deep dive →'
        : L === 'ja'
          ? '会合を開く →'
          : 'Open meeting →',
    badgeStyle: {
      width: 26,
      height: 26,
      borderRadius: 999,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 12,
      fontWeight: 700,
      flexShrink: 0,
      marginTop: 2,
      background: i === 0 ? 'var(--ac)' : 'var(--bg2)',
      color: i === 0 ? '#FFFFFF' : 'var(--tx2)',
      fontFeatureSettings: "'tnum' 1",
    } as React.CSSProperties,
    barStyle: {
      width: m.score * 0.64 + 'px',
      height: '100%',
      borderRadius: 3,
      background: i === 0 ? 'var(--ac)' : 'var(--fnt3)',
    } as React.CSSProperties,
    tierDot: {
      width: 7,
      height: 7,
      borderRadius: 999,
      background: tierColors[m.tier],
      display: 'inline-block',
    } as React.CSSProperties,
    }
  })

  // ---- Recent & Scheduled timeline ----
  // Real-dated held meetings from the last ~13 weeks + all scheduled meetings,
  // positioned on a timeline centred on today (held to the left, scheduled to
  // the right). Only real dates are placed, so positions are temporally honest.
  const timelineItems = useMemo(() => {
    const recent = meetings
      .filter((m) => m.dateReal)
      .map((m) => ({ m, d: daysFrom(m) }))
      .filter((x) => x.d <= 0 && x.d >= -95)
    const sched = upcoming
      .filter((m) => m.dateReal)
      .map((m) => ({ m, d: daysFrom(m) }))
      .filter((x) => x.d >= 0)
    return [...recent, ...sched].sort((a, b) => a.d - b.d)
  }, [meetings, upcoming, todayMid])

  // Window includes today (0) with padding at both extremes.
  const tlDs = timelineItems.map((x) => x.d)
  const tlLo = Math.min(-5, ...tlDs) - 4
  const tlHi = Math.max(5, ...tlDs) + 4
  const tlSpan = tlHi - tlLo || 1
  const pctOf = (d: number) => 4 + ((d - tlLo) / tlSpan) * 92
  const todayPct = pctOf(0)

  const calItems = timelineItems.map((x, i) => {
    const m = x.m
    const pct = pctOf(x.d)
    const top = i % 2 === 0
    const future = x.d > 0
    const col = future ? 'var(--up)' : tierColors[m.tier]
    const shift = pct < 12 ? '0' : pct > 88 ? '-100%' : '-50%'
    const dt = meetingDate(m)
    const dateTxt = L === 'ja' ? `${dt.getMonth() + 1}月${dt.getDate()}日` : `${dt.getDate()} ${MO[dt.getMonth() + 1]}`
    const rel = future
      ? L === 'ja' ? `あと${x.d}日` : `in ${x.d}d`
      : x.d === 0
        ? L === 'ja' ? '本日' : 'today'
        : L === 'ja' ? `${-x.d}日前` : `${-x.d}d ago`
    const metaTxt = dateTxt + ' · ' + rel
    return {
      key: 'cal-' + (m.key || m.tier) + '-' + (m.date || i),
      name: shortLabel(m, L === 'ja'),
      meta: metaTxt,
      tip: (L === 'ja' ? m.ja : m.en) + ' · ' + metaTxt,
      dotS: {
        position: 'absolute',
        left: pct + '%',
        top: 58,
        width: 11,
        height: 11,
        borderRadius: 999,
        background: col,
        border: '2px solid var(--bg1)',
        transform: 'translateX(-50%)',
        zIndex: 2,
      } as React.CSSProperties,
      lineS: {
        position: 'absolute',
        left: pct + '%',
        top: top ? 40 : 66,
        height: 22,
        width: 2,
        background: 'var(--bd2)',
        transform: 'translateX(-50%)',
      } as React.CSSProperties,
      cardS: {
        position: 'absolute',
        left: pct + '%',
        top: top ? 6 : 90,
        transform: 'translateX(' + shift + ')',
        background: 'var(--bg3)',
        border: future ? '1px solid var(--up)' : '1px solid var(--bd)',
        borderRadius: 10,
        padding: '4px 11px',
        cursor: 'pointer',
        zIndex: 3,
        boxShadow: 'var(--sh1)',
        maxWidth: 168,
      } as React.CSSProperties,
    }
  })
  // Evenly spaced date ticks across the window.
  const calWeeks = Array.from({ length: 5 }, (_, k) => {
    const d = Math.round(tlLo + (tlSpan * k) / 4)
    const dt = new Date(todayMid)
    dt.setDate(dt.getDate() + d)
    const pct = pctOf(d)
    return {
      key: 'wk-' + k,
      label: MO[dt.getMonth() + 1] + ' ' + dt.getDate(),
      tickS: {
        position: 'absolute',
        left: pct + '%',
        top: 56,
        width: 1,
        height: 16,
        background: 'var(--bd2)',
      } as React.CSSProperties,
      labS: {
        position: 'absolute',
        left: pct + '%',
        top: 74,
        transform: 'translateX(-50%)',
        fontSize: 10,
        color: 'var(--fnt)',
        fontFeatureSettings: "'tnum' 1",
      } as React.CSSProperties,
    }
  })

  // ---- freshness rows ----
  // JEPX spot / Area prices freshness dates come from the same live snapshot that
  // drives the KPI tiles + chart (system.json date_today), not a hardcoded literal.
  const liveDate = liveSys.ready ? liveSys.dateToday : null
  const fresh = freshData.map((f) => ({
    key: f.en,
    label: L === 'ja' ? f.ja : f.en,
    sub: L === 'ja' ? f.subJa || f.subEn : f.subEn,
    value: liveDate && (f.en === 'JEPX spot' || f.en === 'Area prices') ? liveDate : f.v,
    ok: f.ok,
    delayed: !!f.delayed,
    dotStyle: {
      width: 7,
      height: 7,
      borderRadius: 999,
      background: f.ok ? 'var(--okDot)' : 'var(--warnDot)',
      flexShrink: 0,
    } as React.CSSProperties,
  }))

  // computed top-bar / pulse header values
  // System/Tokyo "now" are read from the same snapshot slot (liveSys.now) so the
  // spread is a valid same-moment comparison; fall back to the fixed slot only
  // before the live snapshot has loaded.
  const sysNowV = liveSys.now.system ?? today[NOW]
  const tokyoNowV = liveSys.now.tokyo ?? liveSys.areasNow[areas[0].key] ?? areas[0].series[NOW]
  const sysNow = sysNowV.toFixed(2)
  const tokyoNow = tokyoNowV.toFixed(2)
  const spread = (sysNowV - tokyoNowV).toFixed(2)

  return (
    <>
      {/* ============ SIDEBAR ============ */}
      <div style={s(`width:264px;flex-shrink:0;background:var(--bg1);border-right:1px solid var(--bd);flex-direction:column;padding:22px 16px 16px;overflow-y:auto;${collapsed ? 'display:none' : 'display:flex'}`)}>
        <div style={s('padding:0 8px')}>
          <div style={s('display:flex;align-items:center;gap:7px')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:23px;height:23px;color:var(--ac);flex-shrink:0"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`} />
            <span style={s('font-size:21px;font-weight:700;letter-spacing:.01em')}>JEMA</span>
          </div>
          <div style={s('font-size:9px;font-weight:600;letter-spacing:.14em;color:var(--mut);margin-top:3px;text-transform:uppercase')}>Japan Energy Market Analytics</div>
        </div>

        <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:26px 8px 8px')}>MENU · メニュー</div>
        <div style={s('display:flex;flex-direction:column;gap:3px')}>
          <div style={s('display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:600;color:var(--acT);background:var(--acTint);cursor:pointer;position:relative')}>
            <span style={s('position:absolute;left:-16px;top:8px;bottom:8px;width:3px;background:var(--ac);border-radius:0 2px 2px 0')}></span>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><rect x="3" y="3" width="7" height="9" rx="1"></rect><rect x="14" y="3" width="7" height="5" rx="1"></rect><rect x="14" y="12" width="7" height="9" rx="1"></rect><rect x="3" y="16" width="7" height="5" rx="1"></rect></svg>`} />
            <span>Market Overview</span>
            <span style={s('margin-left:auto;font-size:10.5px;font-weight:500;color:var(--acHi)')}>概況</span>
          </div>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={tMarket}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><path d="M3 3v18h18"></path><path d="M8 17v-3"></path><path d="M13 17V9"></path><path d="M18 17V5"></path></svg>`} />
            <span>Market Data</span>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;margin-left:auto;color:var(--mut);flex-shrink:0"><path d="M9 18l6-6-6-6"></path></svg>`} />
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={tCapacity}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><polygon points="12 2 22 8.5 12 15 2 8.5 12 2"></polygon><polyline points="2 14 12 20.5 22 14"></polyline></svg>`} />
            <span>Capacity &amp; Auctions</span>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;margin-left:auto;color:var(--mut);flex-shrink:0"><path d="M9 18l6-6-6-6"></path></svg>`} />
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={tPolicy}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><line x1="3" y1="22" x2="21" y2="22"></line><line x1="6" y1="18" x2="6" y2="11"></line><line x1="10" y1="18" x2="10" y2="11"></line><line x1="14" y1="18" x2="14" y2="11"></line><line x1="18" y1="18" x2="18" y2="11"></line><polygon points="12 2 20 7 4 7"></polygon></svg>`} />
            <span>Policy Deep Dive</span>
            <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>3</span>
          </Hoverable>
        </div>

        <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:22px 8px 8px')}>GENERAL · 全般</div>
        <div style={s('display:flex;flex-direction:column;gap:3px')}>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('watchlist')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon></svg>`} />
            <span>Watchlist</span>
            {watch.length > 0 && (
              <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>{watch.length}</span>
            )}
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={toggleNotif}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} />
            <span>Notifications</span>
            <span style={s('margin-left:auto;background:var(--acBadge);color:#FFFFFF;font-size:10px;font-weight:600;border-radius:999px;padding:1px 7px')}>2</span>
          </Hoverable>
          <Hoverable base="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;font-size:13.5px;font-weight:500;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('settings')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex-shrink:0"><circle cx="12" cy="12" r="3"></circle><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path></svg>`} />
            <span>Settings</span>
          </Hoverable>
        </div>

        <div style={s('flex:1')}></div>

        <Hoverable base="display:flex;align-items:center;gap:8px;padding:6px 12px;color:var(--mut);font-size:12px;cursor:pointer;border-radius:10px" hover="background:var(--bg2);color:var(--tx2)" onClick={toggleCollapsed}>
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;flex-shrink:0"><path d="M11 17l-5-5 5-5"></path><path d="M18 17l-5-5 5-5"></path></svg>`} />
          <span>Collapse · 折りたたむ</span>
        </Hoverable>

        <div style={s('background:linear-gradient(135deg,var(--navyA),var(--navyB));border-radius:16px;padding:15px 15px 13px;color:#FFFFFF;margin-top:12px')}>
          <div style={s("display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600")}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;color:#7FD4E8;flex-shrink:0"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14a9 3 0 0 0 18 0V5"></path><path d="M3 12a9 3 0 0 0 18 0"></path></svg>`} />
            Data freshness · データ鮮度
          </div>
          <div style={s("font-size:12px;color:rgba(255,255,255,.78);margin-top:6px")}>Last sync <span style={s("font-weight:600;color:#FFFFFF;font-feature-settings:'tnum' 1")}>06:10 JST</span></div>
          <div style={s('font-size:10.5px;color:rgba(255,255,255,.55);margin-top:2px')}>Hugging Face sync · GitHub Actions daily</div>
          <Hoverable base="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.35);color:#FFFFFF;border-radius:999px;padding:5px 13px;font-size:12px;font-weight:500;cursor:pointer;margin-top:10px" hover="background:rgba(255,255,255,.10)" onClick={tRefresh}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;flex-shrink:0"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>`} />
            Refresh · 更新
          </Hoverable>
        </div>
      </div>

      {/* ============ MAIN COLUMN ============ */}
      <div style={s('flex:1;min-width:0;display:flex;flex-direction:column;position:relative')}>

        {/* Top bar */}
        <div style={s('height:72px;flex-shrink:0;background:var(--bg1);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:18px;padding:0 28px;position:relative;z-index:30')}>
          <div style={s('font-size:13px;color:var(--mut);flex-shrink:0')}>Market Overview <span style={s('color:var(--fnt3)')}>·</span> マーケット概況</div>
          <div onClick={() => openOverlay('search')} style={s('flex:1;max-width:520px;display:flex;align-items:center;gap:9px;background:var(--bg0);border:1px solid var(--bd);border-radius:12px;padding:8px 14px;color:var(--mut);cursor:text')}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;flex-shrink:0"><circle cx="11" cy="11" r="8"></circle><path d="M21 21l-4.35-4.35"></path></svg>`} />
            <input readOnly onFocus={() => openOverlay('search')} placeholder="Search markets, areas, committees… 市場・エリア・委員会を検索…" style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:13px;background:transparent;color:var(--tx);min-width:0;cursor:text')} />
            <span style={s('border:1px solid var(--bd2);background:var(--bg1);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--mut);flex-shrink:0')}>⌘K</span>
          </div>
          <div style={s('flex:1')}></div>
          <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;flex-shrink:0" hover="background:var(--bg2)" onClick={toggleTheme} title="Toggle theme · テーマ切替">
            {dark && (
              <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`} />
            )}
            {!dark && (
              <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`} />
            )}
          </Hoverable>
          <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;position:relative;flex-shrink:0" hover="background:var(--bg2)" onClick={toggleNotif}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} />
            <span style={s('position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:999px;background:var(--ac);border:1.5px solid var(--bg1)')}></span>
          </Hoverable>
          <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;flex-shrink:0')}>
            <span style={segBase(L === 'ja')} onClick={() => setLang('ja')}>日本語</span>
            <span style={segBase(L === 'en')} onClick={() => setLang('en')}>English</span>
          </div>
          <div style={s('display:flex;align-items:center;gap:10px;flex-shrink:0')}>
            <div style={s('width:34px;height:34px;border-radius:999px;background:var(--avatar);color:#FFFFFF;display:flex;align-items:center;justify-content:center;font-size:11.5px;font-weight:600')}>AN</div>
            <div style={s('line-height:1.25')}>
              <div style={s('font-size:13px;font-weight:600')}>Analyst</div>
              <div style={s('font-size:11px;color:var(--mut)')}>analyst@example.jp</div>
            </div>
          </div>

          {/* Notifications popover */}
          {showNotif && (
            <div style={s('position:absolute;right:24px;top:66px;width:360px;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shPop);padding:16px;z-index:60')}>
              <div style={s('font-size:14px;font-weight:600')}>Notifications <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>通知</span></div>
              <div style={s('font-size:11px;font-weight:600;letter-spacing:.05em;color:var(--mut);margin:12px 0 6px')}>NEW POLICY MEETINGS · 新規の会合</div>
              <div style={s('display:flex;flex-direction:column;gap:2px')}>
                <Hoverable base="display:flex;gap:9px;align-items:flex-start;padding:8px;border-radius:10px;cursor:pointer" hover="background:var(--hov)" onClick={tPolicy}>
                  <span style={s('width:7px;height:7px;border-radius:999px;background:var(--ac);margin-top:6px;flex-shrink:0')}></span>
                  <div style={s('flex:1;min-width:0')}>
                    <div style={s('font-size:12.5px;font-weight:500')}>Electricity &amp; Gas Basic Policy Subcommittee</div>
                    <div style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>No. 84 · 27 Jun 2026 · METI</div>
                  </div>
                  <span style={s('font-size:10px;font-weight:600;background:var(--acTint);color:var(--acT);border-radius:6px;padding:1px 6px;flex-shrink:0')}>New</span>
                </Hoverable>
                <Hoverable base="display:flex;gap:9px;align-items:flex-start;padding:8px;border-radius:10px;cursor:pointer" hover="background:var(--hov)" onClick={tPolicy}>
                  <span style={s('width:7px;height:7px;border-radius:999px;background:var(--ac);margin-top:6px;flex-shrink:0')}></span>
                  <div style={s('flex:1;min-width:0')}>
                    <div style={s('font-size:12.5px;font-weight:500')}>E&amp;G Market Surveillance Commission</div>
                    <div style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>No. 58 · 24 Jun 2026 · とりまとめ</div>
                  </div>
                  <span style={s('font-size:10px;font-weight:600;background:var(--acTint);color:var(--acT);border-radius:6px;padding:1px 6px;flex-shrink:0')}>New</span>
                </Hoverable>
              </div>
              <div style={s('display:flex;align-items:center;gap:6px;font-size:11px;font-weight:600;letter-spacing:.05em;color:var(--mut);margin:12px 0 6px')}>PRICE ALERTS · 価格アラート <span style={s('font-size:9.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:6px;padding:1px 6px;letter-spacing:0')}>PROPOSED</span></div>
              <div style={s('display:flex;gap:9px;align-items:flex-start;padding:8px;border-radius:10px;background:var(--bg3)')}>
                <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;color:#F4A261;margin-top:2px;flex-shrink:0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`} />
                <div style={s('flex:1;min-width:0')}>
                  <div style={s("font-size:12.5px;font-weight:500;font-feature-settings:'tnum' 1")}>TEPCO JEPX avg &gt; ¥18/kWh (Daily)</div>
                  <div style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>Rule armed · needs threshold-evaluation job</div>
                </div>
              </div>
              <div style={s('display:flex;justify-content:space-between;border-top:1px solid var(--dv);margin-top:12px;padding-top:10px')}>
                <Hoverable as="span" base="font-size:12px;color:var(--tx2);cursor:pointer" hover="color:var(--acT)" onClick={toggleNotif}>Mark all read · すべて既読に</Hoverable>
                <span style={s('font-size:12px;font-weight:600;color:var(--acT);cursor:pointer')} onClick={tPolicy}>View all →</span>
              </div>
            </div>
          )}
        </div>

        {/* Scrollable content */}
        <div style={s('flex:1;overflow-y:auto;padding:26px 32px 40px')}>
          <div style={s('max-width:1500px;margin:0 auto;display:flex;flex-direction:column;gap:22px')}>

            {/* A · Page header */}
            <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:16px')}>
              <div>
                <div style={s('display:flex;align-items:baseline;gap:10px')}>
                  <span style={s('font-size:26px;font-weight:700;letter-spacing:-.01em')}>Market Overview</span>
                  <span style={s('font-size:15px;font-weight:500;color:var(--mut)')}>マーケット概況</span>
                </div>
                <div style={s('font-size:13.5px;color:var(--tx2);margin-top:2px')}>JEPX system price &amp; the latest policy-committee signals · JEPXシステム価格と政策委員会の最新動向</div>
                <div style={s("display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--mut);margin-top:8px;background:var(--bg1);border:1px solid var(--bd);border-radius:999px;padding:3px 11px;font-feature-settings:'tnum' 1")}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;flex-shrink:0"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`} />
                  Updated {liveSys.dateToday ?? '—'} · 更新
                </div>
              </div>
              <div style={s('display:flex;gap:10px;flex-shrink:0;padding-top:4px')}>
                <Hoverable base="background:var(--ac);color:#FFFFFF;border-radius:999px;padding:9px 20px;font-size:13.5px;font-weight:600;cursor:pointer;box-shadow:var(--sh1a)" hover="background:var(--acT);box-shadow:var(--sh2)" onClick={tMarket}>Open Market Data</Hoverable>
                <Hoverable base="background:var(--bg1);border:1px solid var(--fnt3);color:var(--tx);border-radius:999px;padding:9px 20px;font-size:13.5px;font-weight:600;cursor:pointer" hover="background:var(--acTint2);border-color:var(--ac)" onClick={tPolicy}>All Committees</Hoverable>
              </div>
            </div>

            {/* B · KPI strip */}
            <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
              <Hoverable base="background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;position:relative;box-shadow:var(--sh1a);cursor:pointer;transition:box-shadow .15s" hover="box-shadow:var(--sh2a)" onClick={tMarket}>
                <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                  <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>Latest system price<br />最新システム価格 <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px;opacity:.85;vertical-align:-1px"><title>JEPX spot is day-ahead; 'latest' = the most recent 30-min slot of today. All 48 slots clear the prior day. · JEPXスポットは前日約定。「最新」は本日の最新30分コマ。</title><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`} /></div>
                  <span style={s('width:30px;height:30px;border-radius:999px;border:1px solid rgba(255,255,255,.45);display:flex;align-items:center;justify-content:center;flex-shrink:0')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>`} /></span>
                </div>
                <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{today[NOW].toFixed(2)} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>¥/kWh</span></div>
                <div style={s("font-size:11px;color:rgba(255,255,255,.75);margin-top:2px;font-feature-settings:'tnum' 1")}>slot 14:30 · vs same slot y'day</div>
                <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{k1.txt}</span>
              </Hoverable>
              <Hoverable base="background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);cursor:pointer;transition:box-shadow .15s" hover="box-shadow:var(--sh2)" onClick={tMarket}>
                <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                  <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Today's average<br />本日平均</div>
                  <Hoverable as="span" base="width:30px;height:30px;border-radius:999px;border:1px solid var(--bd);display:flex;align-items:center;justify-content:center;color:var(--mut);flex-shrink:0" hover="color:var(--ac);background:var(--bg0)"><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>`} /></Hoverable>
                </div>
                <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{avg(today).toFixed(2)} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kWh</span></div>
                <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>48 cleared slots · vs y'day avg</div>
                <span style={k2.style}>{k2.txt}</span>
              </Hoverable>
              <Hoverable base="background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);cursor:pointer;transition:box-shadow .15s" hover="box-shadow:var(--sh2)" onClick={tMarket}>
                <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                  <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Today's high<br />本日高値</div>
                  <span style={s('width:30px;height:30px;border-radius:999px;border:1px solid var(--bd);display:flex;align-items:center;justify-content:center;color:var(--mut);flex-shrink:0')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>`} /></span>
                </div>
                <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{today[hiI].toFixed(2)} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kWh</span></div>
                <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>at {slotLabel(hiI)} · vs y'day high</div>
                <span style={k3.style}>{k3.txt}</span>
              </Hoverable>
              <Hoverable base="background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);cursor:pointer;transition:box-shadow .15s" hover="box-shadow:var(--sh2)" onClick={tMarket}>
                <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                  <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Today's low<br />本日安値</div>
                  <span style={s('width:30px;height:30px;border-radius:999px;border:1px solid var(--bd);display:flex;align-items:center;justify-content:center;color:var(--mut);flex-shrink:0')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>`} /></span>
                </div>
                <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{today[loI].toFixed(2)} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kWh</span></div>
                <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>at {slotLabel(loI)} · vs y'day low</div>
                <span style={k4.style}>{k4.txt}</span>
              </Hoverable>
            </div>

            {/* Row: C intraday chart + D market pulse */}
            <div style={s('display:grid;grid-template-columns:2fr 1fr;gap:20px;align-items:stretch')}>

              {/* C · System-price intraday */}
              <div ref={chartRef} style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);min-height:360px;display:flex;flex-direction:column')}>
                <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                  <div>
                    <div style={s('font-size:16px;font-weight:600')}>System Price — Intraday <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>システム価格 日中推移</span></div>
                    <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>48 half-hour slots · ¥/kWh · day-ahead 前日約定</div>
                  </div>
                  <div style={s('display:flex;align-items:center;gap:10px;flex-shrink:0')}>
                    <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                      <span style={segBase(seg === 'today')} onClick={() => { setSeg('today'); setHover(null) }}>Today</span>
                      <span style={segBase(seg === 'yday')} onClick={() => { setSeg('yday'); setHover(null) }}>Yesterday</span>
                      <span style={segBase(seg === 'avg7')} onClick={() => { setSeg('avg7'); setHover(null) }}>7-day avg</span>
                    </div>
                    <Hoverable as="span" base="width:30px;height:30px;border-radius:8px;border:1px solid var(--bd);display:flex;align-items:center;justify-content:center;color:var(--mut);cursor:pointer" hover="color:var(--ac);background:var(--bg0)" onClick={fs} title="Fullscreen · 全画面"><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M8 3H5a2 2 0 0 0-2 2v3"></path><path d="M21 8V5a2 2 0 0 0-2-2h-3"></path><path d="M3 16v3a2 2 0 0 0 2 2h3"></path><path d="M16 21h3a2 2 0 0 0 2-2v-3"></path></svg>`} /></Hoverable>
                  </div>
                </div>

                <div style={s('position:relative;flex:1;margin-top:14px')}>
                  <svg viewBox="0 0 960 320" style={s('width:100%;height:auto;display:block')} onMouseMove={onMove} onMouseLeave={onLeave}>
                    <defs>
                      <linearGradient id="jemaFade" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#00A5CF" stopOpacity="0.20"></stop>
                        <stop offset="100%" stopColor="#00A5CF" stopOpacity="0.01"></stop>
                      </linearGradient>
                    </defs>
                    <g style={{ color: 'var(--grid)' }}>
                      <line x1="46" y1="69" x2="944" y2="69" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="138" x2="944" y2="138" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="207" x2="944" y2="207" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="276" x2="944" y2="276" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                    </g>
                    <g style={{ color: 'var(--mut)' }}>
                      <text x="38" y="73" textAnchor="end" fontSize="11" fill="currentColor">¥20</text>
                      <text x="38" y="142" textAnchor="end" fontSize="11" fill="currentColor">¥15</text>
                      <text x="38" y="211" textAnchor="end" fontSize="11" fill="currentColor">¥10</text>
                      <text x="38" y="280" textAnchor="end" fontSize="11" fill="currentColor">¥5</text>
                      <text x="46" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">00:00</text>
                      <text x="198.9" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">04:00</text>
                      <text x="351.7" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">08:00</text>
                      <text x="504.6" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">12:00</text>
                      <text x="657.4" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">16:00</text>
                      <text x="810.2" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">20:00</text>
                      <text x="930" y="310" textAnchor="middle" fontSize="10.5" fill="currentColor">23:30</text>
                    </g>
                    <rect x="590.6" y="14" width="19.1" height="276" fill="rgba(0,165,207,0.08)" opacity={markerOp}></rect>
                    <path d={mainArea} fill="url(#jemaFade)"></path>
                    <path d={paths.yday} fill="none" stroke="#9AA5B5" strokeWidth="1.6" strokeDasharray="5 4" opacity={ghostOp}></path>
                    <path d={mainPath} fill="none" stroke="#00A5CF" strokeWidth="2.4" strokeLinejoin="round"></path>
                    <line x1={guideX} x2={guideX} y1="14" y2="290" stroke="#94A3B8" strokeWidth="1" strokeDasharray="3 3" opacity={tipOp}></line>
                    <circle style={{ color: 'var(--bg1)' }} cx="600.1" cy={markerCy} r="4.5" fill="#00A5CF" stroke="currentColor" strokeWidth="2" opacity={markerOp}></circle>
                  </svg>
                  {tipOn && tip && (
                    <div style={tip.style}>
                      <div style={s("font-weight:600;font-feature-settings:'tnum' 1")}>{tip.slot} <span style={s('font-weight:400;color:rgba(255,255,255,.65)')}>JST</span></div>
                      <div style={s("display:flex;justify-content:space-between;gap:16px;margin-top:3px;font-feature-settings:'tnum' 1")}><span style={s('color:rgba(255,255,255,.75)')}>{tipMainLabel}</span><span style={s('font-weight:600')}>¥{tip.main}</span></div>
                      <div style={s("display:flex;justify-content:space-between;gap:16px;font-feature-settings:'tnum' 1")}><span style={s('color:rgba(255,255,255,.75)')}>Yesterday</span><span>¥{tip.ghost}</span></div>
                      <div style={s("margin-top:2px;font-feature-settings:'tnum' 1")}><span style={tip.deltaS}>{tip.delta}</span></div>
                    </div>
                  )}
                </div>

                <div style={s('display:flex;align-items:center;gap:18px;margin-top:10px;padding-top:12px;border-top:1px solid var(--dv)')}>
                  <span style={s('display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--tx2)')}><span style={s('width:20px;height:3px;border-radius:2px;background:#00A5CF')}></span>{mainLegend}</span>
                  <span style={ghostLegS} onClick={toggleGhost}><span style={s('width:20px;height:0;border-top:2px dashed #9AA5B5')}></span>Yesterday (ghost) 前日</span>
                  <span style={s('margin-left:auto;font-size:11px;color:var(--mut)')}>Click legend to toggle · slot click deep-links to Market Data</span>
                </div>
              </div>

              {/* D · Market Pulse */}
              <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);display:flex;flex-direction:column;min-width:0')}>
                <div style={s('font-size:16px;font-weight:600')}>Market Pulse <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>スポット概況</span></div>
                <div style={s('display:flex;justify-content:space-between;align-items:center;margin-top:12px')}>
                  <span style={s('font-size:12.5px;color:var(--mut)')}>System now · システム</span>
                  <span style={s("font-size:15px;font-weight:700;font-feature-settings:'tnum' 1")}>¥{sysNow}</span>
                </div>
                <div style={s('display:flex;justify-content:space-between;align-items:center;margin-top:7px')}>
                  <span style={s('font-size:12.5px;color:var(--mut)')}>Tokyo now · 東京</span>
                  <span style={s("font-size:15px;font-weight:700;font-feature-settings:'tnum' 1")}>¥{tokyoNow}</span>
                </div>
                <div style={s('display:flex;justify-content:space-between;align-items:center;margin-top:7px')}>
                  <span style={s('font-size:12.5px;color:var(--mut)')}>Sys–Tokyo spread · 価格差</span>
                  <span style={s("font-size:15px;font-weight:700;color:var(--dn);font-feature-settings:'tnum' 1")}>{spread}</span>
                </div>
                <div style={s('height:1px;background:var(--dv);margin:13px 0 9px')}></div>
                <div style={s('font-size:11.5px;font-weight:600;color:var(--mut);letter-spacing:.04em;margin-bottom:4px')}>PER-AREA PRICES (9) · エリア別価格 <span style={s('font-weight:400;letter-spacing:0')}>— ¥/kWh, latest slot</span></div>
                <div style={s('display:flex;flex-direction:column;min-width:0')}>
                  {pulse.map((row) => (
                    <Hoverable key={row.key} base="" hover="background:var(--hov)" style={row.rowStyle} onClick={tMarket}>
                      <span style={row.dotStyle}></span>
                      <span style={s('font-size:13px;font-weight:500;width:76px;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{row.n1}</span>
                      <span style={s('font-size:10.5px;color:var(--mut);width:40px;flex-shrink:0')}>{row.n2}</span>
                      <svg viewBox="0 0 64 18" style={s('width:64px;height:18px;flex-shrink:0;margin-left:auto')}><polyline points={row.points} fill="none" stroke={row.color} strokeWidth="1.5"></polyline></svg>
                      <span style={s("font-size:13px;font-weight:600;width:46px;text-align:right;font-feature-settings:'tnum' 1;flex-shrink:0")}>{row.price}</span>
                      <span style={row.dStyle}>{row.dTxt}</span>
                    </Hoverable>
                  ))}
                </div>
                <div style={s('font-size:11px;color:var(--mut);margin-top:8px')}>Sorted by latest price · highest area tinted · click row → Market Data</div>
              </div>
            </div>

            {/* Recent & Scheduled meetings timeline */}
            <div style={s('background:var(--bg1);border-radius:20px;padding:18px 20px 10px;box-shadow:var(--sh1)')}>
              <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                <div>
                  <div style={s('font-size:16px;font-weight:600')}>Recent &amp; Scheduled <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>直近・開催予定</span></div>
                  <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Held meetings &amp; scheduled sessions · click → Policy Deep Dive · 開催済みと開催予定の会合</div>
                </div>
                <Hoverable base="display:inline-flex;align-items:center;gap:7px;border:1px solid var(--bd2);color:var(--tx2);border-radius:999px;padding:5px 14px;font-size:12px;font-weight:600;cursor:pointer;flex-shrink:0" hover="border-color:var(--ac);color:var(--acT)" onClick={tIcs}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;flex-shrink:0"><rect x="3" y="4" width="18" height="18" rx="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`} />Add to calendar · ICS
                </Hoverable>
              </div>
              {calItems.length === 0 ? (
                <div style={s('height:96px;display:flex;align-items:center;justify-content:center;font-size:12.5px;color:var(--mut);text-align:center')}>
                  {L === 'ja' ? '直近・開催予定の会合はありません' : 'No recent or scheduled meetings with dates yet'}
                </div>
              ) : (
                <div style={s('position:relative;height:128px;margin-top:6px')}>
                  <div style={s('position:absolute;left:0;right:0;top:63px;height:2px;background:var(--dv);border-radius:1px')}></div>
                  {calWeeks.map((w) => (
                    <React.Fragment key={w.key}>
                      <div style={w.tickS}></div>
                      <div style={w.labS}>{w.label}</div>
                    </React.Fragment>
                  ))}
                  <div style={{ position: 'absolute', left: todayPct + '%', top: 48, width: 2, height: 32, background: 'var(--ac)', borderRadius: 1, transform: 'translateX(-50%)' }}></div>
                  <div style={{ position: 'absolute', left: todayPct + '%', top: 84, fontSize: 10, fontWeight: 600, color: 'var(--acT)', whiteSpace: 'nowrap', transform: 'translateX(-50%)' }}>Today 本日</div>
                  {calItems.map((cm) => (
                    <React.Fragment key={cm.key}>
                      <div style={cm.lineS}></div>
                      <div style={cm.dotS}></div>
                      <div style={cm.cardS} onClick={tPolicy} title={cm.tip}>
                        <div style={s('font-size:11.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{cm.name}</div>
                        <div style={s("font-size:10px;color:var(--mut);white-space:nowrap;font-feature-settings:'tnum' 1")}>{cm.meta}</div>
                      </div>
                    </React.Fragment>
                  ))}
                </div>
              )}
            </div>

            {/* AI Daily Brief (PROPOSED, tweakable) */}
            {showBrief && (
              <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);display:flex;align-items:center;gap:18px')}>
                <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="width:34px;height:34px;color:var(--fnt3);flex-shrink:0"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>`} />
                <div style={s('flex:1')}>
                  <div style={s('display:flex;align-items:center;gap:8px;font-size:15px;font-weight:600')}>AI Daily Brief <span style={s('font-size:12px;font-weight:400;color:var(--mut)')}>AI日次ブリーフ</span><span style={s('font-size:9.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:6px;padding:1px 7px')}>PROPOSED</span></div>
                  <div style={s('font-size:12.5px;color:var(--mut);margin-top:2px')}>Today's AI brief hasn't been generated yet — daily narrative generation is not wired. · 本日のAIブリーフは未生成です — 日次ナラティブ生成は準備中。</div>
                </div>
                <span style={s('border:1px solid var(--bd);color:var(--fnt2);border-radius:999px;padding:7px 16px;font-size:12.5px;font-weight:500;cursor:not-allowed;flex-shrink:0')} title="Coming soon · 近日公開">Generate · 生成</span>
              </div>
            )}

            {/* Row: E radar + F freshness */}
            <div style={s('display:grid;grid-template-columns:2fr 1fr;gap:20px;align-items:start')}>

              {/* E · METI Committee Radar */}
              <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                <div style={s('display:flex;justify-content:space-between;align-items:flex-start;position:relative')}>
                  <div>
                    <div style={s('font-size:16px;font-weight:600')}>METI Committee Radar <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>委員会レーダー</span></div>
                    <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Recent meetings, ranked by importance · 重要度順・直近の会合</div>
                    <div style={s('font-size:11px;color:var(--fnt);margin-top:3px')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:11px;height:11px;vertical-align:-1px"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg>`} /> View data not connected — ranked by recency &amp; institutional weight · 視聴回数データ未接続</div>
                  </div>
                  <Hoverable as="span" base="width:28px;height:28px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--mut);cursor:pointer;flex-shrink:0" hover="background:var(--bg2);color:var(--acT)" onClick={toggleWhy} title="Why this ranking? · この順位の理由"><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:17px;height:17px"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`} /></Hoverable>
                  {showWhy && (
                    <div style={s("position:absolute;right:0;top:34px;width:330px;background:var(--bg1);border:1px solid var(--bd);border-radius:14px;box-shadow:var(--shPop);padding:15px;z-index:40;font-size:12px;color:var(--tx2)")}>
                      <div style={s('font-size:13px;font-weight:600;color:var(--tx)')}>Why this ranking? <span style={s('font-weight:400;color:var(--mut)')}>この順位の理由</span></div>
                      <div style={s('margin-top:7px;line-height:1.55')}>Importance <span style={s("font-feature-settings:'tnum' 1")}>I ∈ [0,100]</span> = institutional tier (0.35) + recency, 30-day half-life (0.25) + activity (0.15) + decision density (0.10) + summary freshness (0.05) + views (0.10, <span style={s('color:var(--warnTx)')}>proposed</span>).</div>
                      <div style={s('margin-top:7px;line-height:1.55;color:var(--mut)')}>Views are a proxy for attention from METI's official YouTube — not an official significance measure. While unavailable, w_V = 0 and remaining weights re-normalize. · 視聴回数はMETI公式YouTubeの推定注目度です。</div>
                      <div style={s('margin-top:9px;font-weight:600;color:var(--fnt2);cursor:not-allowed')} title="Coming soon · 近日公開">Adjust weighting · 重み付けを調整 →</div>
                    </div>
                  )}
                </div>

                <div style={s('display:flex;gap:6px;margin:12px 0 4px')}>
                  <span style={filterChipBase(filter === 'followed')} onClick={() => setFilter('followed')}>Followed フォロー中</span>
                  <span style={filterChipBase(filter === 'all')} onClick={() => setFilter('all')}>All tracked 全追跡</span>
                  <span style={filterChipBase(filter === 'upcoming')} onClick={() => setFilter('upcoming')}>Upcoming 開催予定</span>
                </div>

                <div style={s('display:flex;flex-direction:column')}>
                  {radar.length === 0 && (
                    <div style={s('padding:22px 4px;font-size:12.5px;color:var(--mut);text-align:center;border-top:1px solid var(--dv)')}>
                      {filter === 'followed'
                        ? L === 'ja'
                          ? 'フォロー中の委員会はありません — 星をクリックしてフォロー'
                          : 'No followed committees yet — tap the star on a committee to follow it'
                        : L === 'ja'
                          ? '開催予定の会合はありません'
                          : 'No scheduled meetings right now'}
                    </div>
                  )}
                  {radar.map((m) => (
                    <div key={m.key} style={s('display:flex;gap:12px;align-items:flex-start;padding:12px 4px;border-top:1px solid var(--dv)')}>
                      <span style={m.badgeStyle}>{m.rank}</span>
                      <div style={s('flex:1;min-width:0')}>
                        <div style={s('display:flex;align-items:center;gap:7px;min-width:0')}>
                          <span style={s('font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{m.n1}</span>
                          {m.comKey && (
                            <span
                              onClick={(e) => { e.stopPropagation(); if (m.comKey) toggleFollow(m.comKey) }}
                              title={m.following ? 'Following · フォロー中（クリックで解除）' : 'Follow · フォローする'}
                              style={{ display: 'inline-flex', alignItems: 'center', cursor: 'pointer', flexShrink: 0, color: m.following ? 'var(--ac)' : 'var(--fnt3)' }}
                            >
                              <RawSvg html={`<svg viewBox="0 0 24 24" fill="${m.following ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon></svg>`} />
                            </span>
                          )}
                        </div>
                        <div style={s('font-size:11.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{m.n2}</div>
                        <div style={s("display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--mut);margin-top:3px;font-feature-settings:'tnum' 1")}>
                          <span>{m.meta}</span>
                          <span style={s('display:inline-flex;align-items:center;gap:4px')}><span style={m.tierDot}></span>{m.tier}</span>
                          {m.tori && (<span style={s('font-size:10.5px;font-weight:600;background:var(--acTint);color:var(--acT);border-radius:6px;padding:1px 7px')}>とりまとめ</span>)}
                          {m.sched && (<span style={s('font-size:10.5px;font-weight:600;background:var(--upBg);color:var(--up);border-radius:6px;padding:1px 7px')}>Scheduled 開催予定</span>)}
                        </div>
                        {m.done && (
                          <div style={s('font-size:12.5px;color:var(--tx2);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{m.summary}</div>
                        )}
                        {m.pending && (
                          <div style={s('font-size:12.5px;color:var(--fnt);font-style:italic;margin-top:4px')}>Summary pending · 要約待ち</div>
                        )}
                      </div>
                      <div style={s('display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex-shrink:0;padding-top:2px')}>
                        <div style={s('display:flex;align-items:center;gap:6px')}>
                          <div style={s('width:64px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden')}><div style={m.barStyle}></div></div>
                          <span style={s("font-size:11px;font-weight:600;color:var(--mut);font-feature-settings:'tnum' 1;width:18px;text-align:right")}>{m.score}</span>
                        </div>
                        <Hoverable as="span" base="font-size:12.5px;font-weight:600;color:var(--acT);cursor:pointer;white-space:nowrap" hover="color:var(--ac)" onClick={tPolicy}>{m.cta}</Hoverable>
                      </div>
                    </div>
                  ))}
                </div>
                <div style={s('text-align:center;border-top:1px solid var(--dv);padding-top:12px;margin-top:2px')}>
                  <Hoverable as="span" base="font-size:12.5px;font-weight:600;color:var(--acT);cursor:pointer" hover="color:var(--ac)" onClick={tPolicy}>See all meetings · 全ての会合を見る →</Hoverable>
                </div>
              </div>

              {/* F · Data freshness rail */}
              <div style={s('background:linear-gradient(150deg,var(--navyA) 0%,var(--navyB) 100%);border-radius:20px;padding:20px;color:#FFFFFF;box-shadow:var(--sh1a)')}>
                <div style={s('font-size:16px;font-weight:600')}>Data Freshness <span style={s('font-size:12.5px;font-weight:400;color:rgba(255,255,255,.55)')}>データ鮮度</span></div>
                <div style={s('font-size:11.5px;color:rgba(255,255,255,.55);margin-top:1px')}>Provenance &amp; last ingest · 取得元と最終更新</div>
                <div style={s('display:flex;flex-direction:column;margin-top:12px')}>
                  {fresh.map((f) => (
                    <div key={f.key} style={s('display:flex;justify-content:space-between;align-items:center;gap:10px;padding:7px 0;border-top:1px solid rgba(255,255,255,.10)')}>
                      <span style={s('display:flex;align-items:center;gap:8px;min-width:0')}>
                        <span style={f.dotStyle}></span>
                        <span style={s('font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{f.label} <span style={s('font-size:10.5px;color:rgba(255,255,255,.45)')}>{f.sub}</span></span>
                      </span>
                      {f.ok && (
                        <span style={s("font-size:11.5px;color:rgba(255,255,255,.78);font-feature-settings:'tnum' 1;flex-shrink:0")}>{f.value}</span>
                      )}
                      {f.delayed && (
                        <span style={s("font-size:10.5px;font-weight:600;background:rgba(240,182,87,.20);color:#F0C07A;border-radius:6px;padding:1px 8px;flex-shrink:0;font-feature-settings:'tnum' 1")}>{f.value} · delayed 遅延</span>
                      )}
                    </div>
                  ))}
                </div>
                <div style={s('border-top:1px solid rgba(255,255,255,.14);margin-top:6px;padding-top:11px;font-size:11px;color:rgba(255,255,255,.55);line-height:1.6')}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:11px;height:11px;vertical-align:-1px"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`} /> All times JST · Synced via Hugging Face · daily GitHub Actions cron<br />JEPXスポットは前日約定・毎日更新
                </div>
                <Hoverable base="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(255,255,255,.35);color:#FFFFFF;border-radius:999px;padding:6px 15px;font-size:12.5px;font-weight:500;cursor:pointer;margin-top:12px" hover="background:rgba(255,255,255,.10)" onClick={tRefresh}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;flex-shrink:0"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>`} />Refresh · 更新
                </Hoverable>
              </div>
            </div>

          </div>
        </div>
      </div>
    </>
  )
}
