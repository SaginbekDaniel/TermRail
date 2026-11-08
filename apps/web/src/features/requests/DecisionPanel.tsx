import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, MessageCircleQuestion, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { CATEGORY_ORDER, CategoryBadge, Money, ReviewStatusDot } from '../../components/domain'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Alert, ErrorState, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input, Select, Textarea } from '../../components/ui/Field'
import { useToast } from '../../components/ui/Toast'
import { api } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useEstimates, useRates } from '../../lib/queries'
import type { Category, ClientRequest, Estimate, EstimateLineInput, Finding, ProjectSummary, RequestItem } from '../../lib/types'

function ReviewControls({ request, finding }: { request: ClientRequest; finding: Finding }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const errorMessage = useErrorMessage()
  const [mode, setMode] = useState<'none' | 'override' | 'clarify'>('none')
  const [category, setCategory] = useState<Category>(finding.category)
  const [reason, setReason] = useState('')
  const invalid = finding.validation_errors.some((v) => v.startsWith('UNKNOWN_EVIDENCE_REF'))

  const review = useMutation({
    mutationFn: (body: { decision: string; category?: Category; reason?: string }) =>
      api.post(`/requests/${request.id}/findings/${finding.id}/review`, body),
    onSuccess: () => {
      setMode('none')
      setReason('')
      qc.invalidateQueries({ queryKey: qk.request(request.id) })
      qc.invalidateQueries({ queryKey: ['inbox'] })
      qc.invalidateQueries({ queryKey: qk.project(request.project_id) })
    },
  })

  return (
    <div className="space-y-3">
      {review.isError && <Alert tone="danger" title={errorMessage(review.error)} />}
      {invalid && <Alert tone="warning">{t('review.cannotAcceptInvalid')}</Alert>}
      {mode === 'none' && (
        <div className="flex flex-col gap-2">
          {!invalid && (
            <Button variant="primary" icon={<Check size={15} aria-hidden />} loading={review.isPending}
              onClick={() => review.mutate({ decision: 'ACCEPT' })}>
              {t('review.acceptAs', { category: t(`categories.${finding.category}`) })}
            </Button>
          )}
          <Button onClick={() => setMode('override')}>{t('review.override')}</Button>
          <Button variant="ghost" icon={<MessageCircleQuestion size={15} aria-hidden />} onClick={() => setMode('clarify')}>{t('review.clarify')}</Button>
        </div>
      )}
      {mode === 'override' && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            review.mutate({ decision: 'OVERRIDE', category, reason })
          }}
        >
          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-[13px] font-medium">{t('scope.form.type')}</legend>
            {CATEGORY_ORDER.map((c) => (
              <label key={c} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-surface-muted">
                <input type="radio" name="category" value={c} checked={category === c} onChange={() => setCategory(c)} className="mt-1 accent-(--tr-accent)" />
                <span><span className="block text-[13px] font-medium">{t(`categories.${c}`)}</span><span className="text-xs text-fg-muted">{t(`categoryHints.${c}`)}</span></span>
              </label>
            ))}
          </fieldset>
          <Field label={t('review.overrideReason')}>
            {(p) => <Textarea {...p} rows={3} required minLength={5} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" loading={review.isPending} disabled={reason.trim().length < 5}>{t('review.overrideSubmit')}</Button>
            <Button onClick={() => setMode('none')}>{t('common.cancel')}</Button>
          </div>
        </form>
      )}
      {mode === 'clarify' && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            review.mutate({ decision: 'REQUEST_CLARIFICATION', reason })
          }}
        >
          <Field label={t('review.clarifyReason')}>
            {(p) => <Textarea {...p} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" loading={review.isPending}>{t('review.clarify')}</Button>
            <Button onClick={() => setMode('none')}>{t('common.cancel')}</Button>
          </div>
        </form>
      )}
    </div>
  )
}

function EstimateCard({ estimate, manage, requestId }: { estimate: Estimate; manage: boolean; requestId: string }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const errorMessage = useErrorMessage()
  const notify = useToast()
  const approve = useMutation({
    mutationFn: () => api.post(`/estimates/${estimate.id}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.estimates(requestId) })
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: (e) => notify(errorMessage(e), 'danger'),
  })
  return (
    <div className="rounded-md border border-line">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <span className="text-[13px] font-medium">{t('estimates.versionLabel', { n: estimate.version })}</span>
        <Badge tone={estimate.status === 'APPROVED' ? 'success' : 'neutral'}>{estimate.status === 'APPROVED' ? t('estimates.approved') : t('estimates.draft')}</Badge>
      </div>
      <table className="w-full text-[13px]">
        <tbody className="divide-y divide-line">
          {estimate.lines.map((ln) => (
            <tr key={ln.ordinal}>
              <td className="px-3 py-1.5">
                <span className="block">{ln.description || (ln.kind === 'HOURLY' ? ln.role : t('estimates.fixed'))}</span>
                {ln.kind === 'HOURLY' && (
                  <span className="text-xs text-fg-subtle tabular">
                    {ln.role} · {ln.hours} × <Money amount={ln.rate_snapshot} currency={estimate.currency} />
                  </span>
                )}
              </td>
              <td className="px-3 py-1.5 text-right align-top"><Money amount={ln.amount} currency={estimate.currency} /></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-line font-semibold">
            <td className="px-3 py-2">{t('estimates.subtotal')}</td>
            <td className="px-3 py-2 text-right"><Money amount={estimate.subtotal} currency={estimate.currency} /></td>
          </tr>
        </tfoot>
      </table>
      {(estimate.timeline_days !== null || (manage && estimate.status === 'DRAFT')) && (
        <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2">
          <span className="text-xs text-fg-muted">{estimate.timeline_days !== null && t('changeOrders.timeline', { n: estimate.timeline_days })}</span>
          {manage && estimate.status === 'DRAFT' && (
            <Button size="sm" variant="primary" loading={approve.isPending} onClick={() => approve.mutate()}>{t('estimates.approve')}</Button>
          )}
        </div>
      )}
    </div>
  )
}

const emptyLine = (role = ''): EstimateLineInput => ({ kind: 'HOURLY', description: '', role, hours: '', amount: '' })

function EstimateForm({ request, item, project, onDone }: { request: ClientRequest; item: RequestItem; project: ProjectSummary; onDone: () => void }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const rates = useRates(project.id)
  const firstRole = rates.data?.rates[0]?.role ?? ''
  const [lines, setLines] = useState<EstimateLineInput[]>([emptyLine(firstRole)])
  const [timeline, setTimeline] = useState('')
  const [notes, setNotes] = useState('')

  const create = useMutation({
    mutationFn: () =>
      api.post<Estimate>(`/requests/${request.id}/estimates`, {
        request_item_id: item.id,
        timeline_days: timeline.trim() ? Number(timeline) : null,
        notes,
        lines: lines.map((ln) =>
          ln.kind === 'HOURLY'
            ? { kind: 'HOURLY', description: ln.description, role: ln.role || firstRole, hours: (ln.hours ?? '').replace(',', '.') || null }
            : { kind: 'FIXED', description: ln.description, amount: (ln.amount ?? '').replace(/\s/g, '').replace(',', '.') || null },
        ),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.estimates(request.id) })
      onDone()
    },
  })

  if (rates.data && rates.data.rates.length === 0) {
    return (
      <Alert tone="warning" title={t('estimates.noRates')}
        action={<Link to={`/projects/${project.id}/rates`} className="text-[13px] font-medium text-accent-fg hover:underline">{t('estimates.setRates')}</Link>} />
    )
  }
  const setLine = (i: number, patch: Partial<EstimateLineInput>) => setLines(lines.map((ln, j) => (j === i ? { ...ln, ...patch } : ln)))

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        create.mutate()
      }}
    >
      {create.isError && <ErrorState error={create.error} />}
      {lines.map((ln, i) => (
        <fieldset key={i} className="space-y-2 rounded-md border border-line p-2.5">
          <legend className="sr-only">{`${t('changeOrders.lines')} ${i + 1}`}</legend>
          <div className="flex items-center gap-2">
            <Select aria-label={t('estimates.title')} value={ln.kind} onChange={(e) => setLine(i, { kind: e.target.value as 'HOURLY' | 'FIXED' })} className="w-32">
              <option value="HOURLY">{t('estimates.hourly')}</option>
              <option value="FIXED">{t('estimates.fixed')}</option>
            </Select>
            <Input aria-label={t('estimates.description')} placeholder={t('estimates.description')} value={ln.description} onChange={(e) => setLine(i, { description: e.target.value })} />
            {lines.length > 1 && (
              <Button size="sm" variant="ghost" icon={<Trash2 size={14} aria-hidden />} aria-label={t('common.remove')} onClick={() => setLines(lines.filter((_, j) => j !== i))} />
            )}
          </div>
          {ln.kind === 'HOURLY' ? (
            <div className="grid grid-cols-[1fr_6rem] gap-2">
              <Select aria-label={t('estimates.role')} value={ln.role || firstRole} onChange={(e) => setLine(i, { role: e.target.value })}>
                {rates.data?.rates.map((r) => <option key={r.id} value={r.role}>{r.role}</option>)}
              </Select>
              <Input aria-label={t('estimates.hours')} placeholder={t('estimates.hours')} inputMode="decimal" value={ln.hours ?? ''} onChange={(e) => setLine(i, { hours: e.target.value })} />
            </div>
          ) : (
            <Input aria-label={`${t('estimates.amount')} (${project.currency})`} placeholder={`${t('estimates.amount')} (${project.currency})`} inputMode="decimal" value={ln.amount ?? ''} onChange={(e) => setLine(i, { amount: e.target.value })} />
          )}
        </fieldset>
      ))}
      <Button size="sm" variant="ghost" icon={<Plus size={14} aria-hidden />} onClick={() => setLines([...lines, emptyLine(firstRole)])}>{t('estimates.addLine')}</Button>
      <Field label={t('estimates.timeline')} optional>
        {(p) => <Input {...p} inputMode="numeric" value={timeline} onChange={(e) => setTimeline(e.target.value.replace(/\D/g, ''))} />}
      </Field>
      <Field label={t('estimates.notes')} optional>
        {(p) => <Textarea {...p} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />}
      </Field>
      <p className="text-xs text-fg-subtle">{t('estimates.serverCalculated')}</p>
      <Button type="submit" variant="primary" className="w-full" loading={create.isPending}>{t('estimates.create')}</Button>
    </form>
  )
}

export function DecisionPanel({ request, item, finding, project, manage }: {
  request: ClientRequest
  item: RequestItem
  finding: Finding
  project: ProjectSummary
  manage: boolean
}) {
  const { t, td } = useI18n()
  const estimates = useEstimates(request.id)
  const [formOpen, setFormOpen] = useState(false)
  const effective = finding.final_category
  const itemEstimates = (estimates.data ?? []).filter((e) => e.request_item_id === item.id).sort((a, b) => b.version - a.version)

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <ReviewStatusDot status={finding.review_status} />
        {effective && <div><CategoryBadge category={effective} /></div>}
        {finding.reviews.map((r, i) => (
          <p key={i} className="text-[13px] text-fg-muted">
            {t('review.decided', { decision: td(`review.decisions.${r.decision}`, r.decision), name: r.actor_name })}
            {r.reason && <span className="block text-fg">“{r.reason}”</span>}
          </p>
        ))}
      </div>

      {finding.review_status === 'PENDING' && (manage ? <ReviewControls request={request} finding={finding} /> : <Alert>{t('review.readOnly')}</Alert>)}

      <section className="space-y-3 border-t border-line pt-4">
        <h3 className="text-xs font-semibold tracking-wide text-fg-subtle uppercase">{t('review.estimateTitle')}</h3>
        {finding.review_status === 'PENDING' ? (
          <p className="text-[13px] text-fg-muted">{t('review.reviewFirst')}</p>
        ) : effective === 'CHANGE_CANDIDATE' ? (
          <>
            {itemEstimates.map((e) => <EstimateCard key={e.id} estimate={e} manage={manage} requestId={request.id} />)}
            {manage && (formOpen || itemEstimates.length === 0 ? (
              <EstimateForm request={request} item={item} project={project} onDone={() => setFormOpen(false)} />
            ) : (
              <Button size="sm" icon={<Plus size={14} aria-hidden />} onClick={() => setFormOpen(true)}>{t('estimates.newVersion')}</Button>
            ))}
          </>
        ) : (
          <p className="text-[13px] text-fg-muted">
            {effective === 'IN_SCOPE' || effective === 'BUG_FIX'
              ? t('review.estimateNoCharge')
              : effective === 'AMBIGUOUS'
                ? t('review.estimateAmbiguous')
                : t('review.estimateOnlyChanges')}
          </p>
        )}
      </section>
    </div>
  )
}
