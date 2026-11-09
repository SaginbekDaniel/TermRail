import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { readStored, STORAGE, writeStored } from '../storage'
import { en } from './en'
import { kk } from './kk'
import { ru } from './ru'
import { INTL_TAGS, isLocale, type Locale, type MessageKey, type Messages } from './types'

export type { Locale, MessageKey } from './types'
export { INTL_TAGS, LANGUAGE_CODES, LANGUAGE_NAMES, LOCALES } from './types'

export const DICTS: Record<Locale, Messages> = { en, ru, kk }

export type Vars = Record<string, string | number>

/**
 * Resolves a dotted path. Keys may themselves contain dots (the audit event types such as
 * "change_order.exported" are used verbatim as keys), so at every level the longest literal match wins.
 */
export function lookup(node: unknown, parts: string[]): string | undefined {
  if (parts.length === 0) return typeof node === 'string' ? node : undefined
  if (!node || typeof node !== 'object') return undefined
  for (let n = parts.length; n >= 1; n--) {
    const literal = parts.slice(0, n).join('.')
    if (Object.hasOwn(node, literal)) {
      const found = lookup((node as Record<string, unknown>)[literal], parts.slice(n))
      if (found !== undefined) return found
    }
  }
  return undefined
}

const find = (locale: Locale, key: string): string | undefined => lookup(DICTS[locale], key.split('.'))

export function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (m, name: string) => (name in vars ? String(vars[name]) : m))
}

export function translate(locale: Locale, key: MessageKey, vars?: Vars): string {
  const value = find(locale, key) ?? find('en', key) ?? key
  return interpolate(value, vars)
}

/** For keys built at runtime from server values (error codes, enum values). Falls back to `fallback`. */
export function translateDynamic(locale: Locale, key: string, fallback: string, vars?: Vars): string {
  const value = find(locale, key)
  return value === undefined ? fallback : interpolate(value, vars)
}

/** Stored choice first, then the browser's preferred languages (first supported one wins), else Russian. */
export function detectLocale(): Locale {
  const stored = readStored(STORAGE.locale)
  if (isLocale(stored)) return stored
  const prefs = typeof navigator !== 'undefined' ? (navigator.languages?.length ? navigator.languages : [navigator.language]) : []
  for (const tag of prefs) {
    const base = tag.toLowerCase().split('-')[0]
    if (isLocale(base)) return base
  }
  return 'ru'
}

interface I18n {
  locale: Locale
  setLocale: (l: Locale) => void
  t: (key: MessageKey, vars?: Vars) => string
  /** Translate a dynamic key (e.g. `errors.${code}`), returning `fallback` when the key is unknown. */
  td: (key: string, fallback: string, vars?: Vars) => string
  formatMoney: (amount: string | null | undefined, currency: string) => string
  formatDate: (iso: string | null | undefined, withTime?: boolean) => string
  formatNumber: (value: number) => string
}

const Ctx = createContext<I18n | null>(null)

/**
 * Formatting rules for a locale. Some stripped-down runtimes (embedded WebViews, minimal Chromium builds)
 * ship without Kazakh CLDR data and silently fall back to the root locale ("2026 M11 8", "₸ 480,000.00").
 * Detect that once and use language-neutral numeric dates with ru-RU number formatting instead, so the
 * Kazakh UI never shows broken or Russian month names.
 */
export function intlRules(locale: Locale): { tag: string; numericDates: boolean } {
  const tag = INTL_TAGS[locale]
  if (locale === 'en') return { tag, numericDates: false }
  try {
    const month = new Intl.DateTimeFormat(tag, { month: 'long' }).format(new Date(2026, 10, 8))
    if (!/\d/.test(month)) return { tag, numericDates: false }
  } catch {
    // fall through to the neutral formatting
  }
  return { tag: INTL_TAGS.ru, numericDates: true }
}

const intlLocale = (l: Locale) => intlRules(l).tag

export function formatMoneyFor(locale: Locale, amount: string | null | undefined, currency: string): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  try {
    const nf = new Intl.NumberFormat(intlLocale(locale), {
      style: 'currency',
      currency,
      currencyDisplay: 'narrowSymbol',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
    // Decimal strings are passed through unchanged: Intl formats them without float rounding.
    return nf.format(amount as unknown as number)
  } catch {
    return `${amount} ${currency}`
  }
}

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Locale }) {
  const [locale, setLocaleState] = useState<Locale>(() => initial ?? detectLocale())

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    writeStored(STORAGE.locale, l)
  }, [])

  const value = useMemo<I18n>(() => {
    const { tag, numericDates } = intlRules(locale)
    const dateOpts: Intl.DateTimeFormatOptions = numericDates
      ? { day: '2-digit', month: '2-digit', year: 'numeric' }
      : { dateStyle: 'medium' }
    const dateTimeOpts: Intl.DateTimeFormatOptions = numericDates
      ? { ...dateOpts, hour: '2-digit', minute: '2-digit' }
      : { dateStyle: 'medium', timeStyle: 'short' }
    const dateFmt = new Intl.DateTimeFormat(tag, dateOpts)
    const dateTimeFmt = new Intl.DateTimeFormat(tag, dateTimeOpts)
    const numFmt = new Intl.NumberFormat(tag)
    return {
      locale,
      setLocale,
      t: (key, vars) => translate(locale, key, vars),
      td: (key, fallback, vars) => translateDynamic(locale, key, fallback, vars),
      formatMoney: (amount, currency) => formatMoneyFor(locale, amount, currency),
      formatDate: (iso, withTime = false) => {
        if (!iso) return '—'
        const d = new Date(iso)
        return Number.isNaN(d.getTime()) ? '—' : (withTime ? dateTimeFmt : dateFmt).format(d)
      },
      formatNumber: (v) => numFmt.format(v),
    }
  }, [locale, setLocale])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useI18n must be used inside I18nProvider')
  return ctx
}
