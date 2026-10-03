// Balancing market, per TSO area: required / offered / contracted MW (left) beside
// the ΔkW price band (right), one row per selected area — the same two-column
// layout the Streamlit dashboard uses. Reads the `balancing/{code}/{area}/{level}.json`
// snapshots that `repower export-web` already writes (Native = 30-minute slots).
import { useEffect, useMemo, useState } from 'react'
import { ChartFrame, PLOT_W, PLOT_X0, bandPoints, gapSegments, segPoints } from '../lib/chart'
import { fmtDate } from '../lib/chartkit'
import { getSnapshot, useDataNonce } from '../lib/data'
import { s } from '../lib/style'
import { parseWallClock } from '../lib/time'
import { areas } from './MarketData.data'
import { BAL_CODES, DAY_MS, effectiveRangeDays, type Gran, type Range } from './MarketData.live'

interface VolRow {
  datetime: string
  demand_mw: number | null
  bid_volume_mw: number | null
  contracted_mw: number | null
  missing_mw: number | null
}
interface PriceRow {
  datetime: string
  price_max: number | null
  price_avg: number | null
  price_min: number | null
}
interface BalAreaSnapshot {
  volume: VolRow[]
  price: PriceRow[]
}

const PRODUCTS = [
  { code: BAL_CODES[0], en: 'Primary', ja: '一次' },
  { code: BAL_CODES[1], en: 'Secondary 1', ja: '二次①' },
  { code: BAL_CODES[2], en: 'Secondary 2', ja: '二次②' },
  { code: BAL_CODES[3], en: 'Tertiary 1', ja: '三次①' },
  { code: BAL_CODES[4], en: 'Tertiary 2', ja: '三次②' },
]

const MAX_POINTS = 720
const H_TOP = 12
const H_BOT = 150

const num = (x: number | null | undefined) => (typeof x === 'number' && Number.isFinite(x) ? x : NaN)
const fmt = (x: number, d = 0) => (Number.isFinite(x) ? x.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }) : '—')

/** Rows (ascending by time) whose datetime lies in [t0, t1], decimated to the plot budget. */
function windowRows<T extends { datetime: string }>(rows: T[], t0: number, t1: number) {
  const hit: { r: T; t: number }[] = []
  for (const r of rows) {
    const t = parseWallClock(r.datetime)
    if (Number.isFinite(t) && t >= t0 && t <= t1) hit.push({ r, t })
  }
  if (hit.length <= MAX_POINTS) return hit
  const step = Math.ceil(hit.length / MAX_POINTS)
  const out = hit.filter((_, i) => i % step === 0)
  if (out[out.length - 1] !== hit[hit.length - 1]) out.push(hit[hit.length - 1])
  return out
}

function newest<T extends { datetime: string }>(rows: T[], has: (r: T) => boolean): number {
  for (let i = rows.length - 1; i >= 0; i--) {
    if (has(rows[i])) {
      const t = parseWallClock(rows[i].datetime)
      if (Number.isFinite(t)) return t
    }
  }
  return NaN
}

const fmtDT = (iso: string) => (iso.length > 10 ? `${fmtDate(iso)} ${iso.slice(11, 16)}` : fmtDate(iso))

interface Props {
  sel: Record<string, boolean>
  gran: Gran
  range: Range
  L: string
}

export function BalancingAreaGrid({ sel, gran, range, L }: Props) {
  const nonce = useDataNonce()
  const [code, setCode] = useState<string>(BAL_CODES[0])
  const [data, setData] = useState<Record<string, BalAreaSnapshot | null>>({})
  const [loading, setLoading] = useState(false)
  const selected = areas.filter((a) => sel[a.key])
  const keysCsv = selected.map((a) => a.key).join(',')

  useEffect(() => {
    const keys = keysCsv ? keysCsv.split(',') : []
    let alive = true
    setLoading(true)
    Promise.all(
      keys.map((k) =>
        getSnapshot<BalAreaSnapshot>(`balancing/${code}/${k}/${gran}.json`)
          .then((d) => [k, d] as const)
          .catch(() => [k, null] as const),
      ),
    ).then((entries) => {
      if (!alive) return
      setData(Object.fromEntries(entries))
      setLoading(false)
    })
    return () => {
      alive = false
    }
  }, [keysCsv, code, gran, nonce])

  // Anchor every chart on the newest EPRX slot among the loaded areas so they share an axis.
  const dom = useMemo<[number, number] | null>(() => {
    let a = NaN
    for (const d of Object.values(data)) {
      if (!d) continue
      const t = Math.max(newest(d.volume, (r) => Number.isFinite(num(r.demand_mw))), newest(d.price, (r) => Number.isFinite(num(r.price_avg))))
      if (Number.isFinite(t) && !(t <= a)) a = t
    }
    return Number.isFinite(a) ? [a - effectiveRangeDays(gran, range) * DAY_MS, a] : null
  }, [data, gran, range])

  const xOfT = (t: number) => (dom ? PLOT_X0 + ((t - dom[0]) / (dom[1] - dom[0])) * PLOT_W : PLOT_X0)

  const card = 'background:var(--bg1);border-radius:20px;padding:18px 20px;box-shadow:var(--sh1)'
  const ttl = 'font-size:14px;font-weight:600'
  const sub = 'font-size:11px;color:var(--mut)'
  const legend = (c: string, t: string) => (
    <span style={s('display:inline-flex;align-items:center;gap:5px')}>
      <span style={s(`width:10px;height:10px;border-radius:3px;background:${c}`)}></span>
      {t}
    </span>
  )

  return (
    <div style={s('display:flex;flex-direction:column;gap:14px')}>
      <div style={s('display:flex;align-items:center;gap:10px;flex-wrap:wrap')}>
        <span style={s('font-size:16px;font-weight:600')}>
          {L === 'ja' ? 'エリア別 需給調整市場' : 'Balancing by area'}{' '}
          <span style={s('font-size:12.5px;font-weight:400;color:var(--mut)')}>
            {gran === 'Native' ? '30-min slots' : gran} · {range}
          </span>
        </span>
        <div style={s('display:flex;background:var(--bg2);border-radius:999px;padding:3px;margin-left:auto')} role="group" aria-label="Product">
          {PRODUCTS.map((p) => (
            <button
              key={p.code}
              type="button"
              aria-pressed={code === p.code}
              onClick={() => setCode(p.code)}
              style={s(
                `border:0;cursor:pointer;font:inherit;font-size:12px;font-weight:600;padding:4px 12px;border-radius:999px;white-space:nowrap;background:${code === p.code ? 'var(--bg1)' : 'transparent'};color:${code === p.code ? 'var(--tx)' : 'var(--mut)'}`,
              )}
            >
              {p.en} <span style={s('font-weight:400')}>{p.ja}</span>
            </button>
          ))}
        </div>
      </div>

      {selected.length === 0 && <div style={s(sub)}>Select at least one area above.</div>}

      {selected.map((a) => {
        const d = data[a.key]
        const title = (
          <span style={s('background:var(--bg1);border:1px solid var(--bd);border-radius:999px;padding:4px 14px;font-size:12.5px;font-weight:600;align-self:flex-start')}>
            {a.en} <span style={s('font-weight:400;color:var(--mut)')}>{a.ja}</span>
          </span>
        )
        if (!d || !dom) {
          return (
            <div key={a.key} style={s('display:flex;flex-direction:column;gap:10px')}>
              {title}
              <div style={s(sub)}>{loading || !(a.key in data) ? 'Loading…' : `No ${PRODUCTS.find((p) => p.code === code)?.en} data for this area · この商品のデータなし`}</div>
            </div>
          )
        }

        const vw = windowRows(d.volume, dom[0], dom[1]).filter((p) => Number.isFinite(num(p.r.demand_mw)))
        const pw = windowRows(d.price, dom[0], dom[1]).filter((p) => Number.isFinite(num(p.r.price_avg)))

        const vmax = Math.max(1, ...vw.map((p) => Math.max(num(p.r.demand_mw) || 0, num(p.r.bid_volume_mw) || 0, num(p.r.contracted_mw) || 0))) * 1.08
        const vy = (v: number) => H_BOT - (v / vmax) * (H_BOT - H_TOP)
        const vt = vw.map((p) => p.t)
        const vxs = vt.map(xOfT)
        const vSegs = gapSegments(vt).filter(([a0, a1]) => a1 > a0)
        const vline = (pick: (r: VolRow) => number | null) => vSegs.map((sg) => segPoints(sg, (i) => vxs[i], (i) => vy(num(pick(vw[i].r)) || 0)))

        const pmin = pw.length ? Math.min(...pw.map((p) => num(p.r.price_min ?? p.r.price_avg))) : 0
        const pmax = pw.length ? Math.max(...pw.map((p) => num(p.r.price_max ?? p.r.price_avg))) : 1
        const plo = Math.max(0, pmin * 0.92)
        const phi = pmax * 1.05 || 1
        const py = (v: number) => H_BOT - ((v - plo) / (phi - plo || 1)) * (H_BOT - H_TOP)
        const pt = pw.map((p) => p.t)
        const pxs = pt.map(xOfT)
        const pSegs = gapSegments(pt).filter(([a0, a1]) => a1 > a0)
        const pline = (pick: (r: PriceRow) => number | null) => pSegs.map((sg) => segPoints(sg, (i) => pxs[i], (i) => py(num(pick(pw[i].r)))))

        const ax = (rows: { t: number }[]) => {
          const n = rows.length
          return n ? [fmtDate(new Date(rows[0].t).toISOString()), fmtDate(new Date(rows[Math.floor((n - 1) / 2)].t).toISOString()), fmtDate(new Date(rows[n - 1].t).toISOString())] : ['', '', '']
        }
        const vax = ax(vw)
        const pax = ax(pw)

        return (
          <div key={a.key} style={s('display:flex;flex-direction:column;gap:10px')}>
            {title}
            <div style={s('display:grid;grid-template-columns:1fr 1fr;gap:20px')}>
              <div style={s(card)}>
                <div style={s('display:flex;justify-content:space-between;align-items:baseline')}>
                  <span style={s(ttl)}>Volume <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>調達量</span></span>
                  <span style={s(sub)}>required / offered / contracted · MW</span>
                </div>
                <ChartFrame
                  n={vw.length}
                  label={(i) => fmtDT(vw[i]?.r.datetime ?? '')}
                  xs={vxs}
                  dotY={(i) => vy(num(vw[i].r.contracted_mw) || 0)}
                  tip={(i) => (
                    <>
                      <span>req {fmt(num(vw[i].r.demand_mw))}</span>{' · '}
                      <span style={s('color:#4A6FA5')}>offered {fmt(num(vw[i].r.bid_volume_mw))}</span>{' · '}
                      <span style={s('color:#2A9D8F')}>contracted {fmt(num(vw[i].r.contracted_mw))}</span>{' · '}
                      <span style={s('color:#E24B4A')}>short {fmt(Math.max(0, (num(vw[i].r.demand_mw) || 0) - (num(vw[i].r.contracted_mw) || 0)))} MW</span>
                    </>
                  )}
                >
                  {vSegs.map((sg, i) => <polygon key={'u' + i} points={bandPoints(sg, (k) => vxs[k], (k) => vy(num(vw[k].r.demand_mw) || 0), (k) => vy(Math.min(num(vw[k].r.demand_mw) || 0, num(vw[k].r.contracted_mw) || 0)))} fill="#F48FB1" fillOpacity="0.55" />)}
                  {vline((r) => r.bid_volume_mw).map((p, i) => <polyline key={'o' + i} points={p} fill="none" stroke="#4A6FA5" strokeWidth="1.5" />)}
                  {vline((r) => r.contracted_mw).map((p, i) => <polyline key={'c' + i} points={p} fill="none" stroke="#2A9D8F" strokeWidth="1.6" />)}
                  <g style={s('color:var(--tx)')}>{vline((r) => r.demand_mw).map((p, i) => <polyline key={'d' + i} points={p} fill="none" stroke="currentColor" strokeWidth="1.8" />)}</g>
                </ChartFrame>
                <div style={s("display:flex;justify-content:space-between;padding:0 1.67%;margin-top:5px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                  <span>{vax[0]}</span><span>{vax[1]}</span><span>{vax[2]}</span>
                </div>
                <div style={s('display:flex;align-items:center;gap:14px;margin-top:9px;font-size:11px;color:var(--tx2);flex-wrap:wrap')}>
                  {legend('var(--tx)', 'Required 必要量')}
                  {legend('#4A6FA5', 'Offered 応札')}
                  {legend('#2A9D8F', 'Contracted 約定')}
                  {legend('#F48FB1', 'Under-procured 調達不足')}
                </div>
              </div>
              <div style={s(card)}>
                <div style={s('display:flex;justify-content:space-between;align-items:baseline')}>
                  <span style={s(ttl)}>Price <span style={s('font-size:11.5px;font-weight:400;color:var(--mut)')}>価格</span></span>
                  <span style={s(sub)}>max / avg / min · ¥/ΔkW·30min</span>
                </div>
                <ChartFrame
                  n={pw.length}
                  label={(i) => fmtDT(pw[i]?.r.datetime ?? '')}
                  xs={pxs}
                  dotY={(i) => py(num(pw[i].r.price_avg))}
                  tip={(i) => (
                    <>
                      <span style={s('color:#E24B4A')}>max ¥{fmt(num(pw[i].r.price_max), 2)}</span>{' · '}
                      <span>avg ¥{fmt(num(pw[i].r.price_avg), 2)}</span>{' · '}
                      <span style={s('color:#00A5CF')}>min ¥{fmt(num(pw[i].r.price_min), 2)}</span>
                    </>
                  )}
                >
                  {pSegs.map((sg, i) => <polygon key={'b' + i} points={bandPoints(sg, (k) => pxs[k], (k) => py(num(pw[k].r.price_max ?? pw[k].r.price_avg)), (k) => py(num(pw[k].r.price_min ?? pw[k].r.price_avg)))} fill="#00A5CF" fillOpacity="0.10" />)}
                  {pline((r) => r.price_max).map((p, i) => <polyline key={'x' + i} points={p} fill="none" stroke="#E24B4A" strokeWidth="1.4" />)}
                  <g style={s('color:var(--tx)')}>{pline((r) => r.price_avg).map((p, i) => <polyline key={'a' + i} points={p} fill="none" stroke="currentColor" strokeWidth="1.8" />)}</g>
                  {pline((r) => r.price_min).map((p, i) => <polyline key={'i' + i} points={p} fill="none" stroke="#00A5CF" strokeWidth="1.4" />)}
                </ChartFrame>
                <div style={s("display:flex;justify-content:space-between;padding:0 1.67%;margin-top:5px;font-size:10px;color:var(--mut);font-feature-settings:'tnum' 1")}>
                  <span>{pax[0]}</span><span>{pax[1]}</span><span>{pax[2]}</span>
                </div>
                <div style={s('display:flex;align-items:center;gap:14px;margin-top:9px;font-size:11px;color:var(--tx2);flex-wrap:wrap')}>
                  {legend('#E24B4A', 'Max')}
                  {legend('var(--tx)', 'Avg')}
                  {legend('#00A5CF', 'Min')}
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
