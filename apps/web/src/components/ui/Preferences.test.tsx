import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Logo } from '../brand/Logo'
import { I18nProvider } from '../../lib/i18n'
import { ThemeProvider } from '../../lib/theme'
import { LanguageSwitcher, ThemeToggle } from './Preferences'

const wrap = (ui: React.ReactNode) => render(<ThemeProvider><I18nProvider initial="ru">{ui}</I18nProvider></ThemeProvider>)

describe('LanguageSwitcher', () => {
  it('switches the interface language, persists it and updates <html lang>', async () => {
    const user = userEvent.setup()
    wrap(<LanguageSwitcher />)
    expect(screen.getByRole('group', { name: 'Язык' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Русский' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Қазақша' }))
    expect(screen.getByRole('group', { name: 'Тіл' })).toBeInTheDocument() // label itself re-localised
    expect(screen.getByRole('button', { name: 'Қазақша' })).toHaveAttribute('aria-pressed', 'true')
    expect(localStorage.getItem('termrail.locale')).toBe('kk')
    expect(document.documentElement.lang).toBe('kk')
  })

  it('announces each option in its own language', () => {
    wrap(<LanguageSwitcher />)
    expect(screen.getByRole('button', { name: 'Қазақша' })).toHaveAttribute('lang', 'kk')
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('lang', 'en')
  })
})

describe('ThemeToggle', () => {
  it('has a localised, state-aware label and flips the theme', async () => {
    const user = userEvent.setup()
    wrap(<ThemeToggle />)
    await user.click(screen.getByRole('button', { name: 'Включить тёмную тему' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(screen.getByRole('button', { name: 'Включить светлую тему' })).toBeInTheDocument()
  })
})

describe('Logo', () => {
  it('is an accessible image with the supplied aspect ratio and token-driven fills', () => {
    const { container } = render(<Logo />)
    expect(screen.getByRole('img', { name: 'TermRail' })).toBeInTheDocument()
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('viewBox')).toBe('0 0 1416 170')
    expect(container.querySelectorAll('path')).toHaveLength(8)
    expect(container.querySelector('g[fill="var(--sl-brand)"]')).not.toBeNull()
    expect(container.querySelector('g[fill="var(--sl-logo-ink)"]')).not.toBeNull()
  })
})
