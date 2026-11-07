import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Money } from '../../components/domain'
import { Button } from '../../components/ui/Button'
import { EmptyState, ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { Input } from '../../components/ui/Field'
import { Panel, PanelHeader } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useRates } from '../../lib/queries'
import type { Rates } from '../../lib/types'
import { useProjectContext } from './ProjectLayout'

interface Row { role: string; hourly_rate: string }

export function RatesTab() {
  const { project: p, manage } = useProjectContext()
  const { t } = useI18n()
  const qc = useQueryClient()
  const notify = useToast()
  const rates = useRates(p.id)
  // null = show the saved rates; an array = unsaved local edits.
  const [edits, setEdits] = useState<Row[] | null>(null)
  const saved: Row[] = rates.data?.rates.map((r) => ({ role: r.role, hourly_rate: r.hourly_rate })) ?? []
  const rows = edits ?? saved
  const setRows = (next: Row[]) => setEdits(next)

  const save = useMutation({
    mutationFn: () =>
      api.put<Rates>(`/projects/${p.id}/rates`, {
        expected_revision: rates.data?.revision ?? 0,
        rates: rows.filter((r) => r.role.trim()).map((r) => ({ role: r.role.trim(), hourly_rate: r.hourly_rate.replace(/\s/g, '').replace(',', '.') })),
      }),
    onSuccess: (data) => {
      qc.setQueryData(qk.rates(p.id), data)
      setEdits(null)
      notify(t('rates.saved', { n: data.revision }))
    },
  })

  if (rates.isPending) return <LoadingBlock />
  if (rates.isError) return <ErrorState error={rates.error} onRetry={() => rates.refetch()} />

  const current = rates.data
  const dirty = edits !== null && JSON.stringify(edits) !== JSON.stringify(saved)
  const valid = rows.every((r) => !r.role.trim() || /^\d+([.,]\d{1,2})?$/.test(r.hourly_rate.replace(/\s/g, '')))

  return (
    <Panel>
      <PanelHeader
        title={t('rates.title')}
        description={t('rates.subtitle')}
        actions={current.revision > 0 && <span className="text-[13px] text-fg-subtle">{t('rates.revision', { n: current.revision })}</span>}
      />
      {!manage ? (
        current.rates.length === 0 ? (
          <div className="p-4"><EmptyState title={t('rates.emptyTitle')} body={t('rates.emptyBody')} /></div>
        ) : (
          <ul className="divide-y divide-line">
            {current.rates.map((r) => (
              <li key={r.id} className="flex justify-between px-4 py-2.5"><span>{r.role}</span><Money amount={r.hourly_rate} currency={r.currency} /></li>
            ))}
          </ul>
        )
      ) : (
        <form
          className="space-y-3 p-4"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          {save.isError && <ErrorState error={save.error} />}
          {rows.length === 0 && <p className="text-fg-muted">{t('rates.emptyBody')}</p>}
          {rows.length > 0 && (
            <div className="grid grid-cols-[minmax(0,1fr)_9rem_2.25rem] gap-2 text-[13px] font-medium text-fg-muted">
              <span>{t('rates.role')}</span>
              <span>{t('rates.rate', { currency: p.currency })}</span>
              <span />
            </div>
          )}
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[minmax(0,1fr)_9rem_2.25rem] items-center gap-2">
              <Input aria-label={t('rates.role')} placeholder={t('rates.rolePlaceholder')} maxLength={100} value={r.role}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))} />
              <Input aria-label={t('rates.rate', { currency: p.currency })} inputMode="decimal" className="text-right tabular" value={r.hourly_rate}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, hourly_rate: e.target.value } : x)))} />
              <Button size="sm" variant="ghost" icon={<Trash2 size={14} aria-hidden />} aria-label={`${t('common.remove')}: ${r.role}`}
                onClick={() => setRows(rows.filter((_, j) => j !== i))} />
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <Button size="sm" variant="ghost" icon={<Plus size={14} aria-hidden />} onClick={() => setRows([...rows, { role: '', hourly_rate: '' }])}>
              {t('rates.addRole')}
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!dirty || !valid}>{t('rates.save')}</Button>
          </div>
        </form>
      )}
    </Panel>
  )
}
