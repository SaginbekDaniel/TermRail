import type { en } from './en'

type Widen<T> = T extends string ? string : { [K in keyof T]: Widen<T[K]> }

/** Every locale must provide exactly the keys of the English source dictionary. */
export type Messages = Widen<typeof en>

type Join<K, P> = K extends string ? (P extends string ? `${K}.${P}` : never) : never

/** Dotted paths to string leaves, e.g. "projects.form.title". */
export type MessageKey<T = Messages> = {
  [K in keyof T & string]: T[K] extends string ? K : Join<K, MessageKey<T[K]>>
}[keyof T & string]

export type Locale = 'ru' | 'kk' | 'en'
/** Display order of the language switcher. */
export const LOCALES: Locale[] = ['ru', 'kk', 'en']

/** Language names are shown in their own language (endonyms), so they are not translated. */
export const LANGUAGE_NAMES: Record<Locale, string> = { ru: 'Русский', kk: 'Қазақша', en: 'English' }

/** Short labels for compact switchers (header, auth screens). */
export const LANGUAGE_CODES: Record<Locale, string> = { ru: 'RU', kk: 'ҚАЗ', en: 'EN' }

/** BCP 47 tags used for Intl formatting and the <html lang> attribute. */
export const INTL_TAGS: Record<Locale, string> = { ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }

export function isLocale(value: unknown): value is Locale {
  return value === 'ru' || value === 'kk' || value === 'en'
}
