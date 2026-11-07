import type { ReactNode } from 'react'
import { NavLink } from 'react-router'
import { cx } from './cx'

export function PageHeader({ title, subtitle, actions, eyebrow }: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  eyebrow?: ReactNode
}) {
  return (
    <header className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[13px] text-fg-muted">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight text-balance">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-fg-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Panel({ children, className, as: As = 'section', ...rest }: {
  children: ReactNode
  className?: string
  as?: 'section' | 'div' | 'article'
  'aria-labelledby'?: string
}) {
  return (
    <As className={cx('rounded-lg border border-line bg-surface', className)} {...rest}>
      {children}
    </As>
  )
}

export function PanelHeader({ title, actions, id, description }: {
  title: ReactNode
  actions?: ReactNode
  id?: string
  description?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <h2 id={id} className="text-[15px] font-semibold">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Route-backed tabs (each tab is a real URL, so deep links and back/forward work). */
export function LinkTabs({ items, label }: { items: { to: string; label: string; end?: boolean; count?: number }[]; label: string }) {
  return (
    <nav aria-label={label} className="-mx-4 mb-5 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
      <ul className="flex min-w-max gap-1">
        {items.map((it) => (
          <li key={it.to}>
            <NavLink
              to={it.to}
              end={it.end}
              className={({ isActive }) =>
                cx(
                  '-mb-px inline-flex h-10 items-center gap-1.5 border-b-2 px-2.5 text-sm transition-colors',
                  isActive ? 'border-accent font-medium text-fg' : 'border-transparent text-fg-muted hover:text-fg',
                )
              }
            >
              {it.label}
              {it.count ? (
                <span className="rounded-sm bg-warning-soft px-1.5 text-xs font-medium text-warning tabular">{it.count}</span>
              ) : null}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** In-page segmented control (used for mobile stacked panes). */
export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="grid auto-cols-fr grid-flow-col gap-1 rounded-md bg-surface-muted p-1">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          type="button"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            'h-8 rounded-sm px-2 text-[13px] font-medium transition-colors',
            value === o.value ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 px-4 py-3.5">
      <dt className="text-[13px] text-fg-muted">{label}</dt>
      <dd className="mt-1 truncate text-xl font-semibold tabular">{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-fg-subtle">{hint}</dd>}
    </div>
  )
}

export function KeyValue({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-2 text-sm">
      {items.map((it) => (
        <div key={it.label} className="contents">
          <dt className="text-fg-muted">{it.label}</dt>
          <dd className="min-w-0 break-words">{it.value}</dd>
        </div>
      ))}
    </dl>
  )
}
