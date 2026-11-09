import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { en } from './en'
import { ru } from './ru'
import type { Locale, MessageKey, Messages } from './types'

export type { Locale, MessageKey } from './types'
export { LANGUAGE_NAMES, LOCALES } from './types'

const DICTS: Record<Locale, Messages> = { en, ru }
const STORAGE_KEY = 'termrail.locale'

export type Vars = Record<string, string | number>

function lookup(dict: Messages, key: string): string | undefined {
  let node: unknown = dict
  for (const part of key.split('.')) {
    if (node && typeof node === 'object' && part in node) node = (node as Record<string, unknown>)[part]
    else return undefined
  }
  return typeof node === 'string' ? node : undefined
}

export function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (m, name: string) => (name in vars ? String(vars[name]) : m))
}

export function translate(locale: Locale, key: MessageKey, vars?: Vars): string {
  const value = lookup(DICTS[locale], key) ?? lookup(DICTS.en, key) ?? key
  return interpolate(value, vars)
}

/** For keys built at runtime from server values (error codes, enum values). Falls back to `fallback`. */
export function translateDynamic(locale: Locale, key: string, fallback: string, vars?: Vars): string {
  const value = lookup(DICTS[locale], key)
  return value === undefined ? fallback : interpolate(value, vars)
}

function detectLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'en' || stored === 'ru') return stored
  } catch {
    // storage unavailable
  }
  const nav = typeof navigator !== 'undefined' ? navigator.language.toLowerCase() : 'en'
  return nav.startsWith('ru') || nav.startsWith('kk') ? 'ru' : 'en'
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

const intlLocale = (l: Locale) => (l === 'ru' ? 'ru-RU' : 'en-US')

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
    try {
      localStorage.setItem(STORAGE_KEY, l)
    } catch {
      // ignore
    }
  }, [])

  const value = useMemo<I18n>(() => {
    const dateFmt = new Intl.DateTimeFormat(intlLocale(locale), { dateStyle: 'medium' })
    const dateTimeFmt = new Intl.DateTimeFormat(intlLocale(locale), { dateStyle: 'medium', timeStyle: 'short' })
    const numFmt = new Intl.NumberFormat(intlLocale(locale))
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
