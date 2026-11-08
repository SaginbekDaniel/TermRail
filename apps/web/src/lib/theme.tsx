import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { readStored, STORAGE, writeStored } from './storage'

export type ThemePref = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_PREFS: ThemePref[] = ['system', 'light', 'dark']

const isPref = (v: unknown): v is ThemePref => v === 'system' || v === 'light' || v === 'dark'
const prefersDark = () => typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches

export function readThemePref(): ThemePref {
  const v = readStored(STORAGE.theme)
  return isPref(v) ? v : 'system'
}

export function resolveTheme(pref: ThemePref, systemDark: boolean): ResolvedTheme {
  return pref === 'dark' || (pref === 'system' && systemDark) ? 'dark' : 'light'
}

/** Paints the resolved theme on <html> and keeps the browser chrome (iOS status bar, Android toolbar) in sync. */
function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement
  root.dataset.theme = resolved
  // The canvas colour comes from the CSS tokens, so the browser UI always matches the page.
  const canvas = getComputedStyle(root).getPropertyValue('--sl-canvas').trim()
  if (!canvas) return
  for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
    meta.removeAttribute('media') // an explicit choice overrides the OS preference the static tags were written for
    meta.content = canvas
  }
}

interface ThemeApi {
  /** What the user chose (may be "system"). */
  pref: ThemePref
  /** What is actually painted. */
  resolved: ResolvedTheme
  setPref: (p: ThemePref) => void
  /** Flip between light and dark (leaves "system" for an explicit choice). */
  toggle: () => void
}

const Ctx = createContext<ThemeApi | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(readThemePref)
  const [systemDark, setSystemDark] = useState(prefersDark)
  const resolved = resolveTheme(pref, systemDark)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystemDark(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => applyTheme(resolved), [resolved])

  // Another tab changed the preference: follow it.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE.theme.key) setPrefState(readThemePref())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setPref = useCallback((p: ThemePref) => {
    setPrefState(p)
    writeStored(STORAGE.theme, p === 'system' ? null : p)
  }, [])

  const toggle = useCallback(() => setPref(resolved === 'dark' ? 'light' : 'dark'), [resolved, setPref])

  const value = useMemo(() => ({ pref, resolved, setPref, toggle }), [pref, resolved, setPref, toggle])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider')
  return ctx
}
