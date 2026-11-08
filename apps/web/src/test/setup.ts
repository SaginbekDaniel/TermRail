import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom has no matchMedia; tests drive "prefers-color-scheme" through this stub.
export const media = { dark: false }
vi.stubGlobal('matchMedia', (query: string) => ({
  matches: query.includes('dark') ? media.dark : false,
  media: query,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
  onchange: null,
}))

afterEach(() => {
  cleanup()
  localStorage.clear()
  media.dark = false
  delete document.documentElement.dataset.theme
  document.documentElement.lang = 'en'
})
