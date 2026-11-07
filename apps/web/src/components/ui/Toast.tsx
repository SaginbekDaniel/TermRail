import { CheckCircle2, XCircle } from 'lucide-react'
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { cx } from './cx'

interface ToastItem { id: number; tone: 'success' | 'danger'; message: string }

const Ctx = createContext<{ notify: (message: string, tone?: ToastItem['tone']) => void } | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const next = useRef(1)

  const notify = useCallback((message: string, tone: ToastItem['tone'] = 'success') => {
    const id = next.current++
    setItems((xs) => [...xs.slice(-2), { id, tone, message }])
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === 'danger' ? 7000 : 4000)
  }, [])

  const value = useMemo(() => ({ notify }), [notify])

  return (
    <Ctx.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 px-4 pb-safe sm:items-end sm:px-6"
      >
        {items.map((it) => (
          <div
            key={it.id}
            role={it.tone === 'danger' ? 'alert' : 'status'}
            className={cx(
              'pointer-events-auto flex w-full max-w-sm items-start gap-2 rounded-md border border-line bg-surface px-3.5 py-2.5 shadow-overlay',
            )}
          >
            {it.tone === 'success' ? (
              <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-success" aria-hidden />
            ) : (
              <XCircle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />
            )}
            <span>{it.message}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export function useToast() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useToast must be used inside ToastProvider')
  return ctx.notify
}
