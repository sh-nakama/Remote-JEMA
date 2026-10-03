// The Commands pane: the right-hand mirror of the left navigation pane, local backend only.
//
// It lists the CLI commands `repower web-api` is willing to run (GET /api/commands), as buttons with
// the guidance that used to live only in docs/USER-GUIDE.md right beside each one. The back-catalogue
// workflow ("backflow") comes first, in the order it should be run; read-only diagnostics follow;
// whatever the daily GitHub Actions already do is tucked away last.
//
// Two commands overwrite a whole database (pull-hf, push-hf). They are marked, and each asks for an
// explicit acknowledgement that quotes what the server has recorded about pulls and pushes — see
// `confirmLines`. Everything runs through the same single-flight job runner as the Manage modal, so
// progress and output appear in the progress panel.

import { useMemo, useState, type ReactNode } from 'react'
import { s, Hoverable, press } from './style'
import { useApp } from './app'
import { Modal, icon } from './menus'
import { BADGE, LevelBadge } from './LevelBadge'
import {
  confirmLines, defaultValues, inGroup, missingRequired, pickBi, requestBody, useCommands,
  type Bi, type CommandInfo, type CommandsPayload, type ConfirmLine, type Guards, type ParamSpec, type Values,
} from './commands'

const KEY = 'jema-cmds-open'
const read = (): boolean => {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}
const write = (v: boolean) => {
  try {
    localStorage.setItem(KEY, v ? '1' : '0')
  } catch {
    /* private mode: the pane just forgets its state */
  }
}

const I_TERMINAL = '<polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line>'
const I_COLLAPSE_R = '<path d="M13 17l5-5-5-5"></path><path d="M6 17l5-5-5-5"></path>'
const I_COLLAPSE_L = '<path d="M11 17l-5-5 5-5"></path><path d="M18 17l-5-5 5-5"></path>'
const I_CHEV_D = '<path d="M6 9l6 6 6-6"></path>'
const I_CHEV_U = '<path d="M18 15l-6-6-6 6"></path>'
const I_WARN = '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>'
const I_INFO = '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>'

const PANE = 'width:332px;flex-shrink:0;background:var(--bg1);border-left:1px solid var(--bd);display:flex;flex-direction:column;overflow-y:auto;padding:22px 16px 16px'
// On the three-pane Policy screen an expanded pane would squeeze the detail column to nothing (its left
// side collapses to an icon rail for the same reason), so there it floats over the content instead.
const DRAWER = ';position:fixed;right:0;top:0;bottom:0;z-index:120;box-shadow:var(--shPop)'
const RAIL = 'width:56px;flex-shrink:0;background:var(--bg1);border-left:1px solid var(--bd);display:flex;flex-direction:column;align-items:center;padding:22px 0 16px;gap:4px'
const HEAD = 'font-size:10.5px;font-weight:700;letter-spacing:.09em;color:var(--mut);margin:20px 4px 8px'
const FIELD = 'font-family:inherit;font-size:12.5px;color:var(--tx);background:var(--bg0);border:1px solid var(--bd2);border-radius:9px;padding:6px 9px;min-width:0'

const TONE: Record<ConfirmLine['tone'], string> = {
  danger: 'background:var(--dnBg);color:var(--dn);border:1px solid var(--dn)',
  warn: 'background:var(--warnBg);color:var(--warnTx);border:1px solid var(--warnTx)',
  info: 'background:var(--bg2);color:var(--tx2);border:1px solid var(--bd)',
}

export function CommandsPane() {
  const app = useApp()
  const { interactive, lang, pick, toast, jobRuns, trackJob, openOverlay, setGuideTab, screen } = app
  const [open, setOpen] = useState<boolean>(read)
  const { data, error, reload } = useCommands(interactive)
  const [recipeId, setRecipeId] = useState('backflow')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, Values>>({})
  const [showAuto, setShowAuto] = useState(false)
  const [confirm, setConfirm] = useState<{ cmd: CommandInfo; lines: ConfirmLine[] } | null>(null)
  const [ack, setAck] = useState(false)

  const running = jobRuns.some((r) => r.state === 'running')
  const titles = useMemo(() => {
    const t: Record<string, Bi> = {}
    for (const c of data?.commands ?? []) t[c.id] = c.title
    return t
  }, [data])

  if (!interactive) return null // the read-only deployment has nothing to run

  const toggle = () => {
    write(!open)
    setOpen(!open)
  }

  if (!open) {
    return (
      <div style={s(RAIL)}>
        <Hoverable
          base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--tx2);cursor:pointer;position:relative"
          hover="background:var(--acTint2);color:var(--tx)"
          onClick={toggle}
          title={pick('Commands — run CLI commands from here', 'コマンド — CLIコマンドをここから実行')}
          aria-label={pick('Open the commands pane', 'コマンドパネルを開く')}
        >
          {icon(I_TERMINAL, 19, 'currentColor')}
          {running && <span style={s('position:absolute;top:7px;right:7px;width:8px;height:8px;border-radius:999px;background:var(--ac)')}></span>}
        </Hoverable>
        <div style={s('flex:1')}></div>
        <Hoverable
          base="width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:var(--mut);cursor:pointer"
          hover="background:var(--bg2);color:var(--tx2)"
          onClick={toggle}
          title={pick('Expand · 展開', 'Expand · 展開')}
          aria-label={pick('Expand the commands pane', 'コマンドパネルを展開')}
        >
          {icon(I_COLLAPSE_L, 17, 'currentColor')}
        </Hoverable>
      </div>
    )
  }

  // ---- running a command ----
  const start = (cmd: CommandInfo) => {
    const name = pickBi(cmd.title, 'en')
    const nameJa = pickBi(cmd.title, 'ja')
    fetch('/api/policy/job', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody(cmd, values[cmd.id] ?? defaultValues(cmd))),
    })
      .then(async (r) => {
        const j = (await r.json().catch(() => null)) as { error?: string } | null
        if (r.status === 202) {
          toast(pick(`Started: ${name}`, `実行開始: ${nameJa}`))
          trackJob({
            kind: 'command', title: name, titleJa: nameJa,
            onDone: (run) => {
              reload() // the pull/push guards just changed
              const last = run.output.length ? run.output[run.output.length - 1] : ''
              toast(run.state === 'error'
                ? pick(`Failed: ${name} — ${run.error || last || 'see the activity panel'}`, `失敗: ${nameJa} — ${run.error || last || '進捗パネルをご確認ください'}`)
                : pick(`Finished: ${name}`, `完了: ${nameJa}`))
            },
          })
        } else if (r.status === 409) {
          toast(pick('A job is already running — wait for it to finish', '実行中のジョブがあります。完了までお待ちください'))
        } else {
          toast(pick(`Could not start: ${j?.error || 'request refused'}`, `開始できません: ${j?.error || '要求が拒否されました'}`))
        }
      })
      .catch(() => toast(pick('Could not reach the local API', 'ローカルAPIに接続できません')))
  }

  const requestRun = (cmd: CommandInfo) => {
    if (running) return toast(pick('A job is already running — wait for it to finish', '実行中のジョブがあります。完了までお待ちください'))
    const v = values[cmd.id] ?? defaultValues(cmd)
    const missing = missingRequired(cmd, v)
    if (missing.length) {
      return toast(pick(`Fill in: ${missing.join(', ')}`, `未入力: ${missing.join(', ')}`))
    }
    if (cmd.level !== 'dangerous') return start(cmd)
    // Ask the server *now* what has happened since the pane last loaded — a pull a minute ago
    // matters to the push warning — and fall back to what we have if that fails.
    const show = (g: Guards | null) => {
      setAck(false)
      setConfirm({ cmd, lines: confirmLines(cmd, g, titles, Date.now(), lang) })
    }
    fetch('/api/commands')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('commands'))))
      .then((j: CommandsPayload) => show(j.guards))
      .catch(() => show(data?.guards ?? null))
  }

  const setValue = (cmd: CommandInfo, name: string, v: string | number | boolean) =>
    setValues((prev) => ({ ...prev, [cmd.id]: { ...(prev[cmd.id] ?? defaultValues(cmd)), [name]: v } }))

  const recipe = data?.recipes.find((r) => r.id === recipeId) ?? data?.recipes[0]
  const byId = new Map((data?.commands ?? []).map((c) => [c.id, c]))
  const steps = (recipe?.steps ?? []).map((id) => byId.get(id)).filter((c): c is CommandInfo => !!c)

  const openGuide = () => {
    setGuideTab('commands')
    openOverlay('guide')
  }

  const row = (c: CommandInfo, step?: number) => {
    const isOpen = expanded === c.id
    const danger = c.level === 'dangerous'
    const optional = recipe?.optional.includes(c.id)
    return (
      <div key={c.id} style={s(`border:1px solid ${danger ? 'var(--dn)' : 'var(--bd)'};border-radius:12px;background:var(--bg1);overflow:hidden`)}>
        <Hoverable
          base="display:flex;align-items:center;gap:9px;padding:9px 11px;cursor:pointer"
          hover="background:var(--acTint2)"
          {...press(() => setExpanded(isOpen ? null : c.id), isOpen)}
        >
          {step !== undefined && (
            <span style={s(`width:20px;height:20px;border-radius:999px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:10.5px;font-weight:700;${danger ? 'background:var(--dn);color:#FFFFFF' : 'background:var(--acTint);color:var(--acT)'}`)}>{step}</span>
          )}
          <div style={s('min-width:0;flex:1')}>
            <div style={s('font-size:13px;font-weight:600;color:var(--tx);line-height:1.3')}>{pickBi(c.title, lang)}</div>
            <div style={s('display:flex;gap:5px;flex-wrap:wrap;margin-top:4px;align-items:center')}>
              <LevelBadge level={c.level} lang={lang} />
              {c.needsNotebooklm && <span style={s(`${BADGE};background:var(--bg2);color:var(--tx2)`)}>NotebookLM</span>}
              {optional && <span style={s('font-size:10px;color:var(--mut)')}>{pick('optional', '任意')}</span>}
            </div>
          </div>
          {icon(isOpen ? I_CHEV_U : I_CHEV_D, 15, 'var(--mut)')}
        </Hoverable>
        {isOpen && (
          <div style={s('padding:2px 12px 12px;border-top:1px solid var(--dv)')}>
            <div style={s('font-size:12px;color:var(--tx2);line-height:1.55;margin-top:9px')}>{pickBi(c.summary, lang)}</div>
            <div style={s('font-size:11.5px;color:var(--mut);line-height:1.55;margin-top:6px')}>{pickBi(c.when, lang)}</div>
            {c.params.length > 0 && (
              <div style={s('display:flex;flex-direction:column;gap:7px;margin-top:11px')}>
                {c.params.map((p) => (
                  <label key={p.name} style={s('display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:12px;color:var(--tx2)')}>
                    <span>{pickBi(p.label, lang)}{p.required && <span style={s('color:var(--dn)')}> *</span>}</span>
                    <Field p={p} cmd={c} value={(values[c.id] ?? defaultValues(c))[p.name]} committees={data?.committees ?? []} lang={lang} set={(v) => setValue(c, p.name, v)} />
                  </label>
                ))}
              </div>
            )}
            <div style={s('display:flex;align-items:center;gap:8px;margin-top:12px;flex-wrap:wrap')}>
              <button
                type="button"
                disabled={running}
                onClick={() => requestRun(c)}
                style={s(`font-family:inherit;font-size:12.5px;font-weight:600;border:none;border-radius:999px;padding:6px 16px;cursor:${running ? 'not-allowed' : 'pointer'};opacity:${running ? 0.5 : 1};${danger ? 'background:var(--dn);color:#FFFFFF' : 'background:var(--ac);color:#FFFFFF'}`)}
              >
                {danger ? pick('Review & run…', '確認して実行…') : pick('Run', '実行')}
              </button>
              <Hoverable
                as="span"
                base="font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10.5px;color:var(--mut);background:var(--bg2);border-radius:6px;padding:2px 7px;cursor:pointer"
                hover="color:var(--tx)"
                {...press(() => {
                  navigator.clipboard?.writeText(c.cli).then(
                    () => toast(pick('Copied the terminal command', 'ターミナル用コマンドをコピーしました')),
                    () => toast(c.cli),
                  )
                })}
                title={pick('Copy the equivalent terminal command', '同等のターミナルコマンドをコピー')}
              >{c.cli}</Hoverable>
            </div>
          </div>
        )}
      </div>
    )
  }

  const group = (title: ReactNode, cmds: CommandInfo[]) => (
    <div style={s('display:flex;flex-direction:column;gap:6px')}>
      <div style={s(HEAD)}>{title}</div>
      {cmds.map((c) => row(c))}
    </div>
  )

  const drawer = screen === 'policy'
  return (
    <>
    {drawer && <div style={s(RAIL)}></div> /* keeps the layout the width of the collapsed rail */}
    <div style={s(drawer ? PANE + DRAWER : PANE)}>
      <div style={s('display:flex;align-items:center;gap:8px;padding:0 4px')}>
        {icon(I_TERMINAL, 20, 'var(--ac)')}
        <span style={s('font-size:17px;font-weight:700')}>{pick('Commands', 'コマンド')}</span>
        <span style={s('font-size:11px;color:var(--mut)')}>コマンド</span>
        <span style={s('flex:1')}></span>
        <Hoverable
          as="span"
          base="font-size:11.5px;font-weight:600;color:var(--acT);cursor:pointer;display:inline-flex;align-items:center;gap:4px"
          hover="color:var(--ac)"
          {...press(openGuide)}
          title={pick('Open the guide to these commands', 'コマンドのガイドを開く')}
        >{icon(I_INFO, 13, 'currentColor')}{pick('Guide', 'ガイド')}</Hoverable>
      </div>
      <div style={s('font-size:11.5px;color:var(--mut);margin:4px 4px 0;line-height:1.5')}>
        {pick('Runs on this machine only — the public site has no such buttons.', 'この端末でのみ実行されます。公開サイトにはこのボタンはありません。')}
      </div>

      {error && !data && (
        <div style={s(`${TONE.warn};border-radius:12px;padding:10px 12px;font-size:12px;margin-top:14px;line-height:1.5`)}>
          {pick('Could not load the command list. If `repower web-api` was started before this update, restart it.',
            'コマンド一覧を取得できません。更新前に起動した `repower web-api` の場合は再起動してください。')}
        </div>
      )}
      {!data && !error && <div style={s('font-size:12px;color:var(--mut);margin-top:16px')}>{pick('Loading…', '読み込み中…')}</div>}

      {data && (
        <>
          <div style={s(HEAD)}>{pick('BACKFLOW · 遡及フロー — run in this order', 'BACKFLOW · 遡及フロー — この順に実行')}</div>
          <div style={s('display:flex;gap:6px;flex-wrap:wrap')}>
            {data.recipes.map((r) => (
              <Hoverable
                key={r.id}
                as="span"
                base={`font-size:11.5px;font-weight:600;border-radius:999px;padding:4px 12px;cursor:pointer;${r.id === recipe?.id ? 'background:var(--acTint);color:var(--acT);border:1px solid var(--ac)' : 'color:var(--tx2);border:1px solid var(--bd2)'}`}
                hover="border-color:var(--ac)"
                {...press(() => setRecipeId(r.id), r.id === recipe?.id)}
              >{pickBi(r.title, lang)}</Hoverable>
            ))}
          </div>
          {recipe && <div style={s('font-size:11.5px;color:var(--tx2);line-height:1.55;margin:8px 4px 10px')}>{pickBi(recipe.summary, lang)}</div>}
          <div style={s('display:flex;flex-direction:column;gap:6px')}>
            {steps.map((c, i) => row(c, i + 1))}
          </div>

          {group(pick('INSPECT · 確認 — read-only', 'INSPECT · 確認 — 読み取り専用'), inGroup(data.commands, 'inspect'))}

          <Hoverable
            base="display:flex;align-items:center;gap:6px;margin:20px 4px 8px;cursor:pointer;color:var(--mut)"
            hover="color:var(--tx2)"
            {...press(() => setShowAuto((v) => !v), showAuto)}
          >
            <span style={s('font-size:10.5px;font-weight:700;letter-spacing:.09em')}>{pick('AUTOMATED DAILY · 自動実行', 'AUTOMATED DAILY · 自動実行')}</span>
            <span style={s('flex:1')}></span>
            {icon(showAuto ? I_CHEV_U : I_CHEV_D, 14, 'currentColor')}
          </Hoverable>
          {showAuto ? (
            <div style={s('display:flex;flex-direction:column;gap:6px')}>
              <div style={s('font-size:11.5px;color:var(--mut);margin:0 4px 4px;line-height:1.5')}>
                {pick('The daily GitHub Actions already run these. Reach for them only to catch up after an outage.', '日次のGitHub Actionsで実行済みです。障害後の追い上げにのみ使います。')}
              </div>
              {inGroup(data.commands, 'automated').map((c) => row(c))}
            </div>
          ) : (
            <div style={s('font-size:11.5px;color:var(--mut);margin:0 4px;line-height:1.5')}>
              {pick('Already covered by the daily runs — normally nothing to do.', '日次実行で対応済み。通常は操作不要です。')}
            </div>
          )}
        </>
      )}

      <div style={s('flex:1;min-height:14px')}></div>
      <Hoverable
        base="display:flex;align-items:center;gap:8px;padding:6px 12px;color:var(--mut);font-size:12px;cursor:pointer;border-radius:10px"
        hover="background:var(--bg2);color:var(--tx2)"
        {...press(toggle)}
      >
        {icon(I_COLLAPSE_R, 16, 'currentColor')}<span>{pick('Collapse · 折りたたむ', 'Collapse · 折りたたむ')}</span>
      </Hoverable>

      {confirm && (
        <Modal onClose={() => setConfirm(null)}>
          <div role="alertdialog" aria-modal="true" aria-label={pickBi(confirm.cmd.title, lang)}
            style={s('width:520px;max-width:94vw;background:var(--bg1);border:2px solid var(--dn);border-radius:16px;box-shadow:var(--shPop);padding:20px 22px')}>
            <div style={s('display:flex;align-items:center;gap:10px')}>
              {icon(I_WARN, 22, 'var(--dn)')}
              <span style={s('font-size:16px;font-weight:700')}>{pickBi(confirm.cmd.title, lang)}</span>
              <LevelBadge level="dangerous" lang={lang} />
            </div>
            <div style={s('display:flex;flex-direction:column;gap:8px;margin-top:14px')}>
              {confirm.lines.map((l, i) => (
                <div key={i} style={s(`${TONE[l.tone]};border-radius:10px;padding:9px 12px;font-size:12.5px;line-height:1.55`)}>{l.text}</div>
              ))}
            </div>
            <div style={s('font-size:11.5px;color:var(--mut);margin-top:12px;line-height:1.5')}>
              {pick('Usual order: pull first, do the work, push last — pull and push each replace a whole database and the daily runs write to the same one.',
                '基本の順序: 最初にpull、作業、最後にpush。pullもpushもDB全体を置き換え、日次実行も同じDBに書き込みます。')}
            </div>
            <label style={s('display:flex;align-items:center;gap:8px;margin-top:14px;font-size:12.5px;color:var(--tx);cursor:pointer')}>
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              {pick('I understand this replaces a whole database', 'DB全体が置き換えられることを理解しました')}
            </label>
            <div style={s('display:flex;justify-content:flex-end;gap:10px;margin-top:16px')}>
              <button type="button" onClick={() => setConfirm(null)}
                style={s('font-family:inherit;font-size:13px;font-weight:600;background:var(--bg1);color:var(--tx2);border:1px solid var(--bd2);border-radius:999px;padding:7px 18px;cursor:pointer')}>
                {pick('Cancel', 'キャンセル')}
              </button>
              <button type="button" disabled={!ack || running}
                onClick={() => { const c = confirm.cmd; setConfirm(null); start(c) }}
                style={s(`font-family:inherit;font-size:13px;font-weight:600;background:var(--dn);color:#FFFFFF;border:none;border-radius:999px;padding:7px 18px;cursor:${ack && !running ? 'pointer' : 'not-allowed'};opacity:${ack && !running ? 1 : 0.45}`)}>
                {pick('Run', '実行')}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
    </>
  )
}

/** One form control for a command parameter. */
function Field({ p, cmd, value, committees, lang, set }: {
  p: ParamSpec
  cmd: CommandInfo
  value: string | number | boolean | undefined
  committees: CommandsPayload['committees']
  lang: 'en' | 'ja'
  set: (v: string | number | boolean) => void
}) {
  const name = `${cmd.id}-${p.name}`
  if (p.kind === 'bool') {
    return <input id={name} type="checkbox" checked={!!value} onChange={(e) => set(e.target.checked)} />
  }
  if (p.kind === 'int') {
    return (
      <input id={name} type="number" min={p.lo} max={p.hi} value={value as number | string} onChange={(e) => set(e.target.value)}
        style={s(`${FIELD};width:84px;text-align:right`)} />
    )
  }
  if (p.kind === 'choice') {
    return (
      <select id={name} value={String(value ?? '')} onChange={(e) => set(e.target.value)} style={s(`${FIELD};cursor:pointer`)}>
        {(p.choices ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    )
  }
  // committee
  return (
    <select id={name} value={String(value ?? '')} onChange={(e) => set(e.target.value)} style={s(`${FIELD};cursor:pointer;max-width:176px`)}>
      {p.required
        ? <option value="">{lang === 'ja' ? '選択…' : 'Choose…'}</option>
        : <option value={p.default === 'all' ? 'all' : ''}>{p.default === 'all' ? (lang === 'ja' ? 'すべて' : 'All') : (lang === 'ja' ? '指定なし' : 'Any')}</option>}
      {committees.map((c) => <option key={c.key} value={c.key}>{lang === 'ja' ? c.ja : c.en}</option>)}
    </select>
  )
}

