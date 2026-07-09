// Ported from screens/policy-deep-dive.html
import { useState, type ReactNode } from 'react'
import { s, Hoverable, RawSvg, type CSS } from '../lib/style'
import { useApp } from '../lib/app'
import {
  committees as fxCommittees,
  meetings as fxMeetings,
  untracked as fxUntracked,
  upcoming as fxUpcoming,
  type Meeting,
  type Upcoming,
} from './PolicyDeepDive.data'
import { usePolicyLive } from './PolicyDeepDive.live'
import { downloadIcs } from '../lib/download'

type AnyMeeting = Meeting | Upcoming

const MONTHS = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// dUntil: days between a date string and 2026-07-02 (the export's "today")
function dUntil(ds: string): number {
  return Math.round((new Date(ds).getTime() - new Date(2026, 6, 2).getTime()) / 864e5)
}

// Minimal markdown → React for the committee-level synthesis (raw markdown from
// NotebookLM). Handles `#`/`##`/`###` headings, `-`/`•`/`*` bullets, and blank-line
// paragraphs — no dependency. Inline `**bold**` is stripped to plain text.
function renderMd(md: string): ReactNode[] {
  const strip = (t: string) => t.replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
  const out: ReactNode[] = []
  const lines = (md || '').replace(/\r/g, '').split('\n')
  let para: string[] = []
  const flush = () => {
    if (para.length) {
      out.push(
        <div key={'p' + out.length} style={s('font-size:12.5px;color:var(--tx2);margin-top:6px;line-height:1.6')}>
          {strip(para.join(' '))}
        </div>,
      )
      para = []
    }
  }
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) {
      flush()
      continue
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line)
    if (h) {
      flush()
      out.push(
        <div key={'h' + out.length} style={s('font-size:13px;font-weight:600;color:var(--tx);margin-top:11px')}>
          {strip(h[2])}
        </div>,
      )
      continue
    }
    const b = /^[-•*]\s+(.*)$/.exec(line)
    if (b) {
      flush()
      out.push(
        <div key={'b' + out.length} style={s('display:flex;gap:8px;font-size:12.5px;color:var(--tx2);margin-top:4px;line-height:1.55')}>
          <span style={s('width:5px;height:5px;border-radius:999px;background:var(--ac);margin-top:7px;flex-shrink:0')}></span>
          <span style={s('flex:1')}>{strip(b[1])}</span>
        </div>,
      )
      continue
    }
    para.push(line)
  }
  flush()
  return out
}

export function PolicyDeepDiveScreen() {
  const { lang, setLang, theme, toggleTheme, setScreen, toast, openOverlay, isFollowing, toggleFollow, interactive } = useApp()
  const dark = theme === 'dark'
  const L: 'en' | 'ja' = lang

  // ---- local state (DCLogic defaults) ----
  const [committee, setCommittee] = useState('all')
  const [meeting, setMeeting] = useState('egmsc58')
  const [followedOnly, setFollowedOnly] = useState(false)
  const [jpOpen, setJpOpen] = useState(false)
  const [q, setQ] = useState('')
  const [comQ, setComQ] = useState('') // committee-name search (explorer)
  const [coverage, setCoverage] = useState<'tracked' | 'all'>('tracked')
  const [queued, setQueued] = useState<Record<string, boolean>>({})
  // Detail pane: 'committee' shows the committee-level synthesis overview; 'meeting'
  // shows one session's digest. Selecting a committee vs a session flips it.
  const [detailMode, setDetailMode] = useState<'committee' | 'meeting'>('committee')
  const [synthJpOpen, setSynthJpOpen] = useState(false)
  // Working filters (were placeholder toasts): committee dropdown + date-range dropdown.
  const [comOpen, setComOpen] = useState(false)
  const [dateOpen, setDateOpen] = useState(false)
  const [dateFilter, setDateFilter] = useState<'all' | '30d' | '90d' | 'year' | 'upcoming'>('all')

  // showAudioCard default prop = true
  const showAudioCard = true

  // ---- live policy data (falls back to fixtures while loading) ----
  // Interactive (local master) reads the live DB via /api/policy/deepdive; the
  // read-only deploy reads the static snapshots. Either way the shape is identical.
  const pol = usePolicyLive(interactive)
  // The catalog (committees.json) now carries the full energy catalog — the
  // explorer/feed show only the *tracked* set; the full catalog (incl. discovered
  // committees) lives in the Manage modal. Fixtures are the loading fallback.
  const committees = pol.ready ? pol.committees.filter((c) => c.tracked) : fxCommittees
  const discoveredCount = pol.ready ? pol.committees.filter((c) => c.discovered).length : 6
  const meetings = pol.ready ? pol.meetings : fxMeetings
  const untracked: Meeting[] = pol.ready ? [] : fxUntracked
  const upcoming: Upcoming[] = pol.ready ? pol.upcoming : fxUpcoming

  // ---- handlers ----
  const selAll = () => {
    setCommittee('all')
    setDetailMode('meeting')
  }
  const toggleFollowed = () => setFollowedOnly((v) => !v)
  const toggleJp = () => setJpOpen((v) => !v)
  const clearQ = () => setQ('')
  const covTracked = () => setCoverage('tracked')
  const covAll = () => setCoverage('all')
  // Selecting a committee shows its high-level synthesis; selecting a session shows
  // that session's digest.
  const selectCommittee = (key: string) => {
    setCommittee(key)
    setDetailMode('committee')
    setSynthJpOpen(false)
  }
  const selectMeeting = (key: string) => {
    setMeeting(key)
    setJpOpen(false)
    setDetailMode('meeting')
  }
  const queueMeeting = (key: string) => {
    setQueued((s2) => ({ ...s2, [key]: true }))
    toast('Tracked & queued — NotebookLM summarises it on the next catch-up run (daily 06:10 JST) · 追跡し、要約キューに登録しました')
  }

  // Run catch-up (interactive/local only): kick the auth-free refresh on the local
  // API, then poll the job to completion and report the result. Hidden on the
  // read-only GitHub Pages deployment (no /api).
  const runCatchup = () => {
    if (!interactive) return
    toast(L === 'ja' ? '差分取得を開始しました…' : 'Catch-up started…')
    const poll = () => {
      fetch('/api/policy/catchup')
        .then((r) => r.json())
        .then((j) => {
          if (j.state === 'running') {
            window.setTimeout(poll, 1500)
            return
          }
          if (j.state === 'done' && j.result) {
            const r = j.result
            toast(
              L === 'ja'
                ? `差分取得完了 — 新規会合 ${r.new_meetings} · 日付 ${r.dated} · 発見 ${r.discovered} · 要約待ち ${r.pending}`
                : `Catch-up done — ${r.new_meetings} new · ${r.dated} dated · ${r.discovered} discovered · ${r.pending} pending`,
            )
          } else {
            toast(L === 'ja' ? '差分取得に失敗しました' : 'Catch-up failed')
          }
        })
        .catch(() => toast(L === 'ja' ? '差分取得の状態を取得できません' : 'Could not read catch-up status'))
    }
    fetch('/api/policy/catchup', { method: 'POST' })
      .then(() => window.setTimeout(poll, 1500))
      .catch(() => toast(L === 'ja' ? '差分取得を開始できませんでした' : 'Could not start catch-up'))
  }
  const tManage = () => openOverlay('committees')
  const tViewAll = () => toast('Full “newly summarised” list — not in this prototype · 一覧表示は対象外')
  const tAdd = () => openOverlay('committees')
  const tSource = () => toast('Opens the committee’s official METI/OCCTO page in a new tab · 公式ページを開きます')
  const tRef = () => toast('Citation deep-link: opens the source PDF at the cited page · 引用元PDFの該当ページを開きます')
  const tDoc = () => toast('Opens the original PDF from METI · 元資料PDFを開きます')
  const tRetry = () => toast('Re-queued with high-accuracy OCR — will run on next catch-up · 高精度OCRで再実行キューに追加')
  const tExpand = () => toast('Nav rail auto-collapses on this screen to fit three panes · 3ペイン表示のためナビは自動折りたたみ')
  const tNotif = () => toast('Notifications live on the Overview screen · 通知は概況画面にあります')
  const tNotifyMe = () => toast('Alert armed — you will be notified when the digest is ready · 要約完了時に通知します')

  // ---- computed (mirrors renderVals) ----
  const selCom = committee
  const selMtg = meeting
  const fOnly = followedOnly

  const segBase = (on: boolean): CSS => ({
    padding: '4px 13px', borderRadius: 999, fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: on ? 'var(--ac)' : 'transparent', color: on ? '#FFFFFF' : 'var(--mut)',
    transition: 'all .15s', whiteSpace: 'nowrap',
  })
  const chipBase = (on: boolean): CSS => ({
    fontSize: 11.5, fontWeight: 600, padding: '3px 11px', borderRadius: 999, cursor: 'pointer',
    border: on ? '1px solid var(--ac)' : '1px solid var(--bd2)',
    background: on ? 'var(--acTint)' : 'var(--bg1)', color: on ? 'var(--acT)' : 'var(--mut)', whiteSpace: 'nowrap',
  })

  const orgColors: Record<string, string> = { METI: 'var(--ac)', OCCTO: dark ? '#7C9CD1' : '#4A6FA5', EGC: dark ? '#C77BD8' : '#7B2D8E' }

  // ---- committee search + "recommended to follow" ranking ----
  const cq = comQ.trim().toLowerCase()
  const matchComQ = (c: (typeof committees)[number]) =>
    !cq || (c.en + ' ' + c.ja + ' ' + c.org + ' ' + c.key).toLowerCase().includes(cq)

  const nowMs = Date.now()
  const recScore = (c: (typeof committees)[number]) => {
    const orgW = c.org === 'METI' ? 3 : c.org === 'OCCTO' ? 2 : 1
    const activity = Math.min(c.sourceCount || c.meetings || 0, 60)
    const days = c.lastDate ? Math.max(0, (nowMs - Date.parse(c.lastDate)) / 864e5) : 400
    const recW = Math.max(0, 1 - days / 365)
    return orgW * 2 + activity / 12 + recW * 5
  }
  // Follow uses the real committee keys, which only exist once live data loads.
  // While falling back to fixtures (fixture keys ≠ real keys) show the fixture's
  // own `followed` flag and don't write to the real follow store.
  const isFol = (c: (typeof committees)[number]) => (pol.ready ? isFollowing(c.key) : c.followed)
  const recommended = !pol.ready
    ? []
    : committees
        .filter((c) => !isFollowing(c.key) && matchComQ(c))
        .sort((a, b) => recScore(b) - recScore(a))
        .slice(0, 3)
        .map((c) => ({ key: c.key, n1: L === 'ja' ? c.ja : c.en, org: c.org, last: c.last }))

  // ---- explorer ----
  const orgs: Array<'METI' | 'OCCTO' | 'EGC'> = ['METI', 'OCCTO', 'EGC']
  const explorerGroups = orgs.map((org) => {
    const items = committees
      .filter((c) => c.org === org && (!fOnly || isFol(c)) && matchComQ(c))
      .map((c) => {
        const on = selCom === c.key
        const following = isFol(c)
        let nx = ''
        if (c.nextDate) {
          const dd = dUntil(c.nextDate)
          const mo = parseInt(c.nextDate.slice(5, 7), 10)
          const dy = parseInt(c.nextDate.slice(8, 10), 10)
          nx = L === 'ja'
            ? '次回 第' + c.nextNo + '回 · ' + mo + '月' + dy + '日 · あと' + dd + '日'
            : 'Next No. ' + c.nextNo + ' · ' + MONTHS[mo] + ' ' + dy + ' · in ' + dd + 'd'
        }
        return {
          key: c.key,
          n1: L === 'ja' ? c.ja : c.en, n2: L === 'ja' ? c.en : c.ja, tier: c.tier, last: c.last,
          next: nx, hasNext: !!c.nextDate,
          following,
          s: {
            padding: '7px 9px', borderRadius: 10, cursor: 'pointer',
            background: on ? 'var(--acTint)' : 'transparent',
            borderLeft: on ? '3px solid var(--ac)' : '3px solid transparent', minWidth: 0,
          } as CSS,
          click: () => selectCommittee(c.key),
          folClick: pol.ready ? () => toggleFollow(c.key) : () => {},
          folTxt: following ? (L === 'ja' ? 'フォロー中' : 'Following') : (L === 'ja' ? '＋ フォロー' : '+ Follow'),
          folS: (following
            ? { fontSize: 9.5, fontWeight: 600, background: 'var(--acBadge)', color: '#FFFFFF', borderRadius: 999, padding: '1px 8px', cursor: 'pointer' }
            : { fontSize: 9.5, fontWeight: 600, border: '1px solid var(--bd2)', color: 'var(--acT)', borderRadius: 999, padding: '0 8px', cursor: 'pointer' }) as CSS,
        }
      })
    const count = committees.filter((c) => c.org === org).length
    return {
      name: org + ' · ' + count,
      dot: { width: 7, height: 7, borderRadius: 999, background: orgColors[org], display: 'inline-block' } as CSS,
      items,
    }
  }).filter((g) => g.items.length)

  const allOn = selCom === 'all'
  const allRowS: CSS = {
    marginTop: 10, padding: '7px 11px', borderRadius: 10, cursor: 'pointer', fontSize: 12.5, fontWeight: 600,
    background: allOn ? 'var(--acTint)' : 'var(--bg2)', color: allOn ? 'var(--acT)' : 'var(--tx2)',
  }

  // ---- feed ----
  const stChip = (st: string): { txt: string; s: CSS } => {
    const base: CSS = { fontSize: 10, fontWeight: 600, borderRadius: 999, padding: '1px 8px', flexShrink: 0, whiteSpace: 'nowrap' }
    if (st === 'done') return { txt: 'Summarised 済', s: { ...base, background: 'var(--upBg)', color: 'var(--up)' } }
    if (st === 'scheduled') return { txt: 'Scheduled 開催予定', s: { ...base, background: 'var(--upBg)', color: 'var(--up)' } }
    if (st === 'running') return { txt: 'Summarising…', s: { ...base, background: 'var(--acTint)', color: 'var(--acT)' } }
    if (st === 'failed') return { txt: 'Failed — retry', s: { ...base, background: 'var(--dnBg)', color: 'var(--dn)' } }
    if (st === 'untracked') return { txt: 'Untracked 未追跡', s: { ...base, border: '1px dashed var(--fnt2)', color: 'var(--mut)', background: 'transparent' } }
    return { txt: 'Pending · Queued', s: { ...base, background: 'var(--bg2)', color: 'var(--mut)' } }
  }
  const followedSet: Record<string, boolean> = {}
  committees.forEach((c) => { followedSet[c.key] = isFol(c) })
  const comOrg: Record<string, string> = {}
  committees.forEach((c) => { comOrg[c.key] = c.org })

  const qNorm = (q || '').trim().toLowerCase()

  // Date-range filter (the "Date 期間 ▾" chip). Ranges are relative to the current
  // date; 'upcoming' hides the recent feed and shows only scheduled meetings.
  const nowD = Date.now()
  const ageDays = (ds: string) => (nowD - Date.parse(ds)) / 864e5
  const dateOkRecent = (ds: string): boolean => {
    if (dateFilter === 'all') return true
    if (dateFilter === 'upcoming') return false
    if (!ds || Number.isNaN(Date.parse(ds))) return dateFilter === 'year' ? false : true
    if (dateFilter === '30d') return ageDays(ds) <= 30
    if (dateFilter === '90d') return ageDays(ds) <= 90
    if (dateFilter === 'year') return new Date(ds).getFullYear() === new Date(nowD).getFullYear()
    return true
  }
  const showUpcoming = dateFilter === 'all' || dateFilter === 'upcoming'
  const DATE_LABELS: Record<typeof dateFilter, string> = {
    all: L === 'ja' ? '期間' : 'Date',
    '30d': L === 'ja' ? '過去30日' : 'Last 30d',
    '90d': L === 'ja' ? '過去90日' : 'Last 90d',
    year: L === 'ja' ? '今年' : 'This year',
    upcoming: L === 'ja' ? '開催予定のみ' : 'Upcoming',
  }

  let pool: Meeting[] = meetings.slice()
  if (coverage === 'all' || qNorm) pool = pool.concat(untracked)
  const feedList = pool.filter((m) => {
    if (m.untracked) {
      if (selCom !== 'all' || fOnly) return false
    } else {
      if (!(selCom === 'all' || m.com === selCom)) return false
      if (fOnly && m.com && !followedSet[m.com]) return false
      if (coverage === 'tracked' && !qNorm && m.status === 'pending') return false
    }
    if (!dateOkRecent(m.date)) return false
    if (qNorm) {
      const hay = [m.en, m.ja, m.title, m.titleJa, m.prevEn || '', m.prevJa || '', m.com ? comOrg[m.com] : m.org || '']
        .concat(m.digest ? m.digest.map((sec) => sec.h + ' ' + sec.items.join(' ')) : [])
        .join(' ').toLowerCase()
      if (!hay.includes(qNorm)) return false
    }
    return true
  }).sort((a, b) => {
    // Chronological within a committee: meeting_date is null upstream, so order by
    // meeting number (newest first). Fall back to the summary date for fixtures.
    if (typeof a.num === 'number' && typeof b.num === 'number' && a.num !== b.num) return b.num - a.num
    return b.date < a.date ? -1 : 1
  })

  const mapFeed = (m: AnyMeeting) => {
    const on = selMtg === m.key
    const isQueued = !!queued[m.key]
    const st = stChip(isQueued ? 'pending' : m.status)
    const dd = m.status === 'scheduled' ? dUntil(m.date) : 0
    const org = m.com ? comOrg[m.com] : (m as Meeting).org || ''
    const tori = (m as Meeting).tori
    const prevEn = (m as Meeting).prevEn ?? (m as Upcoming).prevEn
    const prevJa = (m as Meeting).prevJa ?? (m as Upcoming).prevJa
    return {
      key: m.key,
      title: L === 'ja' ? m.ja : m.en,
      meta: m.status === 'scheduled'
        ? m.date + ' · ' + (L === 'ja' ? 'あと' + dd + '日' : 'in ' + dd + 'd') + ' · ' + org
        : m.date + (tori ? ' · とりまとめ' : '') + ' · ' + org,
      st: st.txt, stS: st.s,
      hasPrev: !!prevEn,
      preview: prevEn ? (L === 'ja' ? prevJa || '' : prevEn) : '',
      dot: {
        width: 7, height: 7, borderRadius: 999,
        background: m.status === 'scheduled' ? 'var(--okDot)' : (m.com && followedSet[m.com]) ? 'var(--ac)' : 'var(--fnt2)',
        flexShrink: 0,
      } as CSS,
      s: {
        padding: '9px 10px', borderRadius: 12, cursor: 'pointer',
        background: on ? 'var(--acTint)' : 'transparent',
        borderLeft: on ? '3px solid var(--ac)' : '3px solid transparent',
        borderBottom: '1px solid var(--dv)', minWidth: 0,
      } as CSS,
      click: () => selectMeeting(m.key),
    }
  }
  const feed = feedList.map(mapFeed)

  const upList = upcoming.filter((m) => {
    if (!showUpcoming) return false
    if (!(selCom === 'all' || m.com === selCom)) return false
    if (fOnly && !followedSet[m.com]) return false
    if (qNorm) {
      const hay = [m.en, m.ja, m.title, m.titleJa, m.prevEn || '', m.prevJa || '', comOrg[m.com]]
        .concat(m.agendaEn || []).concat(m.agendaJa || []).join(' ').toLowerCase()
      if (!hay.includes(qNorm)) return false
    }
    return true
  }).sort((a, b) => (a.date < b.date ? -1 : 1))
  const feedUp = upList.map(mapFeed)

  // ---- detail ----
  const allMeetings: AnyMeeting[] = (meetings as AnyMeeting[]).concat(untracked as AnyMeeting[]).concat(upcoming as AnyMeeting[])
  let d = allMeetings.find((m) => m.key === selMtg)
  if (!d) d = feedList[0] || meetings[0]
  const dQueued = !!queued[d.key]
  const dEffSt = dQueued ? 'pending' : d.status
  const dStObj = stChip(dEffSt)
  const hasDigest = dEffSt === 'done'
  const dIsUn = dEffSt === 'untracked'
  const hasAgenda = dEffSt === 'scheduled'
  const dPrev = hasAgenda ? allMeetings.find((m) => m.key === (d as Upcoming).prevKey) : null

  const dM = d as Meeting
  const dU = d as Upcoming

  const dTitle = L === 'ja' ? d.titleJa : d.title
  const dSub = d.sub
  const dSt = dStObj.txt
  const dStS: CSS = { ...dStObj.s, fontSize: 10.5, padding: '2px 9px' }
  const dTori = !!dM.tori
  const dNoDigest = !hasDigest && !hasAgenda
  const dFailed = dEffSt === 'failed'
  const dAgenda = hasAgenda ? (L === 'ja' ? dU.agendaJa : dU.agendaEn) : []
  const dCountdown = hasAgenda ? (L === 'ja' ? 'あと' + dUntil(d.date) + '日' : 'in ' + dUntil(d.date) + ' days') : ''
  const dPrevLabel = dPrev ? (L === 'ja' ? dPrev.ja : dPrev.en) : ''
  const dPrevClick = () => { if (dPrev) selectMeeting(dPrev.key) }
  const dEmptyTitle = dIsUn
    ? 'Not summarised — untracked committee · 未追跡の委員会'
    : (dQueued && dM.untracked)
      ? 'Queued for summarisation · キュー登録済み'
      : dM.emptyTitle || ''
  const dEmptySub = dIsUn
    ? 'Track this committee to add its meetings to the NotebookLM summarisation queue · 追跡するとNotebookLM要約キューに追加されます'
    : (dQueued && dM.untracked)
      ? 'NotebookLM picks this up on the next catch-up run (daily 06:10 JST) · 次回の差分取得で要約されます'
      : dM.emptySub || ''
  const dSections = hasDigest && dM.digest ? dM.digest : []
  const dJp = hasDigest && dM.jp ? dM.jp : []
  const dRefs = hasDigest && dM.refs ? dM.refs : []
  const dDocs = d.docs
  const dComUrl = committees.find((c) => c.key === d.com)?.url || ''
  const openUrl = (url: string) => window.open(url, '_blank', 'noopener,noreferrer')
  const showAudio = showAudioCard && !hasAgenda

  // ---- committee overview (detail pane when a committee, not a session, is selected) ----
  const selCommittee = committees.find((c) => c.key === selCom)
  const showCommittee = detailMode === 'committee' && !!selCommittee
  const coSynthEn = selCommittee?.synthesisEn || ''
  const coSynthJa = selCommittee?.synthesisJa || ''
  const coHasSynth = !!(coSynthEn || coSynthJa)
  const coSessions = selCommittee
    ? meetings
        .filter((m) => m.com === selCommittee.key)
        .sort((a, b) => (typeof a.num === 'number' && typeof b.num === 'number' ? b.num - a.num : b.date < a.date ? -1 : 1))
    : []

  const feedNote = qNorm
    ? 'Searching all METI meetings 全会合を検索中 · ' + (feed.length + feedUp.length) + ((feed.length + feedUp.length) === 1 ? ' match' : ' matches')
    : feedUp.length + ' upcoming 開催予定 · ' + feed.length + ' recent' + (coverage === 'all' ? ' · incl. untracked 未追跡含む' : '')

  const doneList = meetings.filter((m) => m.status === 'done')
  const newCards = pol.ready
    ? doneList.slice(0, 3).map((m) => ({
        title: (L === 'ja' ? m.ja : m.en) + (m.tori ? ' 🏁' : ''),
        meta: m.date + ' · ' + (L === 'ja' ? '要約済み' : 'summarised'),
        preview: (L === 'ja' ? m.prevJa : m.prevEn) || '',
        click: () => selectMeeting(m.key),
      }))
    : [
        { title: 'EGMSC · 第58回 🏁', meta: '2026-06-24 · summarised 06-26', preview: L === 'ja' ? '託送料金制度見直しの中間とりまとめを採択。' : 'Adopted the interim report on the wheeling-charge review.', click: () => selectMeeting('egmsc58') },
        { title: 'Basic Policy · 第84回', meta: '2026-06-27 · summarised 06-29', preview: L === 'ja' ? '長期蓄電池の容量市場連携を審議。' : 'Debated capacity-market linkage for long-duration storage.', click: () => selectMeeting('basic84') },
        { title: 'Renewable Integration · 第63回', meta: '2026-06-05 · summarised 06-08', preview: L === 'ja' ? 'ノンファーム接続の全国展開方針を確認。' : 'Confirmed nationwide non-firm connection rollout from FY2027.', click: () => selectMeeting('renew63') },
      ]

  const langJaS = segBase(L === 'ja')
  const langEnS = segBase(L === 'en')
  const chipCommittee = chipBase(selCom !== 'all')
  const chipDate = chipBase(dateFilter !== 'all')
  const chipFollowed = chipBase(fOnly)
  const covTS: CSS = { padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, cursor: 'pointer', background: coverage === 'tracked' ? 'var(--ac)' : 'transparent', color: coverage === 'tracked' ? '#FFFFFF' : 'var(--mut)', whiteSpace: 'nowrap' }
  const covAS: CSS = { padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, cursor: 'pointer', background: coverage === 'all' ? 'var(--ac)' : 'transparent', color: coverage === 'all' ? '#FFFFFF' : 'var(--mut)', whiteSpace: 'nowrap' }

  return (
    <>
      {/* ============ COLLAPSED ICON RAIL ============ */}
      <div style={s('width:68px;flex-shrink:0;background:var(--bg1);border-right:1px solid var(--bd);display:flex;flex-direction:column;align-items:center;padding:22px 0 16px;gap:4px')}>
        <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:24px;height:24px;color:var(--ac);flex-shrink:0;margin-bottom:18px"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`} />
        <Hoverable base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => setScreen('overview')} title="Market Overview · 概況">
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><rect x="3" y="3" width="7" height="9" rx="1"></rect><rect x="14" y="3" width="7" height="5" rx="1"></rect><rect x="14" y="12" width="7" height="9" rx="1"></rect><rect x="3" y="16" width="7" height="5" rx="1"></rect></svg>`} />
        </Hoverable>
        <Hoverable base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => setScreen('market')} title="Market Data · データ">
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><path d="M3 3v18h18"></path><path d="M8 17v-3"></path><path d="M13 17V9"></path><path d="M18 17V5"></path></svg>`} />
        </Hoverable>
        <Hoverable base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => setScreen('capacity')} title="Capacity & Auctions · 容量市場">
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><polygon points="12 2 22 8.5 12 15 2 8.5 12 2"></polygon><polyline points="2 14 12 20.5 22 14"></polyline></svg>`} />
        </Hoverable>
        <div style={s('width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#FFFFFF;background:var(--acBadge);cursor:pointer;position:relative')} title="Policy Deep Dive · 政策">
          <span style={s('position:absolute;left:-13px;top:8px;bottom:8px;width:3px;background:var(--ac);border-radius:0 2px 2px 0')}></span>
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><line x1="3" y1="22" x2="21" y2="22"></line><line x1="6" y1="18" x2="6" y2="11"></line><line x1="10" y1="18" x2="10" y2="11"></line><line x1="14" y1="18" x2="14" y2="11"></line><line x1="18" y1="18" x2="18" y2="11"></line><polygon points="12 2 20 7 4 7"></polygon></svg>`} />
        </div>
        <div style={s('width:28px;height:1px;background:var(--dv);margin:6px 0')}></div>
        <Hoverable base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('watchlist')} title="Watchlist · ウォッチリスト">
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon></svg>`} />
        </Hoverable>
        <Hoverable base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer" hover="background:var(--acTint2);color:var(--tx)" onClick={() => openOverlay('settings')} title="Settings · 設定">
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><circle cx="12" cy="12" r="3"></circle><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path></svg>`} />
        </Hoverable>
        <div style={s('flex:1')}></div>
        <Hoverable base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--mut);cursor:pointer" hover="background:var(--bg2);color:var(--tx2)" onClick={tExpand} title="Expand nav · ナビを展開">
          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:17px;height:17px"><path d="M13 17l5-5-5-5"></path><path d="M6 17l5-5-5-5"></path></svg>`} />
        </Hoverable>
      </div>

      {/* ============ MAIN COLUMN ============ */}
      <div style={s('flex:1;min-width:0;display:flex;flex-direction:column;position:relative')}>

        {/* Top bar */}
        <div style={s('height:72px;flex-shrink:0;background:var(--bg1);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:18px;padding:0 28px;position:relative;z-index:30')}>
          <div style={s('font-size:13px;color:var(--mut);flex-shrink:0')}>Policy Deep Dive <span style={s('color:var(--fnt3)')}>·</span> 政策ディープダイブ</div>
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
          <Hoverable base="width:40px;height:40px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;position:relative;flex-shrink:0" hover="background:var(--bg2)" onClick={tNotif}>
            <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:19px;height:19px"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} />
            <span style={s('position:absolute;top:9px;right:10px;width:8px;height:8px;border-radius:999px;background:var(--ac);border:1.5px solid var(--bg1)')}></span>
          </Hoverable>
          <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;flex-shrink:0')}>
            <span style={langJaS} onClick={() => setLang('ja')}>日本語</span>
            <span style={langEnS} onClick={() => setLang('en')}>English</span>
          </div>
          <div style={s('display:flex;align-items:center;gap:10px;flex-shrink:0')}>
            <div style={s('width:34px;height:34px;border-radius:999px;background:var(--avatar);color:#FFFFFF;display:flex;align-items:center;justify-content:center;font-size:11.5px;font-weight:600')}>AN</div>
            <div style={s('line-height:1.25')}>
              <div style={s('font-size:13px;font-weight:600')}>Analyst</div>
              <div style={s('font-size:11px;color:var(--mut)')}>analyst@example.jp</div>
            </div>
          </div>
        </div>

        {/* Scrollable content */}
        <div style={s('flex:1;overflow-y:auto;padding:26px 32px 40px')}>
          <div style={s('max-width:1560px;margin:0 auto;display:flex;flex-direction:column;gap:18px')}>

            {/* Page header */}
            <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:16px')}>
              <div>
                <div style={s('display:flex;align-items:baseline;gap:10px')}>
                  <span style={s('font-size:26px;font-weight:700;letter-spacing:-.01em')}>Policy Deep Dive</span>
                  <span style={s('font-size:15px;font-weight:500;color:var(--mut)')}>政策ディープダイブ</span>
                </div>
                <div style={s('font-size:13.5px;color:var(--tx2);margin-top:2px')}>Committee tracking &amp; AI briefings · METI · OCCTO · EGC · 委員会追跡とAIブリーフィング</div>
              </div>
              <div style={s('display:flex;gap:10px;flex-shrink:0;padding-top:4px')}>
                {interactive && (
                  <Hoverable base="display:inline-flex;align-items:center;gap:7px;background:var(--ac);color:#FFFFFF;border-radius:999px;padding:9px 20px;font-size:13.5px;font-weight:600;cursor:pointer;box-shadow:var(--sh1a)" hover="background:var(--acT);box-shadow:var(--sh2)" onClick={runCatchup}>
                    <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;flex-shrink:0"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>`} />Run catch-up · 差分取得
                  </Hoverable>
                )}
                <Hoverable base="background:var(--bg1);border:1px solid var(--fnt3);color:var(--tx);border-radius:999px;padding:9px 20px;font-size:13.5px;font-weight:600;cursor:pointer" hover="background:var(--acTint2);border-color:var(--ac)" onClick={tManage}>Manage · 管理</Hoverable>
              </div>
            </div>

            {/* Search & filter bar */}
            <div style={s('background:var(--bg1);border-radius:16px;padding:10px 16px;box-shadow:var(--sh1);display:flex;align-items:center;gap:12px;flex-wrap:wrap')}>
              <div style={s('flex:1;min-width:220px;display:flex;align-items:center;gap:9px;color:var(--mut)')}>
                <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;flex-shrink:0"><circle cx="11" cy="11" r="8"></circle><path d="M21 21l-4.35-4.35"></path></svg>`} />
                <input placeholder="Search all METI meetings, briefings &amp; digests… 全会合・要約・ダイジェストを検索…" value={q} onChange={(e) => setQ(e.target.value)} style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:13px;background:transparent;color:var(--tx);min-width:0')} />
                {!!qNorm && (
                  <span style={s('font-size:11px;font-weight:600;color:var(--mut);cursor:pointer;flex-shrink:0')} onClick={clearQ}>✕ clear</span>
                )}
                <span style={s('font-size:9.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:6px;padding:1px 7px;flex-shrink:0')} title="Search covers titles, committees & digests — incl. untracked meetings. Full text of source PDFs (FTS5) is proposed. · 検索は未追跡会合も対象。PDF全文検索は提案中">PDF full-text = PROPOSED</span>
              </div>
              <span style={s('width:1px;height:22px;background:var(--dv)')}></span>
              {/* Committee filter dropdown */}
              <span style={s('position:relative')}>
                <span style={chipCommittee} onClick={() => { setComOpen((o) => !o); setDateOpen(false) }}>
                  {selCom === 'all'
                    ? (L === 'ja' ? '委員会 ▾' : 'Committee ▾')
                    : ((L === 'ja' ? selCommittee?.ja : selCommittee?.en) || selCom) + ' ▾'}
                </span>
                {comOpen && (
                  <>
                    <div onClick={() => setComOpen(false)} style={s('position:fixed;inset:0;z-index:40')}></div>
                    <div style={s('position:absolute;top:calc(100% + 6px);left:0;z-index:50;width:310px;max-height:360px;overflow-y:auto;background:var(--bg1);border:1px solid var(--bd);border-radius:12px;box-shadow:var(--shPop);padding:6px')}>
                      <Hoverable base={`display:block;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:12.5px;font-weight:600;color:${selCom === 'all' ? 'var(--acT)' : 'var(--tx)'}`} hover="background:var(--hov)" onClick={() => { selAll(); setComOpen(false) }}>All committees · すべて</Hoverable>
                      {orgs.map((org) => {
                        const items = committees.filter((c) => c.org === org)
                        if (!items.length) return null
                        return (
                          <div key={org}>
                            <div style={s('font-size:10px;font-weight:700;letter-spacing:.06em;color:var(--mut);margin:8px 8px 3px')}>{org}</div>
                            {items.map((c) => (
                              <Hoverable key={c.key} base={`display:block;padding:6px 10px;border-radius:8px;cursor:pointer;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:${selCom === c.key ? 'var(--acT)' : 'var(--tx2)'};background:${selCom === c.key ? 'var(--acTint)' : 'transparent'}`} hover="background:var(--hov)" onClick={() => { selectCommittee(c.key); setComOpen(false) }}>{L === 'ja' ? c.ja : c.en}</Hoverable>
                            ))}
                          </div>
                        )
                      })}
                    </div>
                  </>
                )}
              </span>
              {/* Date-range filter dropdown */}
              <span style={s('position:relative')}>
                <span style={chipDate} onClick={() => { setDateOpen((o) => !o); setComOpen(false) }}>{DATE_LABELS[dateFilter]} ▾</span>
                {dateOpen && (
                  <>
                    <div onClick={() => setDateOpen(false)} style={s('position:fixed;inset:0;z-index:40')}></div>
                    <div style={s('position:absolute;top:calc(100% + 6px);left:0;z-index:50;width:200px;background:var(--bg1);border:1px solid var(--bd);border-radius:12px;box-shadow:var(--shPop);padding:6px')}>
                      {([
                        ['all', L === 'ja' ? 'すべての期間' : 'All time'],
                        ['30d', L === 'ja' ? '過去30日' : 'Last 30 days'],
                        ['90d', L === 'ja' ? '過去90日' : 'Last 90 days'],
                        ['year', L === 'ja' ? '今年' : 'This year'],
                        ['upcoming', L === 'ja' ? '開催予定のみ' : 'Upcoming only'],
                      ] as const).map(([v, label]) => (
                        <Hoverable key={v} base={`display:block;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:12.5px;color:${dateFilter === v ? 'var(--acT)' : 'var(--tx2)'};background:${dateFilter === v ? 'var(--acTint)' : 'transparent'}`} hover="background:var(--hov)" onClick={() => { setDateFilter(v); setDateOpen(false) }}>{label}</Hoverable>
                      ))}
                    </div>
                  </>
                )}
              </span>
              <span style={chipFollowed} onClick={toggleFollowed}>Followed only フォロー中のみ</span>
            </div>

            {/* Newly summarised banner */}
            <div style={s('background:var(--acTint);border:1px solid var(--acTint);border-radius:16px;padding:14px 16px')}>
              <div style={s('display:flex;justify-content:space-between;align-items:center')}>
                <span style={s("display:inline-flex;align-items:center;gap:7px;font-size:13.5px;font-weight:600;color:var(--acT)")}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;flex-shrink:0"><path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3z"></path></svg>`} />Newly summarised · last 7 days (3) 新着要約
                </span>
                <Hoverable as="span" base="font-size:12px;font-weight:600;color:var(--acT);cursor:pointer" hover="color:var(--ac)" onClick={tViewAll}>View all →</Hoverable>
              </div>
              <div style={s('display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px')}>
                {newCards.map((nc, i) => (
                  <Hoverable key={i} base="background:var(--bg1);border-radius:12px;padding:10px 12px;cursor:pointer;box-shadow:var(--sh1)" hover="box-shadow:var(--sh2)" onClick={nc.click}>
                    <div style={s('font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{nc.title}</div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:1px;font-feature-settings:'tnum' 1")}>{nc.meta}</div>
                    <div style={s('font-size:11.5px;color:var(--tx2);margin-top:4px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical')}>{nc.preview}</div>
                  </Hoverable>
                ))}
              </div>
              <div style={s("font-size:11px;color:var(--mut);margin-top:9px;font-feature-settings:'tnum' 1")}>Last run 2026-07-02 06:10 JST — Processed 8 · Summarised 3 · Errored 0 · Synthesised 2 · Rate-limited: no</div>
            </div>

            {/* ============ THREE PANES ============ */}
            <div style={s('display:grid;grid-template-columns:290px 350px 1fr;gap:18px;align-items:start')}>

              {/* EXPLORER */}
              <div style={s('background:var(--bg1);border-radius:20px;padding:16px;box-shadow:var(--sh1)')}>
                <div style={s('display:flex;align-items:baseline;justify-content:space-between')}>
                  <span style={s('font-size:14px;font-weight:600')}>Committees <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>委員会</span></span>
                  <span style={s('font-size:11px;color:var(--mut)')}>{committees.length} tracked</span>
                </div>
                {/* committee search */}
                <div style={s('display:flex;align-items:center;gap:7px;background:var(--bg0);border:1px solid var(--bd);border-radius:10px;padding:6px 10px;margin-top:9px')}>
                  <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;color:var(--mut);flex-shrink:0"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>`} />
                  <input placeholder={L === 'ja' ? '委員会を検索…' : 'Search committees…'} value={comQ} onChange={(e) => setComQ(e.target.value)} style={s('border:none;outline:none;flex:1;font-family:inherit;font-size:12.5px;background:transparent;color:var(--tx);min-width:0')} />
                  {comQ && (
                    <span onClick={() => setComQ('')} style={s('font-size:11px;color:var(--mut);cursor:pointer;flex-shrink:0')}>✕</span>
                  )}
                </div>
                {/* recommended to follow */}
                {recommended.length > 0 && !fOnly && (
                  <div style={s('margin-top:12px')}>
                    <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.06em;color:var(--mut);margin:0 2px 5px')}>{L === 'ja' ? 'おすすめのフォロー' : 'RECOMMENDED TO FOLLOW'}</div>
                    <div style={s('display:flex;flex-direction:column;gap:5px')}>
                      {recommended.map((r) => (
                        <div key={r.key} style={s('display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 9px;border:1px solid var(--bd2);border-radius:10px')}>
                          <span style={s('display:flex;flex-direction:column;min-width:0')}>
                            <span style={s('font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{r.n1}</span>
                            <span style={s("font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>{r.org} · {r.last}</span>
                          </span>
                          <Hoverable as="span" base="font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;border:1px solid var(--ac);color:var(--acT);cursor:pointer;background:var(--acTint);white-space:nowrap;flex-shrink:0" hover="background:var(--ac);color:#FFFFFF" onClick={() => toggleFollow(r.key)}>{L === 'ja' ? '＋ フォロー' : '+ Follow'}</Hoverable>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div style={allRowS} onClick={selAll}>All committees · すべて</div>
                {explorerGroups.map((g, gi) => (
                  <div key={gi}>
                    <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.07em;color:var(--mut);margin:12px 2px 5px;display:flex;align-items:center;gap:6px')}><span style={g.dot}></span>{g.name}</div>
                    <div style={s('display:flex;flex-direction:column;gap:3px')}>
                      {g.items.map((c) => (
                        <div key={c.key} style={c.s} onClick={c.click}>
                          <div style={s('font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{c.n1}</div>
                          <div style={s('font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{c.n2} · {c.tier}</div>
                          <div style={s('display:flex;justify-content:space-between;align-items:center;margin-top:3px')}>
                            <span style={c.folS} onClick={(e) => { e.stopPropagation(); c.folClick() }} title={c.following ? (L === 'ja' ? 'クリックでフォロー解除' : 'Click to unfollow') : (L === 'ja' ? 'クリックでフォロー' : 'Click to follow')}>{c.folTxt}</span>
                            <span style={s("font-size:10.5px;color:var(--mut);font-feature-settings:'tnum' 1")}>{c.last}</span>
                          </div>
                          {c.hasNext && (
                            <div style={s("display:flex;align-items:center;gap:5px;font-size:10.5px;font-weight:600;color:var(--up);margin-top:4px;font-feature-settings:'tnum' 1")}>
                              <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:11px;height:11px;flex-shrink:0"><rect x="3" y="4" width="18" height="18" rx="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`} />
                              <span style={s('white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{c.next}</span>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                <div style={s('border:1px dashed var(--fnt2);border-radius:12px;padding:9px 11px;margin-top:12px;display:flex;justify-content:space-between;align-items:center')}>
                  <span style={s('font-size:11px;color:var(--mut)')}>Discovered · {discoveredCount} committees<br />未追跡 — 「管理」で追跡</span>
                  <Hoverable as="span" base="font-size:11.5px;font-weight:600;padding:3px 11px;border-radius:999px;border:1px solid var(--bd2);color:var(--tx2);cursor:pointer;background:var(--bg1)" hover="border-color:var(--ac);color:var(--acT)" onClick={tAdd}>Manage 管理</Hoverable>
                </div>
              </div>

              {/* FEED */}
              <div style={s('background:var(--bg1);border-radius:20px;padding:16px;box-shadow:var(--sh1)')}>
                <div style={s('display:flex;align-items:baseline;justify-content:space-between')}>
                  <span style={s('font-size:14px;font-weight:600')}>Meetings <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>会合フィード</span></span>
                  <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:2px;flex-shrink:0')}>
                    <span style={covTS} onClick={covTracked}>Tracked</span>
                    <span style={covAS} onClick={covAll}>All METI</span>
                  </div>
                </div>
                <div style={s('font-size:11px;color:var(--mut);margin-top:5px')}>{feedNote}</div>
                <div style={s('display:flex;flex-direction:column;margin-top:8px')}>
                  {feedUp.length > 0 && (
                    <div style={s('display:flex;align-items:center;gap:6px;font-size:10.5px;font-weight:700;letter-spacing:.07em;color:var(--up);margin:2px 2px 4px')}><span style={s('width:7px;height:7px;border-radius:999px;background:var(--okDot)')}></span>UPCOMING · 開催予定</div>
                  )}
                  {feedUp.map((u) => (
                    <div key={u.key} style={u.s} onClick={u.click}>
                      <div style={s('display:flex;justify-content:space-between;align-items:center;gap:8px')}>
                        <span style={s('display:inline-flex;align-items:center;gap:7px;min-width:0')}>
                          <span style={u.dot}></span>
                          <span style={s('font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{u.title}</span>
                        </span>
                        <span style={u.stS}>{u.st}</span>
                      </div>
                      <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{u.meta}</div>
                      {u.hasPrev && (
                        <div style={s('font-size:11.5px;color:var(--tx2);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{u.preview}</div>
                      )}
                    </div>
                  ))}
                  {feedUp.length > 0 && (
                    <div style={s('font-size:10.5px;font-weight:700;letter-spacing:.07em;color:var(--mut);margin:12px 2px 4px')}>RECENT · 開催済み</div>
                  )}
                  {feed.map((f) => (
                    <div key={f.key} style={f.s} onClick={f.click}>
                      <div style={s('display:flex;justify-content:space-between;align-items:center;gap:8px')}>
                        <span style={s('display:inline-flex;align-items:center;gap:7px;min-width:0')}>
                          <span style={f.dot}></span>
                          <span style={s('font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{f.title}</span>
                        </span>
                        <span style={f.stS}>{f.st}</span>
                      </div>
                      <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{f.meta}</div>
                      {f.hasPrev && (
                        <div style={s('font-size:11.5px;color:var(--tx2);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{f.preview}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* DETAIL */}
              <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1);min-width:0')}>
                {/* ---- Committee overview (high-level synthesis) ---- */}
                {showCommittee && (
                  <>
                    <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                      <div style={s('min-width:0')}>
                        <div style={s('display:flex;align-items:center;gap:9px;flex-wrap:wrap')}>
                          <span style={s('font-size:17px;font-weight:700')}>{L === 'ja' ? selCommittee?.ja : selCommittee?.en}</span>
                          <span style={s(`font-size:10.5px;font-weight:600;background:var(--acTint);color:${orgColors[selCommittee?.org || 'METI']};border-radius:6px;padding:1px 7px`)}>{selCommittee?.org}</span>
                          {selCommittee?.discovered && (
                            <span style={s('font-size:9.5px;font-weight:600;color:var(--mut);border:1px dashed var(--fnt2);border-radius:6px;padding:0 6px')}>{L === 'ja' ? '未追跡発見' : 'discovered'}</span>
                          )}
                        </div>
                        <div style={s("font-size:12px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{L === 'ja' ? selCommittee?.en : selCommittee?.ja} · {selCommittee?.tier}</div>
                      </div>
                      <Hoverable as="span" base="display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--acT);cursor:pointer;flex-shrink:0;white-space:nowrap;padding-top:3px" hover="color:var(--ac)" onClick={() => (selCommittee?.url ? openUrl(selCommittee.url) : tSource())}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>`} />METI page · 元ページ</Hoverable>
                    </div>
                    {/* Status rollup */}
                    <div style={s('display:flex;gap:7px;flex-wrap:wrap;margin-top:12px')}>
                      <span style={s("font-size:11px;font-weight:600;border-radius:999px;padding:2px 10px;background:var(--upBg);color:var(--up);font-feature-settings:'tnum' 1")}>{selCommittee?.done || 0} {L === 'ja' ? '要約済み' : 'summarised'}</span>
                      <span style={s("font-size:11px;font-weight:600;border-radius:999px;padding:2px 10px;background:var(--bg2);color:var(--mut);font-feature-settings:'tnum' 1")}>{selCommittee?.pending || 0} {L === 'ja' ? '要約待ち' : 'pending'}</span>
                      {!!(selCommittee?.error) && (
                        <span style={s("font-size:11px;font-weight:600;border-radius:999px;padding:2px 10px;background:var(--dnBg);color:var(--dn);font-feature-settings:'tnum' 1")}>{selCommittee?.error} {L === 'ja' ? 'エラー' : 'errored'}</span>
                      )}
                      {!!(selCommittee?.lastSynth) && (
                        <span style={s("font-size:11px;font-weight:600;border-radius:999px;padding:2px 10px;border:1px solid var(--bd2);color:var(--tx2);font-feature-settings:'tnum' 1")}>{L === 'ja' ? `第${selCommittee?.lastSynth}回まで統合` : `synthesised thru No. ${selCommittee?.lastSynth}`}</span>
                      )}
                    </div>
                    {coHasSynth ? (
                      <>
                        {coSynthEn && (
                          <div style={s('margin-top:16px')}>
                            <div style={s('font-size:11.5px;font-weight:700;letter-spacing:.06em;color:var(--mut)')}>SYNTHESIS OVERVIEW · 横断サマリー（英語）</div>
                            {renderMd(coSynthEn)}
                          </div>
                        )}
                        {coSynthJa && (
                          <div style={s('border:1px solid var(--bd);border-radius:14px;margin-top:14px;overflow:hidden')}>
                            <Hoverable base="display:flex;justify-content:space-between;align-items:center;padding:11px 14px;cursor:pointer;background:var(--bg3)" hover="background:var(--bg2)" onClick={() => setSynthJpOpen((v) => !v)}>
                              <span style={s('font-size:13px;font-weight:600')}>議論の総括（会合横断） <span style={s('font-size:11px;font-weight:400;color:var(--mut)')}>JP authoritative · 日本語正</span></span>
                              <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;color:var(--mut)"><path d="${synthJpOpen ? 'M18 15l-6-6-6 6' : 'M6 9l6 6 6-6'}"></path></svg>`} />
                            </Hoverable>
                            {synthJpOpen && (
                              <div style={s('padding:4px 14px 13px;border-top:1px solid var(--dv)')}>{renderMd(coSynthJa)}</div>
                            )}
                          </div>
                        )}
                      </>
                    ) : (
                      <div style={s('margin-top:16px;border:1px dashed var(--fnt2);border-radius:14px;padding:22px;text-align:center')}>
                        <div style={s('font-size:13.5px;font-weight:600;color:var(--tx2)')}>{L === 'ja' ? '横断サマリーは未作成です' : 'No cross-meeting synthesis yet'}</div>
                        <div style={s('font-size:12px;color:var(--mut);margin-top:3px')}>{L === 'ja' ? 'この委員会の会合を要約すると総括が作成されます（「管理」→▶ で実行）' : "Summarise this committee's meetings to build its synthesis (Manage → ▶)"}</div>
                      </div>
                    )}
                    {/* Sessions */}
                    <div style={s('margin-top:16px;border-top:1px solid var(--dv);padding-top:12px')}>
                      <div style={s('font-size:11.5px;font-weight:700;letter-spacing:.06em;color:var(--mut)')}>SESSIONS · 会合一覧 ({coSessions.length})</div>
                      <div style={s('display:flex;flex-direction:column;gap:2px;margin-top:6px')}>
                        {coSessions.length === 0 && (
                          <div style={s('font-size:12px;color:var(--mut);padding:6px 2px')}>{L === 'ja' ? 'まだ会合が検出されていません' : 'No sessions detected yet'}</div>
                        )}
                        {coSessions.map((m) => {
                          const st = stChip(m.status)
                          return (
                            <Hoverable key={m.key} base="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:7px 10px;border-radius:10px;cursor:pointer" hover="background:var(--hov)" onClick={() => selectMeeting(m.key)}>
                              <span style={s("font-size:12.5px;font-weight:600;color:var(--tx2);white-space:nowrap;font-feature-settings:'tnum' 1")}>{L === 'ja' ? '第' + m.num + '回' : 'No. ' + m.num}{m.tori ? ' 🏁' : ''}</span>
                              <span style={s('flex:1')}></span>
                              <span style={s("font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>{m.date}</span>
                              <span style={st.s}>{st.txt}</span>
                            </Hoverable>
                          )
                        })}
                      </div>
                    </div>
                  </>
                )}
                {/* ---- Session (meeting) detail ---- */}
                {!showCommittee && (
                <>
                <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                  <div style={s('min-width:0')}>
                    <div style={s('display:flex;align-items:center;gap:9px;flex-wrap:wrap')}>
                      <span style={s('font-size:17px;font-weight:700')}>{dTitle}</span>
                      <span style={dStS}>{dSt}</span>
                      {dTori && (<span style={s('font-size:10.5px;font-weight:600;background:var(--acTint);color:var(--acT);border-radius:6px;padding:1px 7px')}>とりまとめ</span>)}
                    </div>
                    <div style={s("font-size:12px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{dSub}</div>
                  </div>
                  <Hoverable as="span" base="display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--acT);cursor:pointer;flex-shrink:0;white-space:nowrap;padding-top:3px" hover="color:var(--ac)" onClick={() => (dComUrl ? openUrl(dComUrl) : tSource())}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>`} />METI page · 元ページ</Hoverable>
                </div>

                {hasDigest && (
                  <div style={s('margin-top:14px')}>
                    <div style={s('font-size:11.5px;font-weight:700;letter-spacing:.06em;color:var(--mut)')}>ENGLISH DIGEST · 英語ダイジェスト</div>
                    {dSections.map((ds, dsi) => (
                      <div key={dsi} style={s('margin-top:11px')}>
                        <div style={s('font-size:13px;font-weight:600;color:var(--tx)')}>{ds.h}</div>
                        {ds.items.map((li, lii) => (
                          <div key={lii} style={s('display:flex;gap:8px;font-size:12.5px;color:var(--tx2);margin-top:4px;line-height:1.55')}>
                            <span style={s('width:5px;height:5px;border-radius:999px;background:var(--ac);margin-top:7px;flex-shrink:0')}></span>
                            <span style={s('flex:1')}>{li}</span>
                          </div>
                        ))}
                      </div>
                    ))}
                    <div style={s('display:flex;gap:6px;margin-top:12px;flex-wrap:wrap')}>
                      {dRefs.map((r, ri) => (
                        <Hoverable key={ri} as="span" base="font-size:11px;font-weight:500;padding:2px 9px;border-radius:999px;border:1px solid var(--bd2);color:var(--tx2);cursor:pointer;background:var(--bg1);font-feature-settings:'tnum' 1" hover="border-color:var(--ac);color:var(--acT)" onClick={tRef}>{r}</Hoverable>
                      ))}
                    </div>

                    {/* JP briefing accordion */}
                    <div style={s('border:1px solid var(--bd);border-radius:14px;margin-top:14px;overflow:hidden')}>
                      <Hoverable base="display:flex;justify-content:space-between;align-items:center;padding:11px 14px;cursor:pointer;background:var(--bg3)" hover="background:var(--bg2)" onClick={toggleJp}>
                        <span style={s('font-size:13px;font-weight:600')}>詳細ブリーフィング（4部構成） <span style={s('font-size:11px;font-weight:400;color:var(--mut)')}>JP authoritative · 日本語正</span></span>
                        {jpOpen && (<RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;color:var(--mut)"><path d="M18 15l-6-6-6 6"></path></svg>`} />)}
                        {!jpOpen && (<RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;color:var(--mut)"><path d="M6 9l6 6 6-6"></path></svg>`} />)}
                      </Hoverable>
                      {jpOpen && (
                        <div style={s('padding:4px 14px 13px;border-top:1px solid var(--dv)')}>
                          {dJp.map((j, ji) => (
                            <div key={ji} style={s('margin-top:10px')}>
                              <div style={s('font-size:12.5px;font-weight:600;color:var(--acT)')}>{j.h}</div>
                              <div style={s('font-size:12.5px;color:var(--tx2);margin-top:3px;line-height:1.7')}>{j.t}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Agenda state for scheduled meetings */}
                {hasAgenda && (
                  <div style={s('margin-top:14px')}>
                    <div style={s('display:flex;align-items:center;gap:9px')}>
                      <span style={s('font-size:11.5px;font-weight:700;letter-spacing:.06em;color:var(--mut)')}>PUBLISHED AGENDA · 公表議題</span>
                      <span style={s("font-size:10.5px;font-weight:600;background:var(--upBg);color:var(--up);border-radius:6px;padding:1px 8px;font-feature-settings:'tnum' 1")}>{dCountdown}</span>
                    </div>
                    {dAgenda.map((ag, agi) => (
                      <div key={agi} style={s('display:flex;gap:8px;font-size:12.5px;color:var(--tx2);margin-top:6px;line-height:1.55')}>
                        <span style={s('width:5px;height:5px;border-radius:999px;background:var(--okDot);margin-top:7px;flex-shrink:0')}></span>
                        <span style={s('flex:1')}>{ag}</span>
                      </div>
                    ))}
                    <div style={s('display:flex;gap:10px;margin-top:14px;flex-wrap:wrap')}>
                      <Hoverable as="span" base="display:inline-flex;align-items:center;gap:6px;background:var(--ac);color:#FFFFFF;border-radius:999px;padding:6px 16px;font-size:12.5px;font-weight:600;cursor:pointer" hover="background:var(--acT)" onClick={tNotifyMe}>
                        <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;flex-shrink:0"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>`} />Notify me when summarised · 要約時に通知
                      </Hoverable>
                      <Hoverable as="span" base="display:inline-flex;align-items:center;gap:6px;border:1px solid var(--bd2);color:var(--tx2);border-radius:999px;padding:6px 16px;font-size:12.5px;font-weight:600;cursor:pointer" hover="border-color:var(--ac);color:var(--acT)" onClick={() => { const n = downloadIcs(`jema-${d.key}.ics`, [{ uid: d.key, date: d.date, summary: dTitle || d.key, description: ((L === 'ja' ? dM.ja : dM.en) || 'METI') + (dM.org ? ' · ' + dM.org : '') }]); toast(n ? (L === 'ja' ? 'カレンダー(.ics)を保存しました' : 'Saved calendar file (.ics)') : (L === 'ja' ? '日付が未定のため出力できません' : 'No date available to export')) }}>
                        <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;flex-shrink:0"><rect x="3" y="4" width="18" height="18" rx="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`} />Add to calendar · ICS
                      </Hoverable>
                    </div>
                    <Hoverable base="display:flex;justify-content:space-between;align-items:center;gap:10px;border:1px solid var(--bd);border-radius:12px;padding:10px 14px;margin-top:14px;cursor:pointer" hover="background:var(--hov)" onClick={dPrevClick}>
                      <span style={s('font-size:12.5px;color:var(--tx2);min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>Previous meeting 前回: <span style={s('font-weight:600;color:var(--tx)')}>{dPrevLabel}</span></span>
                      <span style={s('font-size:12px;font-weight:600;color:var(--acT);white-space:nowrap;flex-shrink:0')}>Open →</span>
                    </Hoverable>
                  </div>
                )}

                {dNoDigest && (
                  <div style={s('margin-top:16px;border:1px dashed var(--fnt2);border-radius:14px;padding:22px;text-align:center')}>
                    <div style={s('font-size:13.5px;font-weight:600;color:var(--tx2)')}>{dEmptyTitle}</div>
                    <div style={s('font-size:12px;color:var(--mut);margin-top:3px')}>{dEmptySub}</div>
                    {dFailed && (
                      <Hoverable as="span" base="display:inline-flex;align-items:center;gap:6px;margin-top:12px;background:var(--ac);color:#FFFFFF;border-radius:999px;padding:6px 16px;font-size:12.5px;font-weight:600;cursor:pointer" hover="background:var(--acT)" onClick={tRetry}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-15 6.7L3 16"></path><path d="M3 21v-5h5"></path></svg>`} />Retry summarisation · 再実行</Hoverable>
                    )}
                    {dIsUn && (
                      <Hoverable as="span" base="display:inline-flex;align-items:center;gap:6px;margin-top:12px;background:var(--ac);color:#FFFFFF;border-radius:999px;padding:6px 16px;font-size:12.5px;font-weight:600;cursor:pointer" hover="background:var(--acT)" onClick={() => queueMeeting(d.key)}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>`} />Track &amp; queue summarisation · 追跡して要約キューへ</Hoverable>
                    )}
                  </div>
                )}

                {/* Audio overview (PROPOSED) */}
                {showAudio && (
                  <div style={s('display:flex;align-items:center;gap:12px;border:1px dashed var(--fnt2);border-radius:14px;padding:11px 14px;margin-top:14px')}>
                    <span style={s('width:36px;height:36px;border-radius:999px;border:1px solid var(--bd2);display:flex;align-items:center;justify-content:center;color:var(--fnt);flex-shrink:0')}><RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`} /></span>
                    <div style={s('flex:1;min-width:0')}>
                      <div style={s('font-size:12.5px;font-weight:600')}>Audio overview <span style={s('font-size:11px;font-weight:400;color:var(--mut)')}>音声概要</span></div>
                      <div style={s('font-size:11px;color:var(--mut)')}>Not generated yet · NotebookLM-style narration · 未生成</div>
                    </div>
                    <span style={s('font-size:9.5px;font-weight:600;background:var(--warnBg);color:var(--warnTx);border-radius:6px;padding:1px 7px;flex-shrink:0')}>PROPOSED</span>
                  </div>
                )}

                {/* Source materials */}
                <div style={s('margin-top:14px;border-top:1px solid var(--dv);padding-top:12px')}>
                  <div style={s('font-size:11.5px;font-weight:700;letter-spacing:.06em;color:var(--mut)')}>SOURCE MATERIALS · 配布資料</div>
                  <div style={s('display:flex;flex-direction:column;gap:2px;margin-top:6px')}>
                    {dDocs.map((doc, di) => (
                      <Hoverable key={di} base="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:7px 10px;border-radius:10px;cursor:pointer" hover="background:var(--hov)" onClick={() => (doc.url ? openUrl(doc.url) : tDoc())}>
                        <span style={s('display:inline-flex;align-items:center;gap:9px;min-width:0;font-size:12.5px;color:var(--tx2)')}>
                          <RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;color:var(--mut);flex-shrink:0"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`} />
                          <span style={s('white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{doc.name}</span>
                        </span>
                        <span style={s("display:inline-flex;align-items:center;gap:8px;flex-shrink:0;font-size:11px;color:var(--mut);font-feature-settings:'tnum' 1")}>{doc.size}<RawSvg html={`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>`} /></span>
                      </Hoverable>
                    ))}
                  </div>
                </div>
                </>
                )}
              </div>
            </div>

          </div>
        </div>
      </div>
    </>
  )
}
