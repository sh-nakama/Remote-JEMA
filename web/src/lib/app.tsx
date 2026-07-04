import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react'

/**
 * App-wide state mirroring the exports' DCLogic: theme + lang (persisted to
 * localStorage under the same keys the exports use — jema-theme / jema-lang),
 * the active screen (the exports navigate via window.location.href to sibling
 * .html files; here that becomes a client-side screen switch), and a transient
 * toast (used by the exports' placeholder `tNav` handlers).
 */

export type Lang = 'en' | 'ja'
export type Theme = 'light' | 'dark'
export type Screen = 'overview' | 'market' | 'policy' | 'capacity'

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

export function AppProvider({
  children,
  initialScreen = 'overview',
}: {
  children: React.ReactNode
  initialScreen?: Screen
}) {
  const [lang, setLangS] = useState<Lang>((read('jema-lang') as Lang) || 'en')
  const [theme, setThemeS] = useState<Theme>((read('jema-theme') as Theme) || 'light')
  const [screen, setScreen] = useState<Screen>(initialScreen)
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const tRef = useRef<number | null>(null)

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

  const value = useMemo<AppState>(
    () => ({ lang, setLang, theme, setTheme, toggleTheme, screen, setScreen, toast, toastMsg, pick }),
    [lang, setLang, theme, setTheme, toggleTheme, screen, toast, toastMsg, pick],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useApp must be used within <AppProvider>')
  return c
}
