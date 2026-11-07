import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderKanban, Plus } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { DemoBadge } from '../../components/domain'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Alert, EmptyState, ErrorState, LoadingBlock, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input, Textarea } from '../../components/ui/Field'
import { PageHeader } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api, newIdempotencyKey } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useProjects } from '../../lib/queries'
import { canManage, useWorkspace } from '../../lib/session'
import type { Project } from '../../lib/types'

export function NewProjectDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const ws = useWorkspace()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const [form, setForm] = useState({ title: '', client: '', currency: 'KZT', budget: '', description: '' })
  // One idempotency key per opened form: double submits and retries can never create duplicates.
  const keyRef = useRef(newIdempotencyKey())

  const create = useMutation({
    mutationFn: () =>
      api.post<Project>('/projects', {
        workspace_id: ws.id,
        title: form.title.trim(),
        client_name: form.client.trim(),
        currency: form.currency.trim().toUpperCase(),
        budget: form.budget.trim() ? form.budget.trim().replace(/\s/g, '').replace(',', '.') : null,
        description: form.description.trim(),
      }, keyRef.current),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: qk.projects(ws.id) })
      qc.invalidateQueries({ queryKey: qk.overview(ws.id) })
      notify(t('projects.form.created'))
      keyRef.current = newIdempotencyKey()
      onClose()
      navigate(`/projects/${p.id}`)
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  const valid = form.title.trim() && form.client.trim() && /^[A-Za-z]{3}$/.test(form.currency.trim())

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('projects.new')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" form="new-project" variant="primary" loading={create.isPending} disabled={!valid}>
            {t('projects.form.create')}
          </Button>
        </>
      }
    >
      <form id="new-project" onSubmit={submit} className="space-y-4">
        {create.isError && <Alert tone="danger" title={errorMessage(create.error)} />}
        <Field label={t('projects.form.title')}>
          {(p) => <Input {...p} required maxLength={200} placeholder={t('projects.form.titlePlaceholder')} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />}
        </Field>
        <Field label={t('projects.form.client')}>
          {(p) => <Input {...p} required maxLength={200} value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} />}
        </Field>
        <div className="grid grid-cols-[7rem_1fr] gap-3">
          <Field label={t('projects.form.currency')}>
            {(p) => <Input {...p} required maxLength={3} className="uppercase" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })} />}
          </Field>
          <Field label={t('projects.form.budget')} optional>
            {(p) => <Input {...p} inputMode="decimal" value={form.budget} onChange={(e) => setForm({ ...form, budget: e.target.value })} />}
          </Field>
        </div>
        <p className="-mt-2 text-[13px] text-fg-subtle">{t('projects.form.currencyHint')}</p>
        <Field label={t('projects.form.description')} optional>
          {(p) => <Textarea {...p} rows={3} maxLength={5000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />}
        </Field>
      </form>
    </Dialog>
  )
}

export function ProjectsPage() {
  const { t, formatMoney } = useI18n()
  const ws = useWorkspace()
  const q = useProjects(ws.id)
  const [params, setParams] = useSearchParams()
  const [open, setOpen] = useState(params.get('new') === '1')
  const manage = canManage(ws.role)

  const close = () => {
    setOpen(false)
    if (params.has('new')) setParams({}, { replace: true })
  }

  return (
    <>
      <PageHeader
        title={t('projects.title')}
        subtitle={t('projects.subtitle')}
        actions={manage && <Button variant="primary" icon={<Plus size={16} aria-hidden />} onClick={() => setOpen(true)}>{t('projects.new')}</Button>}
      />
      {q.isPending ? (
        <LoadingBlock />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <EmptyState
          icon={<FolderKanban size={28} aria-hidden />}
          title={t('projects.emptyTitle')}
          body={t('projects.emptyBody')}
          action={manage && <Button variant="primary" onClick={() => setOpen(true)}>{t('projects.new')}</Button>}
        />
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
          {q.data.map((p) => (
            <li key={p.id}>
              <Link to={`/projects/${p.id}`} className="grid gap-2 px-4 py-3.5 transition-colors hover:bg-surface-muted md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))] md:items-center">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{p.title}</span>
                    {p.is_demo && <DemoBadge />}
                    {p.status === 'ARCHIVED' && <Badge>{t('projects.archived')}</Badge>}
                  </div>
                  <p className="truncate text-[13px] text-fg-muted">{p.client_name}{p.budget ? ` · ${formatMoney(p.budget, p.currency)}` : ''}</p>
                </div>
                <dl className="contents text-[13px]">
                  <div className="flex gap-1.5 md:block">
                    <dt className="text-fg-subtle">{t('projects.baseline')}</dt>
                    <dd>{p.baseline_version ? <Badge tone="success">{t('projects.baselineVersion', { n: p.baseline_version })}</Badge> : <span className="text-fg-muted">{t('projects.noBaseline')}</span>}</dd>
                  </div>
                  <div className="flex gap-1.5 md:block">
                    <dt className="text-fg-subtle">{t('projects.requests')}</dt>
                    <dd className="tabular">{p.requests}</dd>
                  </div>
                  <div className="flex gap-1.5 md:block">
                    <dt className="text-fg-subtle">{t('projects.openReviews')}</dt>
                    <dd>{p.open_reviews > 0 ? <Badge tone="warning">{p.open_reviews}</Badge> : <span className="tabular text-fg-muted">0</span>}</dd>
                  </div>
                </dl>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {manage && <NewProjectDialog open={open} onClose={close} />}
    </>
  )
}
