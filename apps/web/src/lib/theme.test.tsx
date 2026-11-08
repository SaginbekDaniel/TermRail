import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { media } from '../test/setup'
import { readThemePref, resolveTheme, ThemeProvider, useTheme } from './theme'

function Probe() {
  const { pref, resolved, setPref, toggle } = useTheme()
  return (
    <div>
      <output data-testid="state">{pref}/{resolved}</output>
      <button onClick={toggle}>toggle</button>
      <button onClick={() => setPref('system')}>system</button>
    </div>
  )
}
const renderProbe = () => render(<ThemeProvider><Probe /></ThemeProvider>)

describe('theme', () => {
  it('resolves system preference', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })

  it('follows the OS when nothing is stored and paints data-theme', () => {
    media.dark = true
    renderProbe()
    expect(screen.getByTestId('state')).toHaveTextContent('system/dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('persists an explicit choice and survives a remount (page refresh)', async () => {
    const user = userEvent.setup()
    const first = renderProbe()
    await user.click(screen.getByText('toggle'))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('termrail.theme')).toBe('dark')
    first.unmount()
    delete document.documentElement.dataset.theme

    renderProbe()
    expect(screen.getByTestId('state')).toHaveTextContent('dark/dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('"system" clears the stored value', async () => {
    const user = userEvent.setup()
    renderProbe()
    await user.click(screen.getByText('toggle'))
    await user.click(screen.getByText('system'))
    expect(localStorage.getItem('termrail.theme')).toBeNull()
  })

  it('migrates the legacy storage key without logging the choice away', () => {
    localStorage.setItem('scopelock.theme', 'dark')
    expect(readThemePref()).toBe('dark')
  })

  it('keeps browser chrome colour in sync with the page', () => {
    document.head.insertAdjacentHTML('beforeend', '<meta name="theme-color" content="#000" media="(prefers-color-scheme: dark)">')
    document.documentElement.style.setProperty('--sl-canvas', '#09090b')
    act(() => void renderProbe())
    const meta = document.querySelector('meta[name="theme-color"]')!
    expect(meta.getAttribute('content')).toBe('#09090b')
    expect(meta.hasAttribute('media')).toBe(false)
    meta.remove()
  })
})
