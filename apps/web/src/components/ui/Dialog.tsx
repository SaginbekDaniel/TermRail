import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { useI18n } from '../../lib/i18n'
import { cx } from './cx'

/**
 * Modal built on the native <dialog> element: focus trapping, Escape handling, inert background
 * and top-layer stacking come from the browser. On small screens it becomes a bottom sheet that
 * respects the safe-area inset.
 */
export function Dialog({ open, onClose, title, description, children, footer, size = 'md' }: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children?: ReactNode
  footer?: ReactNode
  size?: 'md' | 'lg'
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const { t } = useI18n()

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose() // backdrop click
      }}
      className={cx(
        'm-0 mt-auto max-h-[92dvh] w-full max-w-none rounded-t-lg border border-line bg-surface p-0 text-fg shadow-overlay',
        'backdrop:bg-black/40 sm:m-auto sm:rounded-lg',
        size === 'lg' ? 'sm:max-w-3xl' : 'sm:max-w-lg',
      )}
    >
      {open && (
        <div className="flex max-h-[92dvh] flex-col">
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <h2 id={titleId} className="text-base font-semibold">{title}</h2>
              {description && <p className="mt-1 text-fg-muted">{description}</p>}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="-mr-1 rounded-md p-1 text-fg-muted hover:bg-surface-muted hover:text-fg"
              aria-label={t('common.close')}
            >
              <X size={18} aria-hidden />
            </button>
          </div>
          {children && <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">{children}</div>}
          {footer && (
            <div className="pb-safe flex flex-wrap justify-end gap-2 border-t border-line px-5 pt-3 sm:pb-3">{footer}</div>
          )}
        </div>
      )}
    </dialog>
  )
}
