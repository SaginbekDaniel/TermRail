import { afterEach, describe, expect, it, vi } from 'vitest'
import { DICTS, detectLocale, formatMoneyFor, interpolate, intlRules, lookup, translate, translateDynamic } from './index'
import { LOCALES, type Locale } from './types'

type Tree = { [k: string]: string | Tree }

function leaves(node: Tree, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(node)) {
    const path = prefix ? `${prefix}.${k}` : k
    if (typeof v === 'string') out[path] = v
    else Object.assign(out, leaves(v, path))
  }
  return out
}

const flat = Object.fromEntries(LOCALES.map((l) => [l, leaves(DICTS[l] as unknown as Tree)])) as Record<Locale, Record<string, string>>
const at = (l: Locale, key: string): string => flat[l][key] ?? ''
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

describe('dictionaries', () => {
  it.each(LOCALES)('%s has exactly the keys of the English source', (l) => {
    expect(Object.keys(flat[l]).sort()).toEqual(Object.keys(flat.en).sort())
  })

  it.each(LOCALES)('%s keeps every {placeholder} of the source string', (l) => {
    for (const [key, en] of Object.entries(flat.en)) expect(placeholders(at(l, key)), key).toEqual(placeholders(en))
  })

  it.each(LOCALES)('%s has no empty strings', (l) => {
    for (const [key, v] of Object.entries(flat[l])) expect(v.trim(), key).not.toBe('')
  })

  // Guards against copy-pasting Russian into the Kazakh file (the two share one alphabet, so compare whole strings).
  it('kk does not reuse Russian strings, except language-neutral ones', () => {
    const neutral = new Set(['TermRail', 'Telegram', 'Telegram Business', '—', 'SHA-256', '¶ {n}', 'v{n}', '{decision}: {name}'])
    // Loanwords that are standard Kazakh as well (клиент, валюта, менеджер, провайдер, модель, промпт).
    const loanwords = new Set(['Клиент', 'Валюта', 'Менеджер', 'Провайдер', 'Модель', 'Промпт {v}'])
    const shared = Object.keys(flat.kk).filter(
      (k) => at('kk', k) === at('ru', k) && !neutral.has(at('kk', k)) && !loanwords.has(at('kk', k)),
    )
    expect(shared).toEqual([])
  })

  it('no locale still carries the old product name', () => {
    for (const l of LOCALES) for (const [key, v] of Object.entries(flat[l])) expect(v, `${l}:${key}`).not.toMatch(/scopelock/i)
  })

  it('Kazakh strings use Kazakh-specific letters where expected', () => {
    expect(flat.kk['nav.settings']).toBe('Баптаулар')
    expect(flat.kk['settings.language']).toBe('Тіл')
    expect(Object.values(flat.kk).join('')).toMatch(/[әғқңөұүһі]/)
  })
})

describe('lookup', () => {
  it('resolves nested and literal-dotted keys', () => {
    const tree = { a: { b: 'nested' }, events: { 'change_order.exported': 'literal' } }
    expect(lookup(tree, 'a.b'.split('.'))).toBe('nested')
    expect(lookup(tree, 'events.change_order.exported'.split('.'))).toBe('literal')
    expect(lookup(tree, 'a.missing'.split('.'))).toBeUndefined()
    expect(lookup(tree, ['a'])).toBeUndefined() // not a string leaf
  })

  it.each(LOCALES)('%s translates every audit event type the API emits', (l) => {
    const events = ['workspace.created', 'change_order.exported', 'scope.baseline_approved', 'document.parse_failed']
    for (const e of events) {
      const out = translateDynamic(l, `activity.events.${e}`, '__missing__')
      expect(out, `${l}:${e}`).not.toBe('__missing__')
    }
  })

  it('does not inherit Object.prototype names', () => {
    expect(translateDynamic('ru', 'common.constructor', 'fallback')).toBe('fallback')
  })
})

describe('translate', () => {
  it('interpolates and falls back to English then to the key', () => {
    expect(translate('kk', 'rates.saved', { n: 3 })).toBe('Мөлшерлемелер сақталды (3-редакция)')
    expect(interpolate('{a} of {b}', { a: 1 })).toBe('1 of {b}')
    expect(translate('ru', 'nope.nothing' as never)).toBe('nope.nothing')
  })
})

describe('locale detection & formatting', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('defaults to Russian, honours stored choice and legacy key', () => {
    vi.stubGlobal('navigator', { ...navigator, languages: ['de-DE'], language: 'de-DE' })
    expect(detectLocale()).toBe('ru')
    vi.stubGlobal('navigator', { ...navigator, languages: ['de-DE', 'kk-KZ'], language: 'de-DE' })
    expect(detectLocale()).toBe('kk') // first supported browser language wins
    localStorage.setItem('scopelock.locale', 'kk')
    expect(detectLocale()).toBe('kk')
    localStorage.setItem('termrail.locale', 'en')
    expect(detectLocale()).toBe('en')
  })

  it('formats Kazakh money and dates with full ICU (Node)', () => {
    const rules = intlRules('kk')
    expect(rules.numericDates).toBe(false)
    const plain = (s: string) => s.replace(/\s/g, ' ') // Intl uses no-break spaces
    expect(plain(formatMoneyFor('kk', '480000.00', 'KZT'))).toBe('480 000,00 ₸')
    expect(formatMoneyFor('en', '480000.00', 'KZT')).toBe('₸480,000.00')
    expect(formatMoneyFor('ru', null, 'KZT')).toBe('—')
  })
})
