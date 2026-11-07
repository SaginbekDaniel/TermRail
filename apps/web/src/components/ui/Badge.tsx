import type { ReactNode } from 'react'
import { cx } from './cx'

export type BadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info' | 'violet'

const tones: Record<BadgeTone, string> = {
  neutral: 'bg-surface-muted text-fg-muted',
  accent: 'bg-accent-soft text-accent-fg',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
  info: 'bg-info-soft text-info',
  violet: 'bg-violet-soft text-violet',
}

export function Badge({ tone = 'neutral', icon, children, className, title }: {
  tone?: BadgeTone
  icon?: ReactNode
  children: ReactNode
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={cx(
        'inline-flex h-6 shrink-0 items-center gap-1 rounded-sm px-2 text-xs font-medium whitespace-nowrap',
        tones[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  )
}

/** Small status dot + label, for states that should not compete with category badges. */
export function StatusDot({ tone = 'neutral', children }: { tone?: BadgeTone; children: ReactNode }) {
  const dot: Record<BadgeTone, string> = {
    neutral: 'bg-fg-subtle',
    accent: 'bg-accent',
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
    info: 'bg-info',
    violet: 'bg-violet',
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] whitespace-nowrap text-fg-muted">
      <span className={cx('size-2 rounded-full', dot[tone])} aria-hidden />
      {children}
    </span>
  )
}
