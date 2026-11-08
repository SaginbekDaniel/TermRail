import { FileSignature, FolderKanban, Inbox, LayoutDashboard, LogOut, Menu, Settings, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { BrandLink } from '../components/brand/BrandLink'
import { LanguageSwitcher, ThemeToggle } from '../components/ui/Preferences'
import { cx } from '../components/ui/cx'
import { useI18n, type MessageKey } from '../lib/i18n'
import { useInbox } from '../lib/queries'
import { useSession, useWorkspace } from '../lib/session'

const NAV: { to: string; key: MessageKey; icon: ReactNode; end?: boolean }[] = [
  { to: '/', key: 'nav.overview', icon: <LayoutDashboard size={17} aria-hidden />, end: true },
  { to: '/projects', key: 'nav.projects', icon: <FolderKanban size={17} aria-hidden /> },
  { to: '/inbox', key: 'nav.inbox', icon: <Inbox size={17} aria-hidden /> },
  { to: '/change-orders', key: 'nav.changeOrders', icon: <FileSignature size={17} aria-hidden /> },
  { to: '/settings', key: 'nav.settings', icon: <Settings size={17} aria-hidden /> },
]

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useI18n()
  const ws = useWorkspace()
  const inbox = useInbox(ws.id)
  const pending = inbox.data?.length ?? 0
  return (
    <ul className="space-y-0.5">
      {NAV.map((item) => (
        <li key={item.to}>
          <NavLink
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cx(
                'flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors',
                isActive ? 'bg-surface-muted font-medium text-fg' : 'text-fg-muted hover:bg-surface-muted hover:text-fg',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span className={isActive ? 'text-accent-fg' : undefined}>{item.icon}</span>
                <span className="flex-1">{t(item.key)}</span>
                {item.to === '/inbox' && pending > 0 && (
                  <span className="rounded-sm bg-warning-soft px-1.5 text-xs font-medium text-warning tabular">{pending}</span>
                )}
              </>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
  )
}

function WorkspaceSwitcher() {
  const { me, workspace, selectWorkspace } = useSession()
  const { t } = useI18n()
  if (!me || !workspace) return null
  if (me.workspaces.length < 2) {
    return <p className="truncate px-2.5 text-[13px] text-fg-muted" title={workspace.name}>{workspace.name}</p>
  }
  return (
    <label className="block px-1">
      <span className="sr-only">{t('nav.workspace')}</span>
      <select
        value={workspace.id}
        onChange={(e) => selectWorkspace(e.target.value)}
        className="h-8 w-full rounded-md border border-line bg-surface px-2 text-[13px] text-fg"
      >
        {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
    </label>
  )
}

function SidebarFooter() {
  const { me, logout } = useSession()
  const { t } = useI18n()
  return (
    <div className="border-t border-line pt-3">
      <p className="truncate px-2.5 text-[13px] font-medium" title={me?.user.email}>{me?.user.display_name || me?.user.email}</p>
      <p className="truncate px-2.5 text-xs text-fg-subtle">{me?.user.email}</p>
      <div className="mt-3 flex items-center justify-between gap-2 px-1">
        <LanguageSwitcher />
        <ThemeToggle />
      </div>
      <button
        type="button"
        onClick={logout}
        className="mt-2 flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-sm text-fg-muted hover:bg-surface-muted hover:text-fg"
      >
        <LogOut size={17} aria-hidden />
        {t('nav.signOut')}
      </button>
    </div>
  )
}

export function AppShell() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const location = useLocation()

  useEffect(() => setOpen(false), [location.pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2">
        {t('nav.skipToContent')}
      </a>

      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh flex-col gap-4 border-r border-line bg-surface px-3 py-4 lg:flex">
        <div className="px-2.5 pt-0.5"><BrandLink /></div>
        <WorkspaceSwitcher />
        <nav aria-label={t('nav.primary')} className="flex-1 overflow-y-auto"><NavItems /></nav>
        <SidebarFooter />
      </aside>

      {/* Mobile top bar */}
      <header className="pt-safe sticky top-0 z-30 border-b border-line bg-surface lg:hidden">
        <div className="flex h-13 items-center justify-between px-4">
          <BrandLink className="h-4" />
          <div className="-mr-2 flex items-center gap-0.5">
            <ThemeToggle className="size-10" />
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="inline-flex size-10 items-center justify-center rounded-md text-fg-muted hover:bg-surface-muted hover:text-fg"
              aria-label={t('nav.openMenu')}
              aria-expanded={open}
              aria-controls="mobile-nav"
            >
              <Menu size={20} aria-hidden />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile drawer */}
      <div className={cx('fixed inset-0 z-40 lg:hidden', !open && 'pointer-events-none')} aria-hidden={!open}>
        <div
          className={cx('absolute inset-0 bg-scrim transition-opacity', open ? 'opacity-100' : 'opacity-0')}
          onClick={() => setOpen(false)}
        />
        <div
          id="mobile-nav"
          role="dialog"
          aria-modal="true"
          aria-label={t('nav.primary')}
          inert={!open}
          className={cx(
            'pt-safe pb-safe absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col gap-4 bg-surface px-3 py-4 shadow-overlay transition-transform',
            open ? 'translate-x-0' : '-translate-x-full',
          )}
        >
          <div className="flex items-center justify-between px-2.5">
            <BrandLink className="h-4" />
            <button type="button" onClick={() => setOpen(false)} className="rounded-md p-1.5 text-fg-muted hover:bg-surface-muted" aria-label={t('nav.closeMenu')}>
              <X size={18} aria-hidden />
            </button>
          </div>
          <WorkspaceSwitcher />
          <nav className="flex-1 overflow-y-auto"><NavItems onNavigate={() => setOpen(false)} /></nav>
          <SidebarFooter />
        </div>
      </div>

      <main id="main" className="min-w-0 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <div className="mx-auto max-w-[1280px]">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
