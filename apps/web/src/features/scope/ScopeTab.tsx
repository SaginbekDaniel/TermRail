import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Lock, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { EvidenceQuote, InclusionBadge } from '../../components/domain'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Dialog } from '../../components/ui/Dialog'
import { Alert, EmptyState, ErrorState, LoadingBlock, Spinner, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Textarea } from '../../components/ui/Field'
import { Panel, PanelHeader } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api, newIdempotencyKey } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useDocuments, useScope } from '../../lib/queries'
import type { Baseline, InclusionType, ScopeItem, ScopeItemInput } from '../../lib/types'
import { useProjectContext } from '../projects/ProjectLayout'
import { ScopeItemDialog, type DraftItem } from './ScopeItemDialog'

const GROUPS: InclusionType[] = ['INCLUDED', 'EXCLUDED', 'CONDITION']

const fromServer = (i: ScopeItem): DraftItem => ({
  key: i.id,
  id: i.id,
  title: i.title,
  description: i.description,
  inclusion_type: i.inclusion_type,
  acceptance_criteria: i.acceptance_criteria,
  evidence: i.evidence,
  accepted: i.accepted,
  origin: i.origin,
})

const toInput = (i: DraftItem): ScopeItemInput => ({
  ...(i.id ? { id: i.id } : {}),
  title: i.title,
  description: i.description,
  inclusion_type: i.inclusion_type,
  acceptance_criteria: i.acceptance_criteria,
  source_span_ids: i.evidence.map((e) => e.span_id),
  accepted: i.accepted,
})

function ItemCard({ item, projectId, editable, onEdit, onAccept, onRemove }: {
  item: DraftItem
  projectId: string
  editable: boolean
  onEdit?: () => void
  onAccept?: () => void
  onRemove?: () => void
}) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const evidence = expanded ? item.evidence : item.evidence.slice(0, 1)
  return (
    <li className="px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-medium">{item.title}</h4>
            {editable && item.origin === 'AI_CANDIDATE' && (
              item.accepted
                ? <Badge tone="neutral" icon={<Check size={12} aria-hidden />}>{t('scope.reviewed')}</Badge>
                : <Badge tone="warning" icon={<Sparkles size={12} aria-hidden />}>{t('scope.aiCandidate')} · {t('scope.needsReview')}</Badge>
            )}
          </div>
          {item.description && item.description !== item.title && <p className="mt-0.5 text-[13px] text-fg-muted">{item.description}</p>}
          {item.acceptance_criteria && (
            <p className="mt-1 text-[13px]"><span className="text-fg-subtle">{t('scope.form.acceptance')}:</span> {item.acceptance_criteria}</p>
          )}
        </div>
        {editable && (
          <div className="flex items-center gap-1">
            {!item.accepted && <Button size="sm" variant="secondary" icon={<Check size={14} aria-hidden />} onClick={onAccept}>{t('scope.accept')}</Button>}
            <Button size="sm" variant="ghost" icon={<Pencil size={14} aria-hidden />} onClick={onEdit} aria-label={`${t('common.edit')}: ${item.title}`} />
            <Button size="sm" variant="ghost" icon={<Trash2 size={14} aria-hidden />} onClick={onRemove} aria-label={`${t('common.remove')}: ${item.title}`} />
          </div>
        )}
      </div>
      <div className="mt-2 space-y-2">
        {evidence.map((e) => (
          <EvidenceQuote key={e.span_id} projectId={projectId} documentVersionId={e.document_version_id} spanId={e.span_id}
            documentTitle={e.document_title} documentVersion={e.document_version} anchor={e} text={e.text} />
        ))}
        {item.evidence.length > 1 && (
          <button type="button" className="text-[13px] font-medium text-accent-fg hover:underline" onClick={() => setExpanded(!expanded)}>
            {expanded ? t('common.showLess') : `${t('common.showMore')} (${item.evidence.length - 1})`}
          </button>
        )}
      </div>
    </li>
  )
}

function GroupedItems({ items, projectId, editable, onEdit, onAccept, onRemove }: {
  items: DraftItem[]
  projectId: string
  editable: boolean
  onEdit?: (i: DraftItem) => void
  onAccept?: (i: DraftItem) => void
  onRemove?: (i: DraftItem) => void
}) {
  const { t } = useI18n()
  return (
    <div className="divide-y divide-line">
      {GROUPS.map((g) => {
        const list = items.filter((i) => i.inclusion_type === g)
        if (!list.length) return null
        return (
          <section key={g} aria-label={t(`scope.types.${g}`)}>
            <div className="flex items-center gap-2 bg-surface-muted px-4 py-2">
              <InclusionBadge type={g} />
              <span className="text-[13px] text-fg-muted">{t(`scope.typeHints.${g}`)}</span>
            </div>
            <ul className="divide-y divide-line">
              {list.map((i) => (
                <ItemCard key={i.key} item={i} projectId={projectId} editable={editable}
                  onEdit={() => onEdit?.(i)} onAccept={() => onAccept?.(i)} onRemove={() => onRemove?.(i)} />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

function ApprovedBaseline({ baseline, projectId }: { baseline: Baseline; projectId: string }) {
  const { t, formatDate } = useI18n()
  return (
    <Panel>
      <PanelHeader
        title={<span className="flex items-center gap-2"><Lock size={15} className="text-success" aria-hidden />{t('scope.current', { n: baseline.version })}</span>}
        description={t('scope.approvedBy', { name: baseline.approved_by_name ?? '—', date: formatDate(baseline.approved_at, true) })}
        actions={<span className="font-mono text-[11px] text-fg-subtle" title={baseline.baseline_hash ?? ''}>{t('scope.hash')} {baseline.baseline_hash?.slice(0, 12)}…</span>}
      />
      {baseline.approval_note && <p className="border-b border-line px-4 py-2.5 text-[13px] text-fg-muted">{baseline.approval_note}</p>}
      <GroupedItems items={baseline.items.map(fromServer)} projectId={projectId} editable={false} />
    </Panel>
  )
}

export function ScopeTab() {
  const { project: p, manage } = useProjectContext()
  const { t, td } = useI18n()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const scope = useScope(p.id)
  const docs = useDocuments(p.id)
  const draft = scope.data?.draft ?? null
  const current = scope.data?.current ?? null
  const job = scope.data?.extraction_job ?? null
  const jobActive = job?.status === 'QUEUED' || job?.status === 'RUNNING'

  // null = show the server draft as-is; an array = unsaved local edits.
  const [localItems, setLocalItems] = useState<DraftItem[] | null>(null)
  const serverItems = useMemo(() => (draft ? draft.items.map(fromServer) : []), [draft])
  const items = localItems ?? serverItems
  const dirty = localItems !== null
  const [editing, setEditing] = useState<DraftItem | null>(null)
  const [approveOpen, setApproveOpen] = useState(false)
  const [note, setNote] = useState('')
  const extractKey = useRef(newIdempotencyKey())
  const newKeyCounter = useRef(0)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: qk.scope(p.id) })
    qc.invalidateQueries({ queryKey: qk.project(p.id) })
  }

  // The scope query itself refreshes while extraction runs; when it finishes, refresh the
  // project summary too (it shows whether a draft exists).
  const prevJob = useRef(job?.status)
  useEffect(() => {
    if (prevJob.current && prevJob.current !== job?.status && job?.status === 'SUCCEEDED') {
      qc.invalidateQueries({ queryKey: qk.project(p.id) })
    }
    prevJob.current = job?.status
  }, [job?.status, qc, p.id])

  const extract = useMutation({
    mutationFn: () => api.post(`/projects/${p.id}/scope/extract`, {}, extractKey.current),
    onSuccess: () => {
      extractKey.current = newIdempotencyKey()
      invalidate()
    },
    onError: (e) => notify(errorMessage(e), 'danger'),
  })

  const createDraft = useMutation({
    mutationFn: () => api.post(`/projects/${p.id}/scope/draft`),
    onSuccess: invalidate,
    onError: (e) => notify(errorMessage(e), 'danger'),
  })

  const save = useMutation({
    mutationFn: () => api.put<Baseline>(`/projects/${p.id}/scope/draft`, { expected_revision: draft?.draft_revision, items: items.map(toInput) }),
    onSuccess: (b) => {
      qc.setQueryData(qk.scope(p.id), (old: typeof scope.data) => (old ? { ...old, draft: b } : old))
      setLocalItems(null)
      invalidate()
    },
    onError: (e) => notify(errorMessage(e), 'danger'),
  })

  const approve = useMutation({
    mutationFn: () => api.post<Baseline>(`/projects/${p.id}/scope/approve`, { expected_revision: draft?.draft_revision, note }),
    onSuccess: (b) => {
      setApproveOpen(false)
      setNote('')
      notify(t('scope.approved', { n: b.version }))
      invalidate()
      qc.invalidateQueries({ queryKey: qk.projects(p.workspace_id) })
    },
  })

  const update = (next: DraftItem[]) => setLocalItems(next)
  const unreviewed = items.filter((i) => !i.accepted).length
  const hasParsedDocs = docs.data?.some((d) => d.parse_status === 'PARSED') ?? false
  const counts = useMemo(() => Object.fromEntries(GROUPS.map((g) => [g, items.filter((i) => i.inclusion_type === g).length])), [items])

  if (scope.isPending) return <LoadingBlock rows={5} />
  if (scope.isError) return <ErrorState error={scope.error} onRetry={() => scope.refetch()} />

  const nextVersion = (scope.data.history[0]?.version ?? 0) + 1
  const extractButton = (
    <Button
      variant={draft && items.length ? 'secondary' : 'primary'}
      icon={<Sparkles size={15} aria-hidden />}
      loading={extract.isPending || jobActive}
      disabled={!hasParsedDocs || dirty}
      onClick={() => extract.mutate()}
    >
      {draft && items.length ? t('scope.extractAgain') : t('scope.extract')}
    </Button>
  )

  return (
    <div className="space-y-5">
      {jobActive && (
        <Alert tone="info" title={t('scope.extracting')}>
          <span className="inline-flex items-center gap-2"><Spinner size={13} />{t(`jobs.status.${job.status}`)}</span>
        </Alert>
      )}
      {job?.status === 'FAILED' && draft && (
        <Alert tone="danger" title={t('scope.extractFailed')}>{td(`errors.${job.last_error_code ?? ''}`, job.last_error ?? t('errors.generic'))}</Alert>
      )}

      {draft ? (
        <Panel>
          <PanelHeader
            title={t('scope.draftTitle', { n: draft.version })}
            description={t('scope.draftHint')}
            actions={manage && (
              <>
                {extractButton}
                <Button icon={<Plus size={15} aria-hidden />} onClick={() => setEditing({
                  key: `new-${++newKeyCounter.current}`, title: '', description: '', inclusion_type: 'INCLUDED',
                  acceptance_criteria: '', evidence: [], accepted: true, origin: 'MANUAL',
                })}>{t('scope.addItem')}</Button>
              </>
            )}
          />
          {!hasParsedDocs && <Alert tone="warning" className="m-4" title={t('scope.noParsedDocs')} />}
          {items.length === 0 ? (
            <div className="p-4"><EmptyState title={t('scope.emptyDraft')} /></div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-2.5 text-[13px] text-fg-muted">
                {GROUPS.map((g) => <span key={g}>{t(`scope.counts.${g}`, { n: counts[g] ?? 0 })}</span>)}
                {unreviewed > 0 && (
                  <>
                    <Badge tone="warning">{t('scope.unreviewedCount', { n: unreviewed })}</Badge>
                    {manage && <Button size="sm" onClick={() => update(items.map((i) => ({ ...i, accepted: true })))}>{t('scope.acceptAll')}</Button>}
                  </>
                )}
              </div>
              <GroupedItems
                items={items}
                projectId={p.id}
                editable={manage}
                onEdit={setEditing}
                onAccept={(it) => update(items.map((i) => (i.key === it.key ? { ...i, accepted: true } : i)))}
                onRemove={(it) => update(items.filter((i) => i.key !== it.key))}
              />
            </>
          )}
          {manage && (
            <div className="pb-safe sticky bottom-0 flex flex-wrap items-center justify-end gap-2 rounded-b-lg border-t border-line bg-surface px-4 pt-3 sm:pb-3">
              {dirty && <span className="mr-auto text-[13px] font-medium text-warning">{t('scope.unsaved')}</span>}
              {dirty && <Button variant="ghost" onClick={() => setLocalItems(null)}>{t('scope.discard')}</Button>}
              {dirty && <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{t('scope.saveDraft')}</Button>}
              {!dirty && (
                <Button
                  variant="primary"
                  icon={<Lock size={15} aria-hidden />}
                  disabled={items.length === 0 || unreviewed > 0 || jobActive}
                  onClick={() => setApproveOpen(true)}
                >
                  {t('scope.approve', { n: draft.version })}
                </Button>
              )}
            </div>
          )}
        </Panel>
      ) : current ? null : (
        <Panel className="p-5">
          <EmptyState
            icon={<Lock size={26} aria-hidden />}
            title={t('scope.noBaselineTitle')}
            body={hasParsedDocs ? t('scope.noBaselineBody') : t('scope.noParsedDocs')}
            action={manage && hasParsedDocs && extractButton}
          />
        </Panel>
      )}

      {current && (
        <>
          {!draft && manage && (
            <div className="flex justify-end">
              <Button icon={<Pencil size={15} aria-hidden />} loading={createDraft.isPending} onClick={() => createDraft.mutate()}>
                {t('scope.newVersion', { n: nextVersion })}
              </Button>
            </div>
          )}
          <ApprovedBaseline baseline={current} projectId={p.id} />
        </>
      )}

      {editing && (
        <ScopeItemDialog
          open
          projectId={p.id}
          initial={editing}
          onClose={() => setEditing(null)}
          onSave={(it) => {
            const exists = items.some((i) => i.key === it.key)
            update(exists ? items.map((i) => (i.key === it.key ? it : i)) : [...items, it])
            setEditing(null)
          }}
        />
      )}

      {draft && (
        <Dialog
          open={approveOpen}
          onClose={() => setApproveOpen(false)}
          title={t('scope.approveTitle', { n: draft.version })}
          description={t('scope.approveBody', { count: items.length })}
          footer={
            <>
              <Button onClick={() => setApproveOpen(false)}>{t('common.cancel')}</Button>
              <Button variant="primary" icon={<Lock size={15} aria-hidden />} loading={approve.isPending} onClick={() => approve.mutate()}>
                {t('scope.approve', { n: draft.version })}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            {approve.isError && <ErrorState error={approve.error} />}
            <Field label={t('scope.approveNote')} optional>
              {(fp) => <Textarea {...fp} rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />}
            </Field>
          </div>
        </Dialog>
      )}
    </div>
  )
}
