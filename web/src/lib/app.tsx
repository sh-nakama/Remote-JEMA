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
export type Overlay = 'search' | 'settings' | 'watchlist'

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

  /** User settings (persisted). */
  homeScreen: Screen
  setHomeScreen: (s: Screen) => void
  defaultGran: Level
  setDefaultGran: (l: Level) => void

  /** Transient: an area the ⌘K palette asked Market Data to focus. */
  focusArea: AreaKey | null
  requestArea: (a: AreaKey) => void
  clearFocusArea: () => void
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
  const [homeScreen, setHomeScreenS] = useState<Screen>(homeInit)
  const [defaultGran, setDefaultGranS] = useState<Level>(() => {
    const g = read('jema-gran') as Level | null
    return g && LEVELS.includes(g) ? g : 'Daily'
  })
  const [focusArea, setFocusArea] = useState<AreaKey | null>(null)

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
      homeScreen,
      setHomeScreen,
      defaultGran,
      setDefaultGran,
      focusArea,
      requestArea,
      clearFocusArea,
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
      homeScreen,
      setHomeScreen,
      defaultGran,
      setDefaultGran,
      focusArea,
      requestArea,
      clearFocusArea,
    ],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useApp must be used within <AppProvider>')
  return c
}
