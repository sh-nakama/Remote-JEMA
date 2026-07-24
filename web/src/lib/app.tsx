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
export type Overlay = 'search' | 'settings' | 'watchlist' | 'committees'

/** A single starred entity. `id` is the stable key (e.g. `area:tepco`). */
export interface WatchEntry {
  id: string
  kind: 'area' | 'committee'
  en: string
  ja: string
  /** Screen to open when the entry is activated. */
  screen: Screen
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

  /** User settings (persisted). */
  homeScreen: Screen
  setHomeScreen: (s: Screen) => void
  defaultGran: Level
  setDefaultGran: (l: Level) => void

  /** Transient: an area the ⌘K palette asked Market Data to focus. */
  focusArea: AreaKey | null
  requestArea: (a: AreaKey) => void
  clearFocusArea: () => void

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
  const [homeScreen, setHomeScreenS] = useState<Screen>(homeInit)
  const [defaultGran, setDefaultGranS] = useState<Level>(() => {
    const g = read('jema-gran') as Level | null
    return g && LEVELS.includes(g) ? g : 'Daily'
  })
  const [focusArea, setFocusArea] = useState<AreaKey | null>(null)
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
  const [refreshing, setRefreshing] = useState(false)
  const refreshTimer = useRef<number | null>(null)
  const jobTimer = useRef<number | null>(null)
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
    // Interactive (local `repower web-api`): kick off a real full refresh
    // (recover gaps → scrape every source → export-web), keep the spinner up for
    // the whole job, then reload the freshly-written snapshots. Polls the shared
    // single-flight job slot, so it also attaches to an already-running job (409).
    const finish = (msg: string) => {
      if (jobTimer.current) window.clearTimeout(jobTimer.current)
      jobTimer.current = null
      setRefreshing(false)
      refreshSnapshots()
      toast(msg)
    }
    const poll = () => {
      fetch('/api/data/refresh')
        .then((r) => r.json())
        .then((j: { state?: string }) => {
          if (j && j.state === 'running') {
            jobTimer.current = window.setTimeout(poll, 2000)
          } else if (j && j.state === 'error') {
            finish(pick('Refresh failed — see the web-api console', '更新に失敗しました — web-api のログを確認してください'))
          } else {
            finish(pick('Data refreshed', 'データを更新しました'))
          }
        })
        .catch(() => finish(pick('Refresh status unavailable', '更新状況を取得できませんでした')))
    }
    setRefreshing(true)
    fetch('/api/data/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
      .then(async (r) => {
        const j = (await r.json().catch(() => null)) as { error?: string } | null
        if (r.status === 202) {
          toast(pick('Refreshing data — scraping sources…', 'データ取得中 — 各ソースを収集しています…'))
          if (jobTimer.current) window.clearTimeout(jobTimer.current)
          jobTimer.current = window.setTimeout(poll, 2000)
        } else if (r.status === 409) {
          toast(pick('A job is already running — waiting…', '実行中のジョブがあります — 完了を待っています…'))
          if (jobTimer.current) window.clearTimeout(jobTimer.current)
          jobTimer.current = window.setTimeout(poll, 2000)
        } else {
          setRefreshing(false)
          toast(j && j.error ? j.error : pick('Could not start refresh', '更新を開始できませんでした'))
        }
      })
      .catch(() => {
        setRefreshing(false)
        toast(pick('Could not reach the local API', 'ローカル API に接続できませんでした'))
      })
  }, [interactive, toast, pick])

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
      homeScreen,
      setHomeScreen,
      defaultGran,
      setDefaultGran,
      focusArea,
      requestArea,
      clearFocusArea,
      interactive,
      refreshData,
      refreshing,
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
      homeScreen,
      setHomeScreen,
      defaultGran,
      setDefaultGran,
      focusArea,
      requestArea,
      clearFocusArea,
      interactive,
      refreshData,
      refreshing,
    ],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useApp must be used within <AppProvider>')
  return c
}
