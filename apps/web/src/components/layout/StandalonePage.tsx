import type { ReactNode } from 'react'
import { BrandLink } from '../brand/BrandLink'
import { LanguageSwitcher, ThemeToggle } from '../ui/Preferences'

/**
 * Frame for pages outside the app shell (sign in, register, onboarding): brand on the left,
 * language + theme on the right, content centred. Language and theme stay reachable before sign-in.
 */
export function StandalonePage({ children, width = 'sm' }: { children: ReactNode; width?: 'sm' | 'lg' }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="pt-safe">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4 sm:px-6">
          <BrandLink className="h-5" />
          <div className="flex items-center gap-1.5">
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pb-16 pt-6 sm:items-center sm:pt-0">
        <div className={width === 'lg' ? 'w-full max-w-3xl' : 'w-full max-w-sm'}>{children}</div>
      </main>
    </div>
  )
}
