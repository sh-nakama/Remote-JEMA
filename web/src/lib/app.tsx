import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { AreaKey, Level } from './types'
import { refreshSnapshots } from './data'

/**
 * App-wide state mirroring the exports' DCLogic: theme + lang (persisted to
 * localStorage under the same keys the exports use — jema-theme / jema-lang),
 * the active screen (the exports navigate via window.location.href to sibling
 * .html files; here that becomes a client-side screen switch), and a transient
 * toast (used by the exports' placeholder `tNav` handlers).
 *
 * Phase 4 extends this into the app's persistence layer for the (single-tenant,
 * no-auth) working menus: a localStorage-backed watchlist, user settings
 * (default landing screen + default granularity), sidebar collapse state, a
 * global overlay switch (⌘K search / Settings / Watchlist), and a transient
 * "focus area" used to hand a target area from the ⌘K palette to Market Data.
 */

export type Lang = 'en' | 'ja'
export type Theme = 'light' | 'dark'
export type Screen = 'overview' | 'market' | 'policy' | 'capacity'
export type Overlay = 'search' | 'settings' | 'watchlist' | 'committees' | 'guide'

/** A single starred entity. `id` is the stable key (e.g. `area:tepco`). */
export interface WatchEntry {
  id: string
  kind: 'area' | 'committee'
  en: string
  ja: string
  /** Screen to open when the entry is activated. */
  screen: Screen
}

/** One reported step of a background job (the catch-up job populates these). */
export interface JobStage {
  key: string
  label: string
  label_ja: string
  state: string // running | done | error
  detail?: string | null
  detail_ja?: string | null
}

/** Structured result of a completed catch-up job (absent for other job kinds). */
export interface PolicyCatchupResult {
  new_meetings?: number
  dated?: number
  discovered?: number
  pending?: number
  upcoming?: number | null
}

/** A single tracked run shown in the progress panel + its history. */
export interface JobRun {
  id: number
  kind: string
  title: string
  titleJa: string
  state: 'running' | 'done' | 'error'
  stages: JobStage[]
  output: string[]
  result: PolicyCatchupResult | null
  error: string | null
  startedAt: number
  finishedAt: number | null
}

/** What `trackJob` needs to begin mirroring a backend job into the panel. */
export interface JobTrackMeta {
  kind: string
  title: string
  titleJa: string
  /** Job-status endpoint to poll (default `/api/policy/job`). */
  endpoint?: string
  onDone?: (run: JobRun) => void
}

/** Raw job-status payload from the web API. */
interface RawJob {
  state?: string
  stages?: JobStage[]
  output?: string[]
  result?: unknown
  error?: string | null
  cmd?: string
  kind?: string
}

export interface AppState {
  lang: Lang
  setLang: (l: Lang) => void
  theme: Theme
  setTheme: (t: Theme) => void
  toggleTheme: () => void
  screen: Screen
  setScreen: (s: Screen) => void
  toast: (msg: string) => void
  toastMsg: string | null
  /** pick(en, ja) — the common inline bilingual selector. */
  pick: (en: string, ja: string) => string

  // ---- Phase 4: menus + persistence ----
  /** Which global overlay is open (null = none). */
  overlay: Overlay | null
  openOverlay: (o: Overlay) => void
  closeOverlay: () => void

  /** Sidebar collapsed to a hidden rail (persisted). */
  collapsed: boolean
  toggleCollapsed: () => void

  /** Starred entities (persisted). */
  watch: WatchEntry[]
  isWatched: (id: string) => boolean
  toggleWatch: (e: WatchEntry) => void
  clearWatch: () => void

  /** Followed committees, by committee key (client-side preference, persisted).
   * Seeded with the priority committees on first visit. Drives the Committee
   * Radar's "Followed" filter and the Policy screen's follow toggles. */
  followed: string[]
  isFollowing: (key: string) => boolean
  toggleFollow: (key: string) => void

  /** Archived committees (persisted overrides). Committees whose last meeting was
   * in 2025 or earlier are archived out of the Explorer by default; an explicit
   * entry here (true/false) wins over that default, so the user can restore an
   * archived committee or re-archive an active one. */
  archiveOverrides: Record<string, boolean>
  setArchived: (key: string, archived: boolean) => void
  /** User settings (persisted). */
  homeScreen: Screen
  setHomeScreen: (s: Screen) => void
  defaultGran: Level
  setDefaultGran: (l: Level) => void

  /** Transient: an area the ⌘K palette asked Market Data to focus. */
  focusArea: AreaKey | null
  requestArea: (a: AreaKey) => void
  clearFocusArea: () => void

  /** Transient: a committee (and meeting number, when known) that another screen
   * asked Policy Deep Dive to open — e.g. a row of the Overview radar. */
  focusCommittee: { com: string; num: number | null } | null
  requestCommittee: (com: string, num?: number | null) => void
  clearFocusCommittee: () => void

  /** True when a local backend API (`repower web-api`) is reachable — enables the
   * write controls (track committees) and the Run catch-up button. False on the
   * static GitHub Pages deployment, which is read-only. */
  interactive: boolean

  /** Clear the snapshot cache and refetch every data hook — the real work behind
   * the "Refresh" buttons (picks up a freshly re-run `repower export-web`). */
  refreshData: () => void

  /** True for a brief window after `refreshData()` while snapshots refetch —
   * drives the spinning refresh icon so the reload is visibly in progress. */
  refreshing: boolean

  /** Recent background-job runs (newest first) shown in the progress panel —
   * catch-up and full-refresh push a JobRun here as they run. */
  jobRuns: JobRun[]
  /** Mirror a just-started backend job into `jobRuns` (drives the panel). */
  trackJob: (meta: JobTrackMeta) => void
  /** Progress panel collapsed to a compact pill (persisted). */
  panelMin: boolean
  setPanelMinimized: (min: boolean) => void
  /** Remove one run from the panel history. */
  dismissRun: (id: number) => void
  /** Clear finished runs from the panel history (keeps a running one). */
  clearRuns: () => void
}

const Ctx = createContext<AppState | null>(null)

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, v: string): void {
  try {
    localStorage.setItem(key, v)
  } catch {
    /* ignore */
  }
}
function readJson<T>(key: string, fallback: T): T {
  const raw = read(key)
  if (raw == null) return fallback
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

const SCREENS: Screen[] = ['overview', 'market', 'policy', 'capacity']
const LEVELS: Level[] = ['Native', 'Daily', 'Weekly', 'Monthly']

// Committees a new user follows by default (the priority committees). Only used
// when the key has never been written, so an intentional empty set is preserved.
const DEFAULT_FOLLOW = ['system_review', 'emissions_trading', 'chousei_jukyu']

export function AppProvider({
  children,
  initialScreen,
}: {
  children: React.ReactNode
  initialScreen?: Screen
}) {
  const storedHome = read('jema-home') as Screen | null
  const homeInit: Screen =
    initialScreen || (storedHome && SCREENS.includes(storedHome) ? storedHome : 'overview')

  const [lang, setLangS] = useState<Lang>((read('jema-lang') as Lang) || 'en')
  const [theme, setThemeS] = useState<Theme>((read('jema-theme') as Theme) || 'light')
  const [screen, setScreen] = useState<Screen>(homeInit)
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const tRef = useRef<number | null>(null)

  const [overlay, setOverlay] = useState<Overlay | null>(null)
  const [collapsed, setCollapsed] = useState<boolean>(read('jema-collapse') === '1')
  const [watch, setWatch] = useState<WatchEntry[]>(() => readJson<WatchEntry[]>('jema-watch', []))
  const [followed, setFollowed] = useState<string[]>(() => {
    const raw = read('jema-follow-committees')
    if (raw == null) return DEFAULT_FOLLOW // first visit → seed with priority committees
    try {
      const v = JSON.parse(raw)
      return Array.isArray(v) ? (v as string[]) : DEFAULT_FOLLOW
    } catch {
      return DEFAULT_FOLLOW
    }
  })
  const [archiveOverrides, setArchiveOverrides] = useState<Record<string, boolean>>(() =>
    readJson<Record<string, boolean>>('jema-archive-committees', {}),
  )
  const [homeScreen, setHomeScreenS] = useState<Screen>(homeInit)
  const [defaultGran, setDefaultGranS] = useState<Level>(() => {
    const g = read('jema-gran') as Level | null
    return g && LEVELS.includes(g) ? g : 'Daily'
  })
  const [focusArea, setFocusArea] = useState<AreaKey | null>(null)
  const [focusCommittee, setFocusCommittee] = useState<{ com: string; num: number | null } | null>(null)
  const [interactive, setInteractive] = useState(false)

  // Interactive mode = a local backend (`repower web-api`) is reachable, which
  // enables the write controls (track / priority / run catch-up). Probe
  // `/api/health` regardless of dev-vs-built so a locally-served build works too
  // as long as the API is up; GitHub Pages has no `/api`, so the probe fails and
  // the app stays read-only. Require `mode: "local"` so a stray SPA 200 (e.g. an
  // index.html fallback) can't switch it on. Re-probe on window focus so starting
  // the API and clicking back into the tab flips it on without a manual reload.
  useEffect(() => {
    let alive = true
    const probe = () =>
      fetch('/api/health')
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => {
          if (alive) setInteractive(!!(j && j.ok && j.mode === 'local'))
        })
        .catch(() => {
          if (alive) setInteractive(false)
        })
    probe()
    window.addEventListener('focus', probe)
    return () => {
      alive = false
      window.removeEventListener('focus', probe)
    }
  }, [])

  // Keep <html lang> in sync with the UI language so screen readers pick the
  // right voice and the browser applies the right typography/line-breaking.
  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((l: Lang) => {
    write('jema-lang', l)
    setLangS(l)
  }, [])
  const setTheme = useCallback((t: Theme) => {
    write('jema-theme', t)
    setThemeS(t)
  }, [])
  const toggleTheme = useCallback(() => {
    setThemeS((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark'
      write('jema-theme', next)
      return next
    })
  }, [])
  const toast = useCallback((msg: string) => {
    if (tRef.current) window.clearTimeout(tRef.current)
    setToastMsg(msg)
    tRef.current = window.setTimeout(() => setToastMsg(null), 3800)
  }, [])
  const pick = useCallback((en: string, ja: string) => (lang === 'ja' ? ja : en), [lang])

  const openOverlay = useCallback((o: Overlay) => setOverlay(o), [])
  const closeOverlay = useCallback(() => setOverlay(null), [])
  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      write('jema-collapse', next ? '1' : '0')
      return next
    })
  }, [])

  const isWatched = useCallback((id: string) => watch.some((w) => w.id === id), [watch])
  const toggleWatch = useCallback((e: WatchEntry) => {
    setWatch((prev) => {
      const next = prev.some((w) => w.id === e.id)
        ? prev.filter((w) => w.id !== e.id)
        : [...prev, e]
      write('jema-watch', JSON.stringify(next))
      return next
    })
  }, [])
  const clearWatch = useCallback(() => {
    write('jema-watch', '[]')
    setWatch([])
  }, [])

  const isFollowing = useCallback((key: string) => followed.includes(key), [followed])
  const toggleFollow = useCallback((key: string) => {
    setFollowed((prev) => {
      const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
      write('jema-follow-committees', JSON.stringify(next))
      return next
    })
  }, [])

  const setArchived = useCallback((key: string, archived: boolean) => {
    setArchiveOverrides((prev) => {
      const next = { ...prev, [key]: archived }
      write('jema-archive-committees', JSON.stringify(next))
      return next
    })
  }, [])

  const setHomeScreen = useCallback((s: Screen) => {
    write('jema-home', s)
    setHomeScreenS(s)
  }, [])
  const setDefaultGran = useCallback((l: Level) => {
    write('jema-gran', l)
    setDefaultGranS(l)
  }, [])

  const requestArea = useCallback((a: AreaKey) => setFocusArea(a), [])
  const clearFocusArea = useCallback(() => setFocusArea(null), [])
  const requestCommittee = useCallback(
    (com: string, num?: number | null) => setFocusCommittee({ com, num: num ?? null }),
    [],
  )
  const clearFocusCommittee = useCallback(() => setFocusCommittee(null), [])
  const [refreshing, setRefreshing] = useState(false)
  const refreshTimer = useRef<number | null>(null)
  const jobPollRef = useRef<number | null>(null)
  const jobIdRef = useRef(0)
  const [jobRuns, setJobRuns] = useState<JobRun[]>([])
  const [panelMin, setPanelMinS] = useState<boolean>(read('jema-panel-min') === '1')

  const setPanelMinimized = useCallback((min: boolean) => {
    write('jema-panel-min', min ? '1' : '0')
    setPanelMinS(min)
  }, [])
  const dismissRun = useCallback((id: number) => {
    setJobRuns((prev) => prev.filter((r) => r.id !== id))
  }, [])
  const clearRuns = useCallback(() => {
    // Keep any still-running job; drop finished history.
    setJobRuns((prev) => prev.filter((r) => r.state === 'running'))
  }, [])

  // Mirror a just-started backend job (catch-up / full refresh) into `jobRuns` so
  // the progress panel can show live per-stage progress and a run history. Polls
  // the shared single-flight job slot, refetches page snapshots as each stage
  // completes (new meetings land mid-run), and once more on completion.
  const trackJob = useCallback((meta: JobTrackMeta) => {
    const endpoint = meta.endpoint || '/api/policy/job'
    const id = (jobIdRef.current += 1)
    const run0: JobRun = {
      id, kind: meta.kind, title: meta.title, titleJa: meta.titleJa,
      state: 'running', stages: [], output: [], result: null, error: null,
      startedAt: Date.now(), finishedAt: null,
    }
    setJobRuns((prev) => [run0, ...prev].slice(0, 8))
    setPanelMinS(false) // pop the panel open on a new job
    let doneStages = 0
    let errs = 0
    const poll = () => {
      fetch(endpoint)
        .then((r) => r.json())
        .then((j: RawJob) => {
          errs = 0
          const stages = (j.stages || []) as JobStage[]
          const state: JobRun['state'] =
            j.state === 'running' ? 'running' : j.state === 'error' ? 'error' : 'done'
          let snap: JobRun | null = null
          setJobRuns((prev) =>
            prev.map((x) => {
              if (x.id !== id) return x
              snap = {
                ...x, stages, output: j.output || [], state,
                result: (j.result as PolicyCatchupResult) ?? null,
                error: j.error ?? null,
                finishedAt: state === 'running' ? null : Date.now(),
              }
              return snap
            }),
          )
          const nowDone = stages.filter((sg) => sg.state !== 'running').length
          if (nowDone > doneStages) {
            doneStages = nowDone
            refreshSnapshots() // new meetings land as each stage completes
          }
          if (j.state === 'running') {
            jobPollRef.current = window.setTimeout(poll, 1000)
          } else {
            refreshSnapshots()
            if (snap) meta.onDone?.(snap)
          }
        })
        .catch(() => {
          if ((errs += 1) > 5) {
            setJobRuns((prev) =>
              prev.map((x) =>
                x.id === id
                  ? { ...x, state: 'error', error: 'lost connection to the local API', finishedAt: Date.now() }
                  : x,
              ),
            )
            return
          }
          jobPollRef.current = window.setTimeout(poll, 1500)
        })
    }
    if (jobPollRef.current) window.clearTimeout(jobPollRef.current)
    jobPollRef.current = window.setTimeout(poll, 700)
  }, [])

  const refreshData = useCallback(() => {
    // Static (GitHub Pages / no backend): there's nothing to re-scrape, so just
    // bust the snapshot cache and refetch. A short spinner signals the reload.
    if (!interactive) {
      refreshSnapshots()
      setRefreshing(true)
      if (refreshTimer.current != null) clearTimeout(refreshTimer.current)
      refreshTimer.current = window.setTimeout(() => setRefreshing(false), 800)
      return
    }
    // Interactive (local `repower web-api`): kick off a real full refresh (recover
    // gaps → scrape every source → export-web) and mirror it into the progress
    // panel via trackJob (which refetches snapshots as it runs). Keep the spinner
    // up until the job finishes.
    setRefreshing(true)
    fetch('/api/data/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
      .then(async (r) => {
        const j = (await r.json().catch(() => null)) as { error?: string } | null
        if (r.status === 202 || r.status === 409) {
          toast(
            r.status === 409
              ? pick('A job is already running — waiting…', '実行中のジョブがあります — 完了を待っています…')
              : pick('Refreshing data — scraping sources…', 'データ取得中 — 各ソースを収集しています…'),
          )
          trackJob({
            kind: 'refresh-web',
            title: 'Data refresh',
            titleJa: 'データ更新',
            endpoint: '/api/data/refresh',
            onDone: (run) => {
              setRefreshing(false)
              toast(
                run.state === 'error'
                  ? pick('Refresh failed — see the web-api console', '更新に失敗しました — web-api のログを確認してください')
                  : pick('Data refreshed', 'データを更新しました'),
              )
            },
          })
        } else {
          setRefreshing(false)
          toast(j && j.error ? j.error : pick('Could not start refresh', '更新を開始できませんでした'))
        }
      })
      .catch(() => {
        setRefreshing(false)
        toast(pick('Could not reach the local API', 'ローカル API に接続できませんでした'))
      })
  }, [interactive, toast, pick, trackJob])

  // Global keyboard: ⌘K / Ctrl-K opens search, Esc closes any overlay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setOverlay((o) => (o === 'search' ? null : 'search'))
      } else if (e.key === 'Escape') {
        setOverlay(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const value = useMemo<AppState>(
    () => ({
      lang,
      setLang,
      theme,
      setTheme,
      toggleTheme,
      screen,
      setScreen,
      toast,
      toastMsg,
      pick,
      overlay,
      openOverlay,
      closeOverlay,
      collapsed,
      toggleCollapsed,
      watch,
      isWatched,
      toggleWatch,
      clearWatch,
      followed,
      isFollowing,
      toggleFollow,
      archiveOverrides,
      setArchived,
      homeScreen,
      setHomeScreen,
      defaultGran,
      setDefaultGran,
      focusArea,
      requestArea,
      clearFocusArea,
      focusCommittee,
      requestCommittee,
      clearFocusCommittee,
      interactive,
      refreshData,
      refreshing,
      jobRuns,
      trackJob,
      panelMin,
      setPanelMinimized,
      dismissRun,
      clearRuns,
    }),
    [
      lang,
      setLang,
      theme,
      setTheme,
      toggleTheme,
      screen,
      toast,
      toastMsg,
      pick,
      overlay,
      openOverlay,
      closeOverlay,
      collapsed,
      toggleCollapsed,
      watch,
      isWatched,
      toggleWatch,
      clearWatch,
      followed,
      isFollowing,
      toggleFollow,
      archiveOverrides,
      setArchived,
      homeScreen,
      setHomeScreen,
      defaultGran,
      setDefaultGran,
      focusArea,
      requestArea,
      clearFocusArea,
      focusCommittee,
      requestCommittee,
      clearFocusCommittee,
      interactive,
      refreshData,
      refreshing,
      jobRuns,
      trackJob,
      panelMin,
      setPanelMinimized,
      dismissRun,
      clearRuns,
    ],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useApp must be used within <AppProvider>')
  return c
}
