import type { en } from './en'

type Widen<T> = T extends string ? string : { [K in keyof T]: Widen<T[K]> }

/** Every locale must provide exactly the keys of the English source dictionary. */
export type Messages = Widen<typeof en>

type Join<K, P> = K extends string ? (P extends string ? `${K}.${P}` : never) : never

/** Dotted paths to string leaves, e.g. "projects.form.title". */
export type MessageKey<T = Messages> = {
  [K in keyof T & string]: T[K] extends string ? K : Join<K, MessageKey<T[K]>>
}[keyof T & string]

export type Locale = 'en' | 'ru'
export const LOCALES: Locale[] = ['en', 'ru']

/** Language names are shown in their own language (endonyms), so they are not translated. */
export const LANGUAGE_NAMES: Record<Locale, string> = { en: 'English', ru: 'Русский' }
