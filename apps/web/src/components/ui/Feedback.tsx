import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiError } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { Button } from './Button'
import { cx } from './cx'

export function Spinner({ size = 16, className, label }: { size?: number; className?: string; label?: string }) {
  return (
    <svg
      className={cx('animate-spin shrink-0', className)}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded-md bg-surface-muted', className)} aria-hidden />
}

/** Page/section loading placeholder that keeps the layout stable. */
export function LoadingBlock({ rows = 3 }: { rows?: number }) {
  const { t } = useI18n()
  return (
    <div role="status" aria-label={t('common.loading')} className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={i === 0 ? 'h-5 w-1/3' : 'h-14 w-full'} />
      ))}
    </div>
  )
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-line-strong px-6 py-10 text-center">
      {icon && <div className="mb-3 text-fg-subtle">{icon}</div>}
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {body && <p className="mt-1 max-w-md text-fg-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

type Tone = 'info' | 'success' | 'warning' | 'danger'

const toneStyles: Record<Tone, string> = {
  info: 'bg-info-soft text-info',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
}
const toneIcons: Record<Tone, ReactNode> = {
  info: <Info size={16} aria-hidden />,
  success: <CheckCircle2 size={16} aria-hidden />,
  warning: <AlertTriangle size={16} aria-hidden />,
  danger: <XCircle size={16} aria-hidden />,
}

export function Alert({ tone = 'info', title, children, action, className }: {
  tone?: Tone
  title?: string
  children?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cx('flex items-start gap-2.5 rounded-md px-3 py-2.5', toneStyles[tone], className)}
    >
      <span className="mt-0.5">{toneIcons[tone]}</span>
      <div className="min-w-0 flex-1 text-fg">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cx('text-fg-muted', title && 'mt-0.5')}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

/** Localized message for any thrown error (ApiError codes map to `errors.*`). */
export function useErrorMessage(): (err: unknown) => string {
  const { t, td } = useI18n()
  return (err: unknown) => {
    if (err instanceof ApiError) return td(`errors.${err.code}`, err.message || t('errors.generic'))
    return t('errors.generic')
  }
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const { t } = useI18n()
  const message = useErrorMessage()
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <Alert
      tone="danger"
      className={className}
      title={message(error)}
      action={onRetry && <Button size="sm" onClick={onRetry}>{t('common.retry')}</Button>}
    >
      {requestId && <span className="font-mono text-xs">{t('errors.requestId', { id: requestId })}</span>}
    </Alert>
  )
}
