// Single place for persisted browser state. Keys were renamed with the TermRail rebrand; reads fall back
// to the legacy key so existing users stay signed in and keep their language/theme/workspace choices.

export const STORAGE = {
  token: { key: 'termrail.token', legacy: 'scopelock.token' },
  locale: { key: 'termrail.locale', legacy: 'scopelock.locale' },
  theme: { key: 'termrail.theme', legacy: 'scopelock.theme' },
  workspace: { key: 'termrail.workspace', legacy: 'scopelock.workspace' },
} as const

export type StorageEntry = (typeof STORAGE)[keyof typeof STORAGE]

export function readStored(entry: StorageEntry): string | null {
  try {
    return localStorage.getItem(entry.key) ?? localStorage.getItem(entry.legacy)
  } catch {
    return null // storage blocked (private mode, embedded webview): the preference lasts for this tab only
  }
}

export function writeStored(entry: StorageEntry, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(entry.key)
    else localStorage.setItem(entry.key, value)
    localStorage.removeItem(entry.legacy)
  } catch {
    // ignore
  }
}
