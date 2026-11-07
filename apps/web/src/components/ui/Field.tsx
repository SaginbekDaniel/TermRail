import { useId, type ComponentProps, type ReactNode } from 'react'
import { useI18n } from '../../lib/i18n'
import { cx } from './cx'

const control =
  'block w-full rounded-md border border-line-strong bg-surface px-3 text-fg placeholder:text-fg-subtle ' +
  'transition-colors hover:border-fg-subtle focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 ' +
  'disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-fg-muted aria-[invalid=true]:border-danger'

export function Input({ className, ...rest }: ComponentProps<'input'>) {
  return <input className={cx(control, 'h-9', className)} {...rest} />
}

export function Textarea({ className, ...rest }: ComponentProps<'textarea'>) {
  return <textarea className={cx(control, 'py-2 leading-relaxed', className)} {...rest} />
}

export function Select({ className, children, ...rest }: ComponentProps<'select'>) {
  return (
    <select className={cx(control, 'h-9 pr-8', className)} {...rest}>
      {children}
    </select>
  )
}

/**
 * Label + control + hint/error wiring. The render prop receives the ids so the control gets
 * proper `id`, `aria-describedby` and `aria-invalid` attributes.
 */
export function Field({ label, hint, error, optional, className, children }: {
  label: string
  hint?: string
  error?: string | null
  optional?: boolean
  className?: string
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => ReactNode
}) {
  const { t } = useI18n()
  const id = useId()
  const hintId = `${id}-hint`
  const errId = `${id}-err`
  const describedBy = [error ? errId : null, hint ? hintId : null].filter(Boolean).join(' ') || undefined
  return (
    <div className={cx('space-y-1.5', className)}>
      <label htmlFor={id} className="block text-[13px] font-medium text-fg">
        {label}
        {optional && <span className="ml-1 font-normal text-fg-subtle">({t('common.optional')})</span>}
      </label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {error && <p id={errId} className="text-[13px] text-danger">{error}</p>}
      {hint && !error && <p id={hintId} className="text-[13px] text-fg-subtle">{hint}</p>}
    </div>
  )
}
