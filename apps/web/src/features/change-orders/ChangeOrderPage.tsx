import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, Download, FileDown, Pencil, Send, Undo2, XCircle } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { CategoryBadge, ChangeOrderStatusBadge, Money } from '../../components/domain'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Alert, ErrorState, LoadingBlock, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input, Textarea } from '../../components/ui/Field'
import { KeyValue, PageHeader, Panel, PanelHeader } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api, downloadFile } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useChangeOrder } from '../../lib/queries'
import { canManage, useWorkspace } from '../../lib/session'
import type { ChangeOrder, ChangeOrderContent, ExportRecord } from '../../lib/types'

type EditForm = Pick<ChangeOrderContent, 'title' | 'summary' | 'terms' | 'acceptance_criteria' | 'exclusions'> & {
  valid_until: string
  timeline_days: string
}

function EditDialog({ co, open, onClose }: { co: ChangeOrder; open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const c = co.current.content
  const [form, setForm] = useState<EditForm>({
    title: c.title, summary: c.summary, terms: c.terms, acceptance_criteria: c.acceptance_criteria,
    exclusions: c.exclusions, valid_until: c.valid_until ?? '', timeline_days: c.timeline_days?.toString() ?? '',
  })
  const save = useMutation({
    mutationFn: () =>
      api.patch<ChangeOrder>(`/change-orders/${co.id}/draft`, {
        expected_revision_no: co.current.revision_no,
        ...form,
        valid_until: form.valid_until || null,
        timeline_days: form.timeline_days === '' ? null : Number(form.timeline_days),
      }),
    onSuccess: (data) => {
      qc.setQueryData(qk.changeOrder(co.id), data)
      qc.invalidateQueries({ queryKey: ['changeOrders'] })
      onClose()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  const wasApproved = co.status === 'APPROVED_INTERNAL' || co.status === 'EXPORTED'

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t('changeOrders.actions.edit')}
      footer={<><Button onClick={onClose}>{t('common.cancel')}</Button><Button type="submit" form="co-edit" variant="primary" loading={save.isPending}>{t('common.save')}</Button></>}
    >
      <form id="co-edit" onSubmit={submit} className="space-y-4">
        {wasApproved && <Alert tone="warning" title={t('changeOrders.approvalInvalidated')} />}
        {save.isError && <ErrorState error={save.error} />}
        <Field label={t('changeOrders.fields.title')}>
          {(p) => <Input {...p} required maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />}
        </Field>
        <Field label={t('changeOrders.fields.summary')} optional>
          {(p) => <Textarea {...p} rows={3} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('changeOrders.fields.timeline')} optional>
            {(p) => <Input {...p} inputMode="numeric" value={form.timeline_days} onChange={(e) => setForm({ ...form, timeline_days: e.target.value.replace(/\D/g, '') })} />}
          </Field>
          <Field label={t('changeOrders.fields.validUntil')} optional>
            {(p) => <Input {...p} type="date" value={form.valid_until} onChange={(e) => setForm({ ...form, valid_until: e.target.value })} />}
          </Field>
        </div>
        <Field label={t('changeOrders.fields.acceptance')} optional>
          {(p) => <Textarea {...p} rows={3} value={form.acceptance_criteria} onChange={(e) => setForm({ ...form, acceptance_criteria: e.target.value })} />}
        </Field>
        <Field label={t('changeOrders.fields.terms')} optional>
          {(p) => <Textarea {...p} rows={3} value={form.terms} onChange={(e) => setForm({ ...form, terms: e.target.value })} />}
        </Field>
        <Field label={t('changeOrders.fields.exclusions')} optional>
          {(p) => <Textarea {...p} rows={2} value={form.exclusions} onChange={(e) => setForm({ ...form, exclusions: e.target.value })} />}
        </Field>
      </form>
    </Dialog>
  )
}

function Document({ content }: { content: ChangeOrderContent }) {
  const { t, formatDate } = useI18n()
  return (
    <div className="space-y-5 p-4">
      {content.summary && <p className="leading-relaxed whitespace-pre-line">{content.summary}</p>}
      <ol className="space-y-4">
        {content.items.map((item, i) => (
          <li key={item.request_item_id} className="rounded-md border border-line">
            <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-3 py-2.5">
              <div className="min-w-0">
                <p className="font-medium">{i + 1}. {item.summary || item.requirement}</p>
                <p className="text-[13px] text-fg-muted">«{item.requirement}»</p>
              </div>
              <CategoryBadge category={item.category} />
            </div>
            <div className="space-y-3 px-3 py-2.5">
              {item.reason && <p className="text-[13px]">{item.reason}</p>}
              {item.evidence.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-fg-muted">{t('changeOrders.evidence')}</p>
                  {item.evidence.map((e) => (
                    <blockquote key={e.span_id} className="rounded-md border-l-[3px] border-accent bg-surface-muted px-3 py-2 text-[13px]">
                      “{e.quote}”
                      <span className="mt-1 block text-xs text-fg-subtle">{e.document_title} · {t('common.version', { n: e.document_version })} · {e.anchor}</span>
                    </blockquote>
                  ))}
                </div>
              )}
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left text-xs text-fg-subtle">
                    <th className="py-1 font-medium">{t('estimates.description')}</th>
                    <th className="py-1 text-right font-medium">{t('estimates.hours')}</th>
                    <th className="hidden py-1 text-right font-medium sm:table-cell">{t('estimates.rate')}</th>
                    <th className="py-1 text-right font-medium">{t('estimates.amount')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line border-t border-line">
                  {item.estimate.lines.map((ln, j) => (
                    <tr key={j}>
                      <td className="py-1.5 pr-2">{ln.description || ln.role || t('estimates.fixed')}{ln.kind === 'HOURLY' && ln.description && <span className="block text-xs text-fg-subtle">{ln.role}</span>}</td>
                      <td className="py-1.5 text-right tabular">{ln.hours ?? '—'}</td>
                      <td className="hidden py-1.5 text-right sm:table-cell">{ln.rate ? <Money amount={ln.rate} currency={content.currency} /> : '—'}</td>
                      <td className="py-1.5 text-right"><Money amount={ln.amount} currency={content.currency} /></td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-line font-medium">
                    <td className="py-1.5" colSpan={2}>{t('estimates.subtotal')}</td>
                    <td className="hidden sm:table-cell" />
                    <td className="py-1.5 text-right"><Money amount={item.estimate.subtotal} currency={content.currency} /></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </li>
        ))}
      </ol>
      <div className="flex items-center justify-between rounded-md bg-surface-muted px-4 py-3">
        <span className="font-semibold">{t('changeOrders.total')}</span>
        <Money amount={content.total} currency={content.currency} className="text-lg font-semibold" />
      </div>
      <KeyValue
        items={[
          ...(content.timeline_days !== null ? [{ label: t('changeOrders.fields.timeline'), value: t('changeOrders.timeline', { n: content.timeline_days }) }] : []),
          ...(content.valid_until ? [{ label: t('changeOrders.fields.validUntil'), value: formatDate(content.valid_until) }] : []),
          ...(content.acceptance_criteria ? [{ label: t('changeOrders.fields.acceptance'), value: <span className="whitespace-pre-line">{content.acceptance_criteria}</span> }] : []),
          ...(content.terms ? [{ label: t('changeOrders.fields.terms'), value: <span className="whitespace-pre-line">{content.terms}</span> }] : []),
          ...(content.exclusions ? [{ label: t('changeOrders.fields.exclusions'), value: <span className="whitespace-pre-line">{content.exclusions}</span> }] : []),
        ]}
      />
    </div>
  )
}

export function ChangeOrderPage() {
  const { coId = '' } = useParams()
  const { t, formatDate } = useI18n()
  const ws = useWorkspace()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const q = useChangeOrder(coId)
  const [dialog, setDialog] = useState<'edit' | 'approve' | 'cancel' | 'changes' | null>(null)
  const [comment, setComment] = useState('')

  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: Record<string, unknown> }) => api.post<ChangeOrder>(`/change-orders/${coId}/${path}`, body ?? {}),
    onSuccess: (data) => {
      qc.setQueryData(qk.changeOrder(coId), data)
      qc.invalidateQueries({ queryKey: ['changeOrders'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
      setDialog(null)
      setComment('')
    },
    onError: (e) => notify(errorMessage(e), 'danger'),
  })

  const doExport = useMutation({
    mutationFn: (draft: boolean) => api.post<ExportRecord>(`/change-orders/${coId}/export`, { draft }),
    onSuccess: async (x) => {
      await qc.invalidateQueries({ queryKey: qk.changeOrder(coId) })
      qc.invalidateQueries({ queryKey: ['changeOrders'] })
      notify(t('changeOrders.exported'))
      await downloadFile(x.download_path, 'change-order.pdf')
    },
    onError: (e) => notify(errorMessage(e), 'danger'),
  })

  if (q.isPending) return <LoadingBlock rows={6} />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const co = q.data
  const c = co.current.content
  const manage = canManage(ws.role)
  const can = (a: ChangeOrder['allowed_actions'][number]) => manage && co.allowed_actions.includes(a)
  const lastApproval = co.approvals.find((a) => a.decision === 'APPROVED')
  const approvalInvalidated = co.status === 'DRAFT' && lastApproval && lastApproval.target_id !== co.current.id

  return (
    <>
      <PageHeader
        eyebrow={<Link to={`/projects/${co.project_id}/change-orders`} className="inline-flex items-center gap-1 hover:text-fg"><ArrowLeft size={14} aria-hidden />{co.project_title}</Link>}
        title={`${t('changeOrders.number', { n: co.number })} · ${c.title}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <ChangeOrderStatusBadge status={co.status} />
            <span>{t('changeOrders.revision', { n: co.current.revision_no })}</span>
            <Link to={`/requests/${co.request_id}`} className="text-accent-fg hover:underline">{t('review.original')}</Link>
          </span>
        }
        actions={
          <>
            {can('edit') && <Button icon={<Pencil size={15} aria-hidden />} onClick={() => setDialog('edit')}>{t('changeOrders.actions.edit')}</Button>}
            {can('preview') && co.status !== 'APPROVED_INTERNAL' && co.status !== 'EXPORTED' && (
              <Button icon={<FileDown size={15} aria-hidden />} loading={doExport.isPending && doExport.variables === true} onClick={() => doExport.mutate(true)}>
                {t('changeOrders.actions.preview')}
              </Button>
            )}
            {can('submit') && <Button variant="primary" icon={<Send size={15} aria-hidden />} loading={act.isPending} onClick={() => act.mutate({ path: 'submit' })}>{t('changeOrders.actions.submit')}</Button>}
            {can('request_changes') && <Button icon={<Undo2 size={15} aria-hidden />} onClick={() => setDialog('changes')}>{t('changeOrders.actions.request_changes')}</Button>}
            {can('approve') && <Button variant="primary" icon={<CheckCircle2 size={15} aria-hidden />} onClick={() => setDialog('approve')}>{t('changeOrders.actions.approve', { n: co.current.revision_no })}</Button>}
            {can('export') && (
              <Button variant="primary" icon={<Download size={15} aria-hidden />} loading={doExport.isPending && doExport.variables === false} onClick={() => doExport.mutate(false)}>
                {t('changeOrders.actions.export')}
              </Button>
            )}
          </>
        }
      />

      <div className="space-y-4">
        {approvalInvalidated && <Alert tone="warning" title={t('changeOrders.approvalInvalidated')} />}
        <Alert tone="info">{co.status === 'APPROVED_INTERNAL' || co.status === 'EXPORTED' ? t('changeOrders.noSendNotice') : t('changeOrders.draftOnlyExport')}</Alert>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] lg:items-start">
          <Panel>
            <PanelHeader
              title={t('changeOrders.items')}
              description={`${c.project.client_name} · ${t('changeOrders.baseline', { n: c.baseline.version })}`}
            />
            <Document content={c} />
          </Panel>

          <div className="space-y-4">
            <Panel>
              <PanelHeader title={t('changeOrders.approvals')} />
              <div className="space-y-3 p-4 text-[13px]">
                <p className="break-all text-xs text-fg-subtle">{t('changeOrders.contentHash')}: <span className="font-mono">{co.current.content_hash}</span></p>
                {co.approvals.length === 0 ? (
                  <p className="text-fg-muted">{t('changeOrders.noApprovals')}</p>
                ) : (
                  <ul className="space-y-2">
                    {co.approvals.map((a) => {
                      const rev = co.revisions.find((r) => r.id === a.target_id)
                      return (
                        <li key={a.id} className="flex items-start gap-2">
                          {a.decision === 'APPROVED' ? <CheckCircle2 size={15} className="mt-0.5 text-success" aria-hidden /> : <Undo2 size={15} className="mt-0.5 text-warning" aria-hidden />}
                          <span>
                            <span className="font-medium">{a.actor_name}</span> · {t('changeOrders.revision', { n: rev?.revision_no ?? '?' })}
                            <span className="block text-xs text-fg-subtle">{formatDate(a.decided_at, true)}</span>
                            {a.comment && <span className="block">“{a.comment}”</span>}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader title={t('changeOrders.exports')} />
              <div className="p-4 text-[13px]">
                {co.exports.length === 0 ? (
                  <p className="text-fg-muted">{t('changeOrders.noExports')}</p>
                ) : (
                  <ul className="space-y-2">
                    {co.exports.map((x) => {
                      const rev = co.revisions.find((r) => r.id === x.revision_id)
                      return (
                        <li key={x.id} className="flex items-center justify-between gap-2">
                          <span className="min-w-0">
                            <Badge tone={x.is_draft ? 'neutral' : 'success'}>{x.is_draft ? t('changeOrders.draftExport') : t('changeOrders.finalExport')}</Badge>
                            <span className="ml-2 text-fg-muted">{t('changeOrders.revision', { n: rev?.revision_no ?? '?' })}</span>
                            <span className="block text-xs text-fg-subtle">{formatDate(x.created_at, true)}</span>
                          </span>
                          <Button size="sm" variant="ghost" icon={<Download size={14} aria-hidden />}
                            onClick={() => downloadFile(x.download_path, 'change-order.pdf').catch((e) => notify(errorMessage(e), 'danger'))}>
                            {t('common.download')}
                          </Button>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader title={t('changeOrders.revisions')} />
              <ul className="space-y-1.5 p-4 text-[13px]">
                {co.revisions.map((r) => (
                  <li key={r.id} className="flex justify-between gap-2">
                    <span>{t('changeOrders.revision', { n: r.revision_no })} · {r.created_by_name}</span>
                    <span className="text-xs text-fg-subtle">{formatDate(r.created_at, true)}</span>
                  </li>
                ))}
              </ul>
              {can('cancel') && (
                <div className="border-t border-line px-4 py-3">
                  <Button size="sm" variant="danger" icon={<XCircle size={14} aria-hidden />} onClick={() => setDialog('cancel')}>{t('changeOrders.actions.cancel')}</Button>
                </div>
              )}
            </Panel>
          </div>
        </div>
      </div>

      {dialog === 'edit' && <EditDialog co={co} open onClose={() => setDialog(null)} />}
      <Dialog
        open={dialog === 'approve'}
        onClose={() => setDialog(null)}
        title={t('changeOrders.approveTitle', { n: co.current.revision_no })}
        description={t('changeOrders.approveBody', { hash: co.current.content_hash.slice(0, 12) })}
        footer={
          <>
            <Button onClick={() => setDialog(null)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={act.isPending} onClick={() => act.mutate({ path: 'approve', body: { revision_id: co.current.id, content_hash: co.current.content_hash, comment } })}>
              {t('changeOrders.actions.approve', { n: co.current.revision_no })}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-md bg-surface-muted px-3 py-2.5">
            <span>{t('changeOrders.total')}</span>
            <Money amount={c.total} currency={c.currency} className="font-semibold" />
          </div>
          <Field label={t('changeOrders.comment')} optional>
            {(p) => <Textarea {...p} rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />}
          </Field>
        </div>
      </Dialog>
      <Dialog
        open={dialog === 'changes'}
        onClose={() => setDialog(null)}
        title={t('changeOrders.requestChangesTitle')}
        footer={<><Button onClick={() => setDialog(null)}>{t('common.cancel')}</Button><Button variant="primary" loading={act.isPending} onClick={() => act.mutate({ path: 'request-changes', body: { comment } })}>{t('changeOrders.actions.request_changes')}</Button></>}
      >
        <Field label={t('changeOrders.comment')} optional>
          {(p) => <Textarea {...p} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />}
        </Field>
      </Dialog>
      <Dialog
        open={dialog === 'cancel'}
        onClose={() => setDialog(null)}
        title={t('changeOrders.cancelTitle')}
        description={t('changeOrders.cancelBody')}
        footer={<><Button onClick={() => setDialog(null)}>{t('common.back')}</Button><Button variant="danger" loading={act.isPending} onClick={() => act.mutate({ path: 'cancel' })}>{t('changeOrders.actions.cancel')}</Button></>}
      />
    </>
  )
}
