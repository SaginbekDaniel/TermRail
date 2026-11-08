import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { Money } from '../../components/domain'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Alert, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input, Select } from '../../components/ui/Field'
import { api, newIdempotencyKey } from '../../lib/api'
import { LANGUAGE_NAMES, LOCALES, useI18n, type Locale } from '../../lib/i18n'
import type { ChangeOrder, ClientRequest, Estimate } from '../../lib/types'

export function CreateChangeOrderDialog({ open, onClose, request, estimates }: {
  open: boolean
  onClose: () => void
  request: ClientRequest
  estimates: Estimate[]
}) {
  const { t, locale } = useI18n()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const errorMessage = useErrorMessage()
  const key = useRef(newIdempotencyKey())

  // Latest APPROVED estimate per requirement.
  const latest = useMemo(() => {
    const byItem = new Map<string, Estimate>()
    for (const e of estimates) {
      if (e.status !== 'APPROVED') continue
      const prev = byItem.get(e.request_item_id)
      if (!prev || e.version > prev.version) byItem.set(e.request_item_id, e)
    }
    return [...byItem.values()]
  }, [estimates])
  const [selected, setSelected] = useState<Set<string> | null>(null)
  const chosen = selected ?? new Set(latest.map((e) => e.id))
  const [title, setTitle] = useState('')
  const [language, setLanguage] = useState<Locale>(locale)
  const items = new Map(request.items.map((i) => [i.id, i]))

  const create = useMutation({
    mutationFn: () =>
      api.post<ChangeOrder>('/change-orders', { request_id: request.id, estimate_ids: [...chosen], title, language }, key.current),
    onSuccess: (co) => {
      key.current = newIdempotencyKey()
      qc.invalidateQueries({ queryKey: ['changeOrders'] })
      onClose()
      navigate(`/change-orders/${co.id}`)
    },
  })

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('changeOrders.createTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={create.isPending} disabled={chosen.size === 0} onClick={() => create.mutate()}>{t('changeOrders.create')}</Button>
        </>
      }
    >
      <div className="space-y-4">
        {create.isError && <Alert tone="danger" title={errorMessage(create.error)} />}
        {latest.length === 0 ? (
          <Alert tone="warning" title={t('changeOrders.noApprovedEstimates')} />
        ) : (
          <fieldset className="space-y-2">
            <legend className="mb-1 text-[13px] font-medium">{t('changeOrders.createBody')}</legend>
            {latest.map((e) => (
              <label key={e.id} className="flex cursor-pointer items-start gap-2.5 rounded-md border border-line px-3 py-2.5 hover:bg-surface-muted">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 accent-(--tr-accent)"
                  checked={chosen.has(e.id)}
                  onChange={() => {
                    const next = new Set(chosen)
                    if (next.has(e.id)) next.delete(e.id)
                    else next.add(e.id)
                    setSelected(next)
                  }}
                />
                <span className="min-w-0 flex-1 text-[13px]">
                  <span className="block">{items.get(e.request_item_id)?.exact_text}</span>
                  <span className="text-xs text-fg-subtle">{t('estimates.versionLabel', { n: e.version })}</span>
                </span>
                <Money amount={e.subtotal} currency={e.currency} className="text-[13px] font-medium" />
              </label>
            ))}
          </fieldset>
        )}
        <Field label={t('changeOrders.titleLabel')} optional>
          {(p) => <Input {...p} maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />}
        </Field>
        <Field label={t('changeOrders.language')}>
          {(p) => (
            <Select {...p} value={language} onChange={(e) => setLanguage(e.target.value as Locale)}>
              {LOCALES.map((l) => <option key={l} value={l}>{LANGUAGE_NAMES[l]}</option>)}
            </Select>
          )}
        </Field>
      </div>
    </Dialog>
  )
}
