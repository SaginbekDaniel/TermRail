import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MessageSquarePlus, Plus } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { CategoryBadge, CATEGORY_ORDER, RequestStatusBadge } from '../../components/domain'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Alert, EmptyState, ErrorState, LoadingBlock, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input, Textarea } from '../../components/ui/Field'
import { ApiError, api, newIdempotencyKey } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useProjectRequests } from '../../lib/queries'
import { canContribute, useWorkspace } from '../../lib/session'
import type { ClientRequest, ProjectSummary, RequestListItem } from '../../lib/types'
import { useProjectContext } from '../projects/ProjectLayout'

export function NewRequestDialog({ project, open, onClose }: { project: ProjectSummary; open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const errorMessage = useErrorMessage()
  const [form, setForm] = useState({ message: '', sender: '', subject: '' })
  const keys = useRef({ request: newIdempotencyKey(), analyze: newIdempotencyKey() })
  const hasBaseline = project.baseline_version !== null

  const submit = useMutation({
    mutationFn: async (analyze: boolean) => {
      const req = await api.post<ClientRequest>(`/projects/${project.id}/requests`, {
        message_text: form.message, sender: form.sender, subject: form.subject,
      }, keys.current.request)
      if (analyze) await api.post(`/requests/${req.id}/analyze`, {}, keys.current.analyze)
      return req
    },
    onSuccess: (req) => {
      keys.current = { request: newIdempotencyKey(), analyze: newIdempotencyKey() }
      qc.invalidateQueries({ queryKey: qk.projectRequests(project.id) })
      qc.invalidateQueries({ queryKey: qk.project(project.id) })
      setForm({ message: '', sender: '', subject: '' })
      onClose()
      navigate(`/requests/${req.id}`)
    },
  })

  const submitForm = (e: FormEvent) => {
    e.preventDefault()
    if (form.message.trim()) submit.mutate(hasBaseline)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t('requests.newTitle')}
      description={t('requests.subtitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          {!hasBaseline || submit.error instanceof ApiError ? (
            <Button loading={submit.isPending && submit.variables === false} disabled={!form.message.trim()} onClick={() => submit.mutate(false)}>
              {t('requests.saveOnly')}
            </Button>
          ) : null}
          <Button type="submit" form="new-request" variant="primary" disabled={!form.message.trim() || !hasBaseline}
            loading={submit.isPending && submit.variables === true}>
            {t('requests.submit')}
          </Button>
        </>
      }
    >
      <form id="new-request" onSubmit={submitForm} className="space-y-4">
        {!hasBaseline && <Alert tone="warning" title={t('requests.baselineRequired')} />}
        {submit.isError && <Alert tone="danger" title={errorMessage(submit.error)} />}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('requests.sender')} optional>
            {(p) => <Input {...p} maxLength={300} value={form.sender} onChange={(e) => setForm({ ...form, sender: e.target.value })} />}
          </Field>
          <Field label={t('requests.subject')} optional>
            {(p) => <Input {...p} maxLength={300} value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />}
          </Field>
        </div>
        <Field label={t('requests.message')}>
          {(p) => (
            <Textarea {...p} required rows={9} maxLength={20000} placeholder={t('requests.messagePlaceholder')}
              value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
          )}
        </Field>
      </form>
    </Dialog>
  )
}

export function RequestList({ items, showProject = false }: { items: RequestListItem[]; showProject?: boolean }) {
  const { t, formatDate } = useI18n()
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
      {items.map((r) => (
        <li key={r.id}>
          <Link to={`/requests/${r.id}`} className="block px-4 py-3.5 transition-colors hover:bg-surface-muted">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="min-w-0 truncate font-medium">
                {r.subject || r.sender || r.excerpt.slice(0, 60)}
              </p>
              <RequestStatusBadge status={r.status} />
            </div>
            <p className="mt-0.5 line-clamp-2 text-[13px] text-fg-muted">{r.excerpt}</p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-fg-subtle">
              {showProject && <span className="mr-1">{r.project_title} ·</span>}
              <span className="mr-1">{t('requests.received', { date: formatDate(r.received_at, true) })}</span>
              {CATEGORY_ORDER.filter((c) => r.categories[c]).map((c) => (
                <span key={c} className="inline-flex items-center gap-1"><CategoryBadge category={c} />{(r.categories[c] ?? 0) > 1 && <span className="tabular">×{r.categories[c]}</span>}</span>
              ))}
              {r.pending_reviews > 0 && <Badge tone="warning">{t('requests.pending', { n: r.pending_reviews })}</Badge>}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  )
}

export function RequestsTab() {
  const { project: p } = useProjectContext()
  const { t } = useI18n()
  const ws = useWorkspace()
  const q = useProjectRequests(p.id)
  const [params, setParams] = useSearchParams()
  const [open, setOpen] = useState(params.get('new') === '1')
  const contribute = canContribute(ws.role)
  const close = () => {
    setOpen(false)
    if (params.has('new')) setParams({}, { replace: true })
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-fg-muted">{t('requests.subtitle')}</p>
        {contribute && <Button variant="primary" icon={<Plus size={16} aria-hidden />} onClick={() => setOpen(true)}>{t('requests.new')}</Button>}
      </div>
      {q.isPending ? (
        <LoadingBlock />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <EmptyState
          icon={<MessageSquarePlus size={28} aria-hidden />}
          title={t('requests.emptyTitle')}
          body={t('requests.emptyBody')}
          action={contribute && <Button variant="primary" onClick={() => setOpen(true)}>{t('requests.new')}</Button>}
        />
      ) : (
        <RequestList items={q.data} />
      )}
      {contribute && <NewRequestDialog project={p} open={open} onClose={close} />}
    </div>
  )
}
