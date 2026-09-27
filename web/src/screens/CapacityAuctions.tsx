// Ported from screens/capacity-auctions.html — 4th JEMA screen (Capacity & Auctions).
import { useState } from 'react'
import { s, Hoverable, press } from '../lib/style'
import { useApp } from '../lib/app'
import { fmtStamp, SampleTag } from '../lib/freshness'
import { useManifest } from '../lib/data'
import { NotificationsPopover, useNotifSeen, unreadCount } from '../lib/notifications'
import type { NotifItem, NotifSection } from '../lib/notifications'
import { Sidebar, TopBar, PageHeader, ExportButton, useReload } from '../lib/chrome'
import { segBase, areaColor, MONTHS, orgColor } from '../lib/chartkit'
import { CAPACITY_AREAS, maData, ltdaData, ltdaRounds } from './CapacityAuctions.data'
import type { MaRow } from './CapacityAuctions.data'
import { useCapacityLive } from './CapacityAuctions.live'
import { usePolicyMeetings } from './MarketOverview.live'
import { downloadCsv } from '../lib/download'

type View = 'main' | 'ltda'

type CapacityArea = (typeof CAPACITY_AREAS)[number]

/** Areas that cleared at the same price in one auction. */
interface PriceBand {
  price: number
  areas: CapacityArea[]
}

export function CapacityAuctionsScreen() {
  const { lang, theme, setScreen, toast, requestCommittee } = useApp()
  const [view, setView] = useState<View>('main')
  const [showNotif, setShowNotif] = useState(false)

  const L = lang
  const dark = theme === 'dark'

  const goPolicy = () => setScreen('policy')
  const openCommittee = (com: string | undefined, num: number) => {
    if (com) requestCommittee(com, num || null)
    setScreen('policy')
  }
  const openUrl = (url: string | undefined) => {
    if (url && /^https?:\/\//i.test(url)) window.open(url, '_blank', 'noopener,noreferrer')
  }

  // Placeholder / toast handlers
  const tRefresh = useReload()
  const tNotif = () => setShowNotif((n) => !n)
  const tExport = () => {
    const rows = maSrc.map((m) => {
      const rec: Record<string, string | number> = {
        'Delivery FY': m.fy,
        'Auction held': m.held,
        'National average (¥/kW)': m.natl,
      }
      // One column per OCCTO area: the auction clears per area, and which areas
      // share a price changes every year, so the split can't be summarised by a
      // fixed pair of zone columns.
      for (const a of CAPACITY_AREAS) {
        const v = m.areas?.[a.key]
        rec[`${a.en} ${a.ja} (¥/kW)`] = typeof v === 'number' ? v : '—'
      }
      rec['Distinct clearing prices'] = bandsOf(m).length
      rec.Procured = m.proc
      rec['Achievement %'] = m.ach
      rec.Source = m.source ?? ''
      return rec
    })
    downloadCsv('jema-capacity-main-auction.csv', rows)
    toast('Downloaded main-auction results (CSV) · 約定結果をCSVで保存しました')
  }
  const tRow = () => {
    // No per-project detail is published in-app; open OCCTO's official capacity-market
    // section (the auction-results publications live under market-board/market/).
    window.open('https://www.occto.or.jp/market-board/market/index.html', '_blank', 'noopener,noreferrer')
    toast(L === 'ja' ? 'OCCTO 容量市場の公式ページを開きました' : 'Opened OCCTO’s official capacity-market page')
  }

  // Live curated capacity data (fixtures as loading fallback).
  const cap = useCapacityLive()
  const maSrc = cap.ready ? cap.ma : maData
  const ltdaSrc = cap.ready ? cap.ltda : ltdaData
  const roundsSrc = cap.ready && cap.rounds.length ? cap.rounds : ltdaRounds

  // Derived row data
  const numOf = (v: string | number | undefined): number => {
    if (typeof v === 'number') return v
    // Strip ¥ / commas / units. A non-numeric placeholder like "—" must become
    // NaN (not 0) — Number("") is 0, which would draw spurious zero-height bars.
    const cleaned = String(v ?? '').replace(/[^0-9.]/g, '')
    if (cleaned === '') return NaN
    const n = Number(cleaned)
    return Number.isFinite(n) ? n : NaN
  }

  // ---- Clearing-price bands ----
  // The capacity market clears per OCCTO area, and the auction splits wherever
  // an interconnector binds — FY2024 settled at one price nationwide, FY2027 at
  // six. So the "zones" are derived per year by grouping the areas that cleared
  // at the same price, never hardcoded to a Hokkaido/Kyushu pair.
  const bandsOf = (m: MaRow | undefined): PriceBand[] => {
    const by = new Map<number, CapacityArea[]>()
    for (const a of CAPACITY_AREAS) {
      const p = m?.areas?.[a.key]
      if (typeof p !== 'number' || !Number.isFinite(p)) continue
      by.set(p, [...(by.get(p) ?? []), a])
    }
    return [...by.entries()]
      .sort((x, y) => y[0] - x[0])
      .map(([price, areas]) => ({ price, areas }))
  }
  const areaNames = (areas: CapacityArea[]): string =>
    areas.map((a) => (L === 'ja' ? a.ja : a.en)).join(' · ')
  const yen = (v: number): string => (Number.isFinite(v) ? '¥' + Math.round(v).toLocaleString('en-US') : '—')

  const maRows = maSrc.map((m) => {
    const bands = bandsOf(m)
    return {
      ...m,
      bands,
      hi: bands[0]?.price ?? NaN,
      lo: bands[bands.length - 1]?.price ?? NaN,
      bar: {
        display: 'block',
        width: m.ach + '%',
        height: '100%',
        borderRadius: 3,
        background: m.ach >= 99 ? 'var(--ac)' : '#EF9F27',
      } as React.CSSProperties,
    }
  })

  // ---- Main-auction KPI + price-chart model, derived from the live rows so
  // the cards, chart and tables always agree with the results table. ----
  const CH_X0 = 46
  const CH_X1 = 944
  const CH_Y0 = 270
  const CH_TOP = 14
  const chYears = maSrc.slice(-6)
  const chSlotW = (CH_X1 - CH_X0) / Math.max(chYears.length, 1)
  // Y-axis ceiling derived from the plotted prices instead of a hardcoded 16,000.
  // The hi-fi geometry keeps gridlines at fixed y (190/110/30) worth 1·/2·/3·step,
  // with the axis topping out at 3.2·step — so step 5,000 reproduces the export's
  // vmax 16,000 exactly (FY2029's ¥15,112 zonal clears sit just under the top).
  // Recomputing the step keeps future higher-priced rounds on-axis; the ladder
  // fallback (and the empty-data default) still lands on the original 5,000/16,000.
  const CH_STEP_LADDER = [500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000]
  const chDataMax = Math.max(
    0,
    ...chYears
      .flatMap((m) => [numOf(m.natl), ...CAPACITY_AREAS.map((a) => m.areas?.[a.key] ?? NaN)])
      .filter((n) => Number.isFinite(n)),
  )
  const chStep =
    chDataMax > 0
      ? CH_STEP_LADDER.find((st) => st * 3.2 >= chDataMax) ?? Math.ceil(chDataMax / 3.2 / 5000) * 5000
      : 5000
  const CH_VMAX = chStep * 3.2
  const yOf = (v: number) => CH_TOP + ((CH_VMAX - v) / CH_VMAX) * (CH_Y0 - CH_TOP)

  // One bar per area per delivery year: equal bar heights are exactly the areas
  // that cleared together, so the split reads straight off the chart.
  const CH_BAR_GAP = 2
  const chBarW = Math.max(
    5,
    Math.min(16, (chSlotW * 0.84 - CH_BAR_GAP * (CAPACITY_AREAS.length - 1)) / CAPACITY_AREAS.length),
  )
  const chGroupW = chBarW * CAPACITY_AREAS.length + CH_BAR_GAP * (CAPACITY_AREAS.length - 1)
  const maChart = chYears.map((m, i) => {
    const cx = CH_X0 + chSlotW * (i + 0.5)
    const x0 = cx - chGroupW / 2
    const bands = bandsOf(m)
    const nat = numOf(m.natl)
    const hi = bands[0]?.price ?? NaN
    const lo = bands[bands.length - 1]?.price ?? NaN
    return {
      fy: m.fy,
      cx,
      x0,
      hi,
      lo,
      nat,
      natY: yOf(nat),
      natOk: Number.isFinite(nat),
      // Range caption above the group — the whole point of the chart is the spread.
      label: !Number.isFinite(hi) ? '—' : hi === lo ? yen(hi) : yen(lo) + '–' + yen(hi).slice(1),
      labelY: Number.isFinite(hi) ? yOf(hi) - 7 : CH_Y0,
      bars: CAPACITY_AREAS.map((a, j) => {
        const v = m.areas?.[a.key]
        const ok = typeof v === 'number' && Number.isFinite(v)
        return {
          key: a.key,
          name: L === 'ja' ? a.ja : a.en,
          v: ok ? v : NaN,
          ok,
          x: x0 + j * (chBarW + CH_BAR_GAP),
          y: ok ? yOf(v) : CH_Y0,
          h: ok ? CH_Y0 - yOf(v) : 0,
        }
      }),
    }
  })

  const maLast = maSrc[maSrc.length - 1]
  const maPrev = maSrc[maSrc.length - 2]
  const lastBands = bandsOf(maLast)
  const prevBands = bandsOf(maPrev)
  const hiBand = lastBands[0]
  const loBand = lastBands[lastBands.length - 1]
  const spread = (hiBand?.price ?? NaN) - (loBand?.price ?? NaN)
  const deltaChip = (cur: number, prev: number) => {
    if (!Number.isFinite(cur) || !Number.isFinite(prev) || prev === 0)
      return {
        txt: '—',
        style: { background: 'rgba(138,147,163,.14)', color: 'var(--mut)' } as React.CSSProperties,
      }
    const d = cur - prev
    const pct = (d / prev) * 100
    const up = d >= 0
    return {
      txt:
        (up ? '▲ +' : '▼ −') +
        Math.abs(Math.round(d)).toLocaleString('en-US') +
        ' (' + (up ? '+' : '−') + Math.abs(pct).toFixed(1) + '%)',
      style: (up
        ? { background: 'var(--upBg)', color: 'var(--up)' }
        : { background: 'var(--dnBg)', color: 'var(--dn)' }) as React.CSSProperties,
    }
  }
  const hdDelta = deltaChip(numOf(maLast?.natl), numOf(maPrev?.natl))
  const hiDelta = deltaChip(hiBand?.price ?? NaN, prevBands[0]?.price ?? NaN)
  const loDelta = deltaChip(loBand?.price ?? NaN, prevBands[prevBands.length - 1]?.price ?? NaN)

  // ---- notifications (bell popover) ----
  // Capacity data is event-driven (OCCTO publishes once per auction), so the
  // honest signals are: the newest published main-auction result, the running
  // LTDA total, and how fresh the export itself is. Only the auction result and
  // the export carry a real timestamp, so only those can count as unread.
  const manifest = useManifest()
  const { seenAt: notifSeenAt, markSeen: notifMarkSeen } = useNotifSeen('jema-notif-seen-capacity')

  /** "Jan 2026" → ms (UTC, 1st of month), or NaN. */
  const heldTs = (held: string | undefined): number => {
    const m = /^([A-Za-z]{3})\s+(\d{4})$/.exec((held ?? '').trim())
    const mi = m ? MONTHS.indexOf(m[1]) : -1
    return m && mi >= 0 ? Date.UTC(Number(m[2]), mi, 1) : NaN
  }

  const auctionItems: NotifItem[] = []
  if (maLast) {
    const held = heldTs(maLast.held)
    auctionItems.push({
      key: 'ma:' + maLast.fy,
      kind: 'done',
      title:
        L === 'ja'
          ? `${maLast.fy} メインオークション約定`
          : `${maLast.fy} main auction cleared`,
      meta: [
        lastBands.length > 1
          ? (L === 'ja' ? `${lastBands.length}価格帯 ` : `${lastBands.length} zonal prices `) +
            yen(loBand.price) + '–' + yen(hiBand.price).slice(1) + '/kW'
          : (L === 'ja' ? '全エリア一律 ' : 'uniform ') + yen(hiBand?.price ?? NaN) + '/kW',
        (L === 'ja' ? '全国平均 ' : 'national avg ') + maLast.natl + '/kW',
        maLast.proc + (L === 'ja' ? ' 約定' : ' procured'),
        (L === 'ja' ? '目標達成 ' : '') + maLast.ach + '%' + (L === 'ja' ? '' : ' of target'),
      ]
        .filter(Boolean)
        .join(' · '),
      badge: L === 'ja' ? '新規' : 'New',
      ts: Number.isFinite(held) ? held : undefined,
      onClick: () => {
        setShowNotif(false)
        if (maLast.source) window.open(maLast.source, '_blank', 'noopener,noreferrer')
        else tRow()
      },
    })
  }

  // Running LTDA total across the published rounds — a standing fact, not an
  // event, so it has no timestamp and never marks the bell unread.
  const ltdaTotal = ltdaSrc.reduce((n, t) => {
    const g = Number(String(t.cum).replace(/[^0-9.]/g, ''))
    return n + (Number.isFinite(g) ? g : 0)
  }, 0)
  const ltdaItems: NotifItem[] =
    ltdaTotal > 0
      ? [
          {
            key: 'ltda:total',
            kind: 'info',
            title:
              L === 'ja'
                ? `長期脱炭素電源オークション 累計 ${ltdaTotal.toFixed(2)} GW`
                : `Long-term decarbonisation auction · ${ltdaTotal.toFixed(2)} GW awarded`,
            meta:
              L === 'ja'
                ? `${ltdaSrc.length}技術 · 3ラウンド累計`
                : `${ltdaSrc.length} technologies · cumulative over 3 rounds`,
            onClick: () => {
              setView('ltda')
              setShowNotif(false)
            },
          },
        ]
      : []

  const dataItems: NotifItem[] = []
  const mf = manifest.data
  if (mf?.generated_at) {
    const exported = Date.parse(mf.generated_at)
    dataItems.push({
      key: 'freshness',
      kind: 'new',
      title: L === 'ja' ? 'スナップショットを更新しました' : 'Snapshot refreshed',
      meta: L === 'ja' ? `書出 ${fmtStamp(mf.generated_at)}` : `exported ${fmtStamp(mf.generated_at)}`,
      ts: Number.isFinite(exported) ? exported : undefined,
      onClick: tRefresh,
    })
  }

  const notifSections: NotifSection[] = [
    { key: 'auction', label: L === 'ja' ? '約定結果' : 'AUCTION RESULTS', items: auctionItems },
    { key: 'ltda', label: L === 'ja' ? '長期脱炭素電源オークション' : 'LONG-TERM DECARBONISATION', items: ltdaItems },
    { key: 'data', label: L === 'ja' ? 'データ更新' : 'DATA UPDATES', items: dataItems },
  ]
  const notifUnread = unreadCount(notifSections, notifSeenAt)

  const ltdaRows = ltdaSrc.map((t) => ({
    n1: L === 'ja' ? t.ja : t.en,
    n2: L === 'ja' ? t.en : t.ja,
    r1: t.r1,
    r2: t.r2,
    r3: t.r3,
    cum: t.cum,
    share: t.share,
    dot: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: dark ? t.cd : t.c,
      flexShrink: 0,
    } as React.CSSProperties,
    bar: {
      display: 'block',
      width: t.share + '%',
      height: '100%',
      borderRadius: 3,
      background: dark ? t.cd : t.c,
    } as React.CSSProperties,
  }))

  // ---- LTDA: every figure below is derived from the curated OCCTO rounds ----
  const gw = (kw: number) => kw / 1e6
  const pctOf = (a: number, b: number) => (b > 0 ? Math.round((a / b) * 100) : 0)
  const techKw = (key: string, i?: number): number => {
    const kw = ltdaSrc.find((t) => t.key === key)?.kw ?? []
    return i == null ? kw.reduce((a, b) => a + b, 0) : (kw[i] ?? 0)
  }
  const lastR = roundsSrc.length - 1
  const rLast = roundsSrc[lastR]
  const rPrev = roundsSrc[lastR - 1]
  const ltdaKw = roundsSrc.reduce((n, r) => n + r.kw, 0)
  const ltdaPlants = roundsSrc.reduce((n, r) => n + r.plants, 0)
  const roundKwDelta = rLast && rPrev ? gw(rLast.kw) - gw(rPrev.kw) : NaN
  const battShare = (i: number) => pctOf(techKw('battery', i), roundsSrc[i]?.kw ?? 0)
  const decarbShare = (i?: number) =>
    i == null ? pctOf(ltdaKw - techKw('lng'), ltdaKw) : pctOf((roundsSrc[i]?.kw ?? 0) - techKw('lng', i), roundsSrc[i]?.kw ?? 0)
  const fmtDay = (iso: string | undefined) => {
    const [y, m, d] = (iso ?? '').split('-').map(Number)
    if (!y || !m || !d) return '—'
    return L === 'ja' ? `${y}年${m}月${d}日` : `${d} ${MONTHS[m - 1]} ${y}`
  }
  // Stacked bars: one per round, largest technology at the base (rows arrive sorted by total).
  const LT_Y0 = 270
  const LT_TOP = 14
  const ltStep = Math.max(1, Math.ceil((Math.max(0.1, ...roundsSrc.map((r) => gw(r.kw))) * 1.05) / 3))
  const ltY = (g: number) => LT_Y0 - (g / (ltStep * 3)) * (LT_Y0 - LT_TOP)
  const ltSlot = (944 - 46) / Math.max(roundsSrc.length, 1)
  const ltBars = roundsSrc.map((r, i) => {
    const cx = 46 + ltSlot * (i + 0.5)
    let acc = 0
    const segs = ltdaSrc
      .filter((t) => (t.kw?.[i] ?? 0) > 0)
      .map((t) => {
        const g = gw(t.kw[i])
        const y1 = ltY(acc)
        acc += g
        const y2 = ltY(acc)
        return {
          key: t.key,
          y: Math.round(y2 * 10) / 10,
          h: Math.round((y1 - y2) * 10) / 10,
          fill: dark ? t.cd : t.c,
          title: `R${r.round} · ${L === 'ja' ? t.ja : t.en} ${g.toFixed(2)} GW · ${t.plants?.[i] ?? 0} ${L === 'ja' ? '件' : 'plants'}`,
        }
      })
    const [py, pm] = r.published.split('-').map(Number)
    return {
      round: r.round,
      x: Math.round(cx - 55),
      cx: Math.round(cx),
      segs,
      total: gw(r.kw).toFixed(2) + ' GW',
      totalY: Math.round(ltY(acc) - 8),
      label: `Round ${r.round} · results ${MONTHS[pm - 1] ?? ''} ${py || ''}`,
    }
  })
  // Newest OCCTO publication: an LTDA release (exact day) or a main-auction result (month).
  const pubDates = [
    ...roundsSrc.map((r) => ({ t: Date.parse(r.published + 'T00:00:00Z'), txt: r.published })),
    ...(maLast ? [{ t: heldTs(maLast.held), txt: maLast.held }] : []),
  ].filter((p) => Number.isFinite(p.t))
  const lastPublication = pubDates.length ? pubDates.reduce((a, b) => (b.t > a.t ? b : a)).txt : undefined

  // ---- Policy thread: the latest meeting of each capacity-market committee ----
  const CAPACITY_COMMITTEES = ['youryou_kentoukai', 'stable_power_supply_wg', 'emsc_decarbonization', 'chousei_jukyu']
  const pol = usePolicyMeetings()
  const polRows = [...pol.upcoming, ...pol.meetings]
    .filter((p) => p.key && CAPACITY_COMMITTEES.includes(p.key))
    .sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))
    .slice(0, 4)
    .map((p) => ({
      key: (p.key ?? '') + ':' + p.no + (p.sched ? ':s' : ''),
      com: p.key,
      no: p.no,
      n1: L === 'ja' ? p.ja : p.en,
      meta:
        (L === 'ja' ? '第' + p.no + '回 · ' : 'No. ' + p.no + ' · ') +
        (p.dateReal ? fmtDay(p.date) : (L === 'ja' ? '検出 ' : 'detected ') + fmtDay(p.date)) +
        ' · ' + p.tier,
      summary: p.done
        ? (L === 'ja' ? p.sJa : p.sEn) || ''
        : p.sched
          ? ''
          : L === 'ja' ? '要約待ち' : 'Summary pending',
      sched: !!p.sched,
      cta: L === 'ja' ? '詳細を見る →' : 'Deep dive →',
      tierDot: {
        width: 9,
        height: 9,
        borderRadius: 999,
        background: orgColor(p.tier, dark),
        flexShrink: 0,
        marginTop: 6,
      } as React.CSSProperties,
    }))

  return (
    <>
      {/* ============ SIDEBAR ============ */}
      <Sidebar active="capacity" unread={notifUnread} onToggleNotif={tNotif} lastPublication={lastPublication} source="OCCTO auction results · event-driven, not daily" />

      {/* ============ MAIN COLUMN ============ */}
      <div style={s('flex:1;min-width:0;display:flex;flex-direction:column;position:relative')}>

        <TopBar screen="capacity" unread={notifUnread} onToggleNotif={tNotif}>
          {/* Notifications — newest auction result, LTDA total, snapshot freshness */}
          <NotificationsPopover
            open={showNotif}
            lang={L}
            sections={notifSections}
            seenAt={notifSeenAt}
            onClose={() => setShowNotif(false)}
            onMarkRead={notifMarkSeen}
            action={{
              label: L === 'ja' ? 'OCCTO 公式ページ →' : 'OCCTO results →',
              onClick: () => {
                setShowNotif(false)
                tRow()
              },
            }}
          />
        </TopBar>

        {/* Scrollable content */}
        <div style={s('flex:1;overflow-y:auto;padding:26px 32px 40px')}>
          <div style={s('max-width:1500px;margin:0 auto;display:flex;flex-direction:column;gap:20px')}>

            <PageHeader
              screen="capacity"
              subtitle="Main auction results & long-term decarbonization auctions (LTDA) · メインオークションと長期脱炭素電源オークション"
            >
              <ExportButton onClick={tExport} />
            </PageHeader>

            {/* Sub-view switcher */}
            <div style={s('display:flex;align-items:center;gap:14px;flex-wrap:wrap')}>
              <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px')}>
                <span style={segBase(view === 'main')} {...press(() => setView('main'), view === 'main')}>Main Auction メインオークション</span>
                <span style={segBase(view === 'ltda')} {...press(() => setView('ltda'), view === 'ltda')}>LTDA 長期脱炭素</span>
              </div>
              <span style={s('font-size:11.5px;color:var(--mut)')}>Event-driven OCCTO publications — not a daily feed · 公表ベース（日次更新ではありません）</span>
            </div>

            {/* ================= MAIN AUCTION VIEW ================= */}
            {view === 'main' && (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>{maLast?.fy} national average<br />全国平均単価</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{numOf(maLast?.natl).toLocaleString('en-US')} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>¥/kW·year</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>after 経過措置 · main auction {maLast?.held} · vs {maPrev?.fy}<SampleTag failed={cap.failed} /></div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{hdDelta.txt}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Procured capacity<br />調達容量</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{numOf(maLast?.proc).toFixed(1)} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>GW</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{maLast?.ach}% of target · {maLast?.fy} delivery<SampleTag failed={cap.failed} /></div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;font-feature-settings:'tnum' 1;background:rgba(138,147,163,.14);color:var(--mut)")}>{lastBands.length > 1 ? (L === 'ja' ? `${lastBands.length}価格帯に分断` : `${lastBands.length} clearing prices`) : (L === 'ja' ? '全エリア一律' : 'single national price')}</span>
                  </div>
                  {/* Highest / lowest clearing zone of the newest auction — the areas
                      in each are derived from the result, not hardcoded, because the
                      split moves every year. */}
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Highest clearing zone<br />最高値エリア</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{Number.isFinite(hiBand?.price) ? hiBand.price.toLocaleString('en-US') : '—'} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>{hiBand ? areaNames(hiBand.areas) : '—'}<SampleTag failed={cap.failed} /></div>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, fontWeight: 600, padding: '3px 9px', borderRadius: 999, marginTop: 9, fontFeatureSettings: "'tnum' 1", ...hiDelta.style }}>{hiDelta.txt}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Lowest clearing zone<br />最安値エリア</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{Number.isFinite(loBand?.price) ? loBand.price.toLocaleString('en-US') : '—'} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>¥/kW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>{loBand ? areaNames(loBand.areas) : '—'}{Number.isFinite(spread) && spread > 0 ? ` · spread ${yen(spread)}` : ''}<SampleTag failed={cap.failed} /></div>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, fontWeight: 600, padding: '3px 9px', borderRadius: 999, marginTop: 9, fontFeatureSettings: "'tnum' 1", ...loDelta.style }}>{loDelta.txt}</span>
                  </div>
                </div>

                {/* Clearing price chart */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Clearing Price by Area <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>エリア別 約定価格<SampleTag failed={cap.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Main auction · ¥/kW·year · one bar per OCCTO area — equal heights are areas that cleared together · 同一価格のエリアは同じ高さ</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px;flex-shrink:0')}>auction held ~4 years ahead of delivery</span>
                  </div>
                  <svg viewBox="0 0 960 300" style={s('width:100%;height:auto;display:block;margin-top:10px')}>
                    <g style={s('color:var(--grid)')}>
                      <line x1="46" y1="30" x2="944" y2="30" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="110" x2="944" y2="110" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="190" x2="944" y2="190" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      <line x1="46" y1="270" x2="944" y2="270" stroke="currentColor" strokeWidth="1"></line>
                    </g>
                    <g style={s('color:var(--mut)')}>
                      <text x="38" y="34" textAnchor="end" fontSize="11" fill="currentColor">{(chStep * 3).toLocaleString('en-US')}</text>
                      <text x="38" y="114" textAnchor="end" fontSize="11" fill="currentColor">{(chStep * 2).toLocaleString('en-US')}</text>
                      <text x="38" y="194" textAnchor="end" fontSize="11" fill="currentColor">{chStep.toLocaleString('en-US')}</text>
                      {maChart.map((c) => (
                        <text key={c.fy} x={c.cx} y="292" textAnchor="middle" fontSize="11" fill="currentColor">{c.fy}</text>
                      ))}
                    </g>
                    {maChart.map((c) => (
                      <g key={c.fy}>
                        {c.bars.filter((b) => b.ok).map((b) => (
                          <rect key={b.key} x={b.x} y={b.y} width={chBarW} height={b.h} rx="2" fill={areaColor(b.key, dark)}>
                            <title>{`${c.fy} · ${b.name} ¥${b.v.toLocaleString('en-US')}/kW`}</title>
                          </rect>
                        ))}
                        {/* National average unit price — below the clearing prices
                            because the 経過措置 discount is netted off it. */}
                        {c.natOk && (
                          <line x1={c.x0 - 4} y1={c.natY} x2={c.x0 + chGroupW + 4} y2={c.natY} stroke="var(--tx2)" strokeWidth="1.5" strokeDasharray="5 3">
                            <title>{`${c.fy} · national average ¥${Math.round(c.nat).toLocaleString('en-US')}/kW`}</title>
                          </line>
                        )}
                        <text x={c.cx} y={c.labelY} fontSize="10.5" fontWeight="600" textAnchor="middle" style={{ fill: 'var(--tx2)' }}>{c.label}</text>
                      </g>
                    ))}
                  </svg>
                  <div style={s('display:flex;align-items:center;gap:14px;margin-top:10px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap;font-size:11.5px;color:var(--tx2)')}>
                    {CAPACITY_AREAS.map((a) => (
                      <span key={a.key} style={s('display:inline-flex;align-items:center;gap:6px')}>
                        <span style={{ width: 12, height: 12, borderRadius: 4, background: areaColor(a.key, dark) }}></span>
                        {a.en} {a.ja}
                      </span>
                    ))}
                    <span style={s('display:inline-flex;align-items:center;gap:6px')}>
                      <span style={{ width: 12, height: 0, borderTop: '2px dashed var(--tx2)' }}></span>
                      National avg 全国平均単価
                    </span>
                  </div>
                </div>

                {/* Results table */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Auction Results <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>約定結果一覧<SampleTag failed={cap.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Main auction by delivery year · clearing-price range across the OCCTO areas</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>¥/kW·year · GW</span>
                  </div>
                  <div style={s("display:grid;grid-template-columns:.8fr .8fr .9fr 1.3fr .8fr .9fr 1.3fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)")}>
                    <span>DELIVERY 年度</span><span>HELD 実施</span><span style={s('text-align:right')}>NATIONAL AVG 全国平均</span><span style={s('text-align:right')}>ZONAL RANGE 価格帯</span><span style={s('text-align:right')}>ZONES 区分</span><span style={s('text-align:right')}>PROCURED 調達</span><span style={s('text-align:right')}>ACHIEVEMENT 達成率</span>
                  </div>
                  {maRows.map((m) => (
                    <Hoverable key={m.fy} base="display:grid;grid-template-columns:.8fr .8fr .9fr 1.3fr .8fr .9fr 1.3fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer" hover="background:var(--hov)" onClick={() => (m.source ? window.open(m.source, '_blank', 'noopener') : tRow())}>
                      <span style={s("font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>{m.fy}</span>
                      <span style={s("font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{m.held}</span>
                      <span style={s("text-align:right;font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>{m.natl}</span>
                      <span style={s("text-align:right;font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{m.bands.length === 0 ? '—' : m.hi === m.lo ? yen(m.hi) : yen(m.lo) + ' – ' + yen(m.hi)}</span>
                      <span style={s("text-align:right;font-size:12.5px;color:var(--tx2);font-feature-settings:'tnum' 1")}>{m.bands.length <= 1 ? (L === 'ja' ? '一律' : 'uniform') : m.bands.length}</span>
                      <span style={s("text-align:right;font-size:12.5px;font-feature-settings:'tnum' 1")}>{m.proc}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:72px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={m.bar}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{m.ach}%</span>
                      </span>
                    </Hoverable>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>National average = 約定総額（経過措置控除後）÷ 約定総容量, so it sits below the clearing prices · Achievement = 調達容量÷目標調達量 · click a year for the full OCCTO publication</div>
                </div>

                {/* Per-area clearing-price matrix — the split the headline figures hide */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Area Clearing Prices <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>エリア毎の約定価格<SampleTag failed={cap.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Every OCCTO area, every delivery year · shading marks the price bands the auction split into · 濃い網掛けほど高値の価格帯</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>¥/kW·year</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: `1.5fr repeat(${Math.max(maRows.length, 1)}, 1fr)`, gap: 0, marginTop: 12, fontSize: 11, fontWeight: 600, color: 'var(--mut)', letterSpacing: '.04em', padding: '0 8px 8px', borderBottom: '1px solid var(--dv)' }}>
                    <span>AREA エリア</span>
                    {maRows.map((m) => (
                      <span key={m.fy} style={s('text-align:right')}>{m.fy}</span>
                    ))}
                  </div>
                  {CAPACITY_AREAS.map((a) => (
                    <div key={a.key} style={{ display: 'grid', gridTemplateColumns: `1.5fr repeat(${Math.max(maRows.length, 1)}, 1fr)`, gap: 0, alignItems: 'center', padding: '8px', borderBottom: '1px solid var(--dv)' }}>
                      <span style={s('display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600')}>
                        <span style={{ width: 8, height: 8, borderRadius: 999, background: areaColor(a.key, dark), flexShrink: 0 }}></span>
                        {L === 'ja' ? a.ja : a.en} <span style={s('font-size:11px;font-weight:400;color:var(--mut)')}>{L === 'ja' ? a.en : a.ja}</span>
                      </span>
                      {maRows.map((m) => {
                        const v = m.areas?.[a.key]
                        const rank = m.bands.findIndex((b) => b.price === v)
                        // Tint by band rank so the areas that cleared together read
                        // as one block down the column; a uniform year stays flat.
                        const t = m.bands.length > 1 && rank >= 0 ? 0.18 * (1 - rank / (m.bands.length - 1)) : 0
                        return (
                          <span
                            key={m.fy}
                            title={`${m.fy} · ${L === 'ja' ? a.ja : a.en} · ${m.bands.length > 1 && rank >= 0 ? `${L === 'ja' ? '価格帯' : 'band'} ${rank + 1}/${m.bands.length}` : L === 'ja' ? '全国一律' : 'uniform'}`}
                            style={{
                              textAlign: 'right',
                              fontSize: 12.5,
                              fontWeight: rank === 0 && m.bands.length > 1 ? 600 : 400,
                              fontFeatureSettings: "'tnum' 1",
                              padding: '4px 6px',
                              borderRadius: 6,
                              background: t > 0 ? (dark ? `rgba(31,182,220,${t})` : `rgba(0,165,207,${t})`) : 'transparent',
                            }}
                          >
                            {typeof v === 'number' ? yen(v) : '—'}
                          </span>
                        )
                      })}
                    </div>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px')}>The auction splits the national market wherever an interconnector binds, so areas on either side of the constraint clear at different prices · 連系線制約により約定処理が分断されたエリアは別価格で約定します</div>
                </div>
              </div>
            )}

            {/* ================= LTDA VIEW ================= */}
            {view === 'ltda' && (
              <div style={s('display:flex;flex-direction:column;gap:20px')}>

                <div style={s('display:grid;grid-template-columns:repeat(4,1fr);gap:20px')}>
                  <div style={s('background:var(--ac);color:#FFFFFF;border-radius:20px;padding:20px;box-shadow:var(--sh1a)')}>
                    <div style={s('font-size:12px;font-weight:600;color:rgba(255,255,255,.85)')}>Round {rLast?.round} awarded<br />第{rLast?.round}回 落札容量</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{rLast ? gw(rLast.kw).toFixed(2) : '—'} <span style={s('font-size:13px;font-weight:500;color:rgba(255,255,255,.8)')}>GW</span></div>
                    <div style={s('font-size:11px;color:rgba(255,255,255,.75);margin-top:2px')}>results {fmtDay(rLast?.published)} · {rLast?.plants} plants<SampleTag failed={cap.failed} /></div>
                    {Number.isFinite(roundKwDelta) && (
                      <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.24);color:#FFFFFF;margin-top:9px;font-feature-settings:'tnum' 1")}>{roundKwDelta >= 0 ? '▲ +' : '▼ −'}{Math.abs(roundKwDelta).toFixed(2)} GW vs Round {rPrev?.round}</span>
                    )}
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Battery storage share<br />蓄電池シェア</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{battShare(lastR)}<span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>%</span></div>
                    <div style={s("font-size:11px;color:var(--mut);margin-top:2px;font-feature-settings:'tnum' 1")}>{gw(techKw('battery', lastR)).toFixed(2)} GW in R{rLast?.round} · {ltdaSrc.find((t) => t.key === 'battery')?.plants?.[lastR] ?? 0} plants<SampleTag failed={cap.failed} /></div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;font-feature-settings:'tnum' 1;background:rgba(138,147,163,.14);color:var(--mut)")}>{roundsSrc.slice(0, -1).map((r, i) => `R${r.round}: ${battShare(i)}%`).join(' · ')}</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Cumulative awarded<br />累計落札</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{gw(ltdaKw).toFixed(2)} <span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>GW</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>{roundsSrc.length} rounds · {ltdaPlants} plants<SampleTag failed={cap.failed} /></div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;font-feature-settings:'tnum' 1;background:var(--upBg);color:var(--up)")}>storage (battery + pumped) {pctOf(techKw('battery') + techKw('pumped'), ltdaKw)}%</span>
                  </div>
                  <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                    <div style={s('font-size:12px;font-weight:600;color:var(--mut)')}>Decarbonised share<br />脱炭素電源の比率</div>
                    <div style={s("font-size:33px;font-weight:700;margin-top:10px;font-feature-settings:'tnum' 1;line-height:1.15")}>{decarbShare()}<span style={s('font-size:13px;font-weight:500;color:var(--mut)')}>%</span></div>
                    <div style={s('font-size:11px;color:var(--mut);margin-top:2px')}>cumulative · the rest is LNG · 残りはLNG<SampleTag failed={cap.failed} /></div>
                    <span style={s("display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;margin-top:9px;font-feature-settings:'tnum' 1;background:rgba(138,147,163,.14);color:var(--mut)")}>{roundsSrc.map((r, i) => `R${r.round}: ${decarbShare(i)}%`).join(' · ')}</span>
                  </div>
                </div>

                {/* Stacked tech chart */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Awarded Capacity by Technology <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>技術別落札容量<SampleTag failed={cap.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>LTDA rounds 1–{roundsSrc.length} · GW · 20-year fixed revenue contracts · 20年間の固定収入契約</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px;flex-shrink:0')}>hover a segment for detail</span>
                  </div>
                  <svg viewBox="0 0 960 300" style={s('width:100%;height:auto;display:block;margin-top:10px')}>
                    <g style={s('color:var(--grid)')}>
                      {[3, 2, 1].map((k) => (
                        <line key={k} x1="46" y1={ltY(ltStep * k)} x2="944" y2={ltY(ltStep * k)} stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"></line>
                      ))}
                      <line x1="46" y1="270" x2="944" y2="270" stroke="currentColor" strokeWidth="1"></line>
                    </g>
                    <g style={s('color:var(--mut)')}>
                      {[3, 2, 1].map((k) => (
                        <text key={k} x="38" y={ltY(ltStep * k) + 4} textAnchor="end" fontSize="11" fill="currentColor">{ltStep * k} GW</text>
                      ))}
                      {ltBars.map((b) => (
                        <text key={b.round} x={b.cx} y="292" textAnchor="middle" fontSize="11" fill="currentColor">{b.label}</text>
                      ))}
                    </g>
                    {ltBars.map((b) =>
                      b.segs.map((g) => (
                        <rect key={b.round + g.key} x={b.x} y={g.y} width="110" height={g.h} fill={g.fill}>
                          <title>{g.title}</title>
                        </rect>
                      )),
                    )}
                    <g fontSize="11" fontWeight="600" textAnchor="middle" style={s('fill:var(--tx2)')}>
                      {ltBars.map((b) => (
                        <text key={b.round} x={b.cx} y={b.totalY}>{b.total}</text>
                      ))}
                    </g>
                  </svg>
                  <div style={s('display:flex;align-items:center;gap:16px;margin-top:10px;padding-top:12px;border-top:1px solid var(--dv);flex-wrap:wrap;font-size:11.5px;color:var(--tx2)')}>
                    {ltdaSrc.map((t) => (
                      <span key={t.key} style={s('display:inline-flex;align-items:center;gap:6px')}>
                        <span style={{ width: 12, height: 12, borderRadius: 4, background: dark ? t.cd : t.c }}></span>
                        {t.en} {t.ja}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Tech table */}
                <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
                  <div style={s('display:flex;justify-content:space-between;align-items:flex-start')}>
                    <div>
                      <div style={s('font-size:16px;font-weight:600')}>Technology Breakdown <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>技術別内訳<SampleTag failed={cap.failed} /></span></div>
                      <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Awarded GW per round · cumulative share of all LTDA awards</div>
                    </div>
                    <span style={s('font-size:11px;color:var(--mut);padding-top:4px')}>GW</span>
                  </div>
                  <div style={s("display:grid;grid-template-columns:1.7fr .6fr .6fr .6fr .7fr 1.3fr;gap:0;margin-top:12px;font-size:11px;font-weight:600;color:var(--mut);letter-spacing:.04em;padding:0 8px 8px;border-bottom:1px solid var(--dv)")}>
                    <span>TECHNOLOGY · 電源</span><span style={s('text-align:right')}>ROUND 1</span><span style={s('text-align:right')}>ROUND 2</span><span style={s('text-align:right')}>ROUND 3</span><span style={s('text-align:right')}>CUMULATIVE 累計</span><span style={s('text-align:right')}>SHARE シェア</span>
                  </div>
                  {ltdaRows.map((t, i) => (
                    <Hoverable key={i} base="display:grid;grid-template-columns:1.7fr .6fr .6fr .6fr .7fr 1.3fr;gap:0;align-items:center;padding:10px 8px;border-bottom:1px solid var(--dv);border-radius:8px;cursor:pointer" hover="background:var(--hov)" onClick={tRow}>
                      <span style={s('display:flex;align-items:center;gap:9px;min-width:0')}>
                        <span style={t.dot}></span>
                        <span style={s('font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{t.n1} <span style={s('font-weight:400;color:var(--mut);font-size:11.5px')}>{t.n2}</span></span>
                      </span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{t.r1}</span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{t.r2}</span>
                      <span style={s("text-align:right;font-size:13px;font-feature-settings:'tnum' 1")}>{t.r3}</span>
                      <span style={s("text-align:right;font-size:13px;font-weight:600;font-feature-settings:'tnum' 1")}>{t.cum}</span>
                      <span style={s('display:flex;align-items:center;gap:8px;justify-content:flex-end')}>
                        <span style={s('width:72px;height:6px;border-radius:3px;background:var(--bg2);overflow:hidden;flex-shrink:0')}><span style={t.bar}></span></span>
                        <span style={s("font-size:12px;font-weight:600;width:34px;text-align:right;font-feature-settings:'tnum' 1")}>{t.share}%</span>
                      </span>
                    </Hoverable>
                  ))}
                  <div style={s('font-size:11px;color:var(--mut);margin-top:10px;display:flex;flex-wrap:wrap;gap:4px 10px')}>
                    <span>Summed from OCCTO&apos;s per-plant award lists · 落札電源一覧より集計 · results:</span>
                    {roundsSrc.map((r) =>
                      r.source ? (
                        <Hoverable key={r.round} as="span" base="color:var(--acT);cursor:pointer" hover="color:var(--ac)" onClick={() => openUrl(r.source)}>
                          Round {r.round} ({r.published}) ↗
                        </Hoverable>
                      ) : (
                        <span key={r.round}>Round {r.round} ({r.published})</span>
                      ),
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Policy thread (always visible) */}
            <div style={s('background:var(--bg1);border-radius:20px;padding:20px;box-shadow:var(--sh1)')}>
              <div style={s('display:flex;justify-content:space-between;align-items:flex-start;gap:12px')}>
                <div>
                  <div style={s('display:flex;align-items:center;gap:9px')}>
                    <span style={s('font-size:16px;font-weight:600')}>Policy Thread — Capacity Market <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>政策スレッド：容量市場</span></span>
                  </div>
                  <div style={s('font-size:12px;color:var(--mut);margin-top:1px')}>Latest meetings of the committees that shape the capacity market and the LTDA · 容量市場・長期脱炭素電源オークションに関わる会議体の直近の会合</div>
                </div>
                <Hoverable as="span" base="font-size:12.5px;font-weight:600;color:var(--acT);cursor:pointer;white-space:nowrap;padding-top:4px" hover="color:var(--ac)" onClick={goPolicy}>Open Policy Deep Dive →</Hoverable>
              </div>
              <div style={s('display:flex;flex-direction:column;margin-top:8px')}>
                {polRows.length === 0 && (
                  <div style={s('padding:12px 4px;border-top:1px solid var(--dv);font-size:12.5px;color:var(--mut)')}>
                    {pol.failed
                      ? L === 'ja' ? '会合データを読み込めませんでした。' : 'Committee meetings could not be loaded.'
                      : pol.ready
                        ? L === 'ja' ? '該当する会合はまだありません。' : 'No meetings recorded for these committees yet.'
                        : L === 'ja' ? '会合を読み込み中…' : 'Loading committee meetings…'}
                  </div>
                )}
                {polRows.map((p) => (
                  <Hoverable key={p.key} base="display:flex;gap:12px;align-items:flex-start;padding:12px 4px;border-top:1px solid var(--dv);cursor:pointer;border-radius:8px" hover="background:var(--hov)" onClick={() => openCommittee(p.com, p.no)}>
                    <span style={p.tierDot}></span>
                    <div style={s('flex:1;min-width:0')}>
                      <div style={s('display:flex;align-items:center;gap:8px;min-width:0')}>
                        <span style={s('font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{p.n1}</span>
                        {p.sched && (
                          <span style={s('font-size:10.5px;font-weight:600;background:var(--upBg);color:var(--up);border-radius:6px;padding:1px 7px;flex-shrink:0')}>Scheduled 開催予定</span>
                        )}
                      </div>
                      <div style={s("font-size:11.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-feature-settings:'tnum' 1")}>{p.meta}</div>
                      <div style={s('font-size:12.5px;color:var(--tx2);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')}>{p.summary}</div>
                    </div>
                    <span style={s('font-size:12.5px;font-weight:600;color:var(--acT);white-space:nowrap;flex-shrink:0;padding-top:2px')}>{p.cta}</span>
                  </Hoverable>
                ))}
              </div>
            </div>

            <div style={s('font-size:12px;color:var(--mut);text-align:center;padding:2px 0 6px')}>Published by OCCTO · 容量市場・長期脱炭素電源オークション約定結果 · event-driven · last publication {lastPublication ?? '—'}</div>

          </div>
        </div>
      </div>
    </>
  )
}
