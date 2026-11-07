import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy, FileSignature, RefreshCw, Sparkles } from 'lucide-react'
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { CategoryBadge, EvidenceQuote, RequestStatusBadge, ReviewStatusDot } from '../../components/domain'
import { Button } from '../../components/ui/Button'
import { cx } from '../../components/ui/cx'
import { Alert, ErrorState, LoadingBlock, Spinner, useErrorMessage } from '../../components/ui/Feedback'
import { PageHeader, Panel, Segmented } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api, newIdempotencyKey } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useEstimates, useProject, useRequest } from '../../lib/queries'
import { canContribute, canManage, useWorkspace } from '../../lib/session'
import type { ClientRequest, Finding, ProjectSummary, RequestItem } from '../../lib/types'
import { CreateChangeOrderDialog } from './CreateChangeOrderDialog'
import { DecisionPanel } from './DecisionPanel'

function MessageWithHighlights({ request, selectedId, onSelect }: {
  request: ClientRequest
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const text = request.message_text
  const parts: ReactNode[] = []
  let cursor = 0
  for (const item of [...request.items].sort((a, b) => a.start_offset - b.start_offset)) {
    if (item.start_offset < cursor) continue
    if (item.start_offset > cursor) parts.push(text.slice(cursor, item.start_offset))
    parts.push(
      <mark
        key={item.id}
        onClick={() => onSelect(item.id)}
        className={cx(
          'cursor-pointer rounded-[2px] px-0.5 text-fg transition-colors',
          item.id === selectedId ? 'bg-highlight ring-1 ring-warning' : 'bg-accent-soft hover:bg-highlight',
        )}
      >
        {text.slice(item.start_offset, item.end_offset)}
      </mark>,
    )
    cursor = item.end_offset
  }
  parts.push(text.slice(cursor))
  return <p className="leading-relaxed whitespace-pre-wrap">{parts}</p>
}

function RequirementList({ items, findings, selectedId, onSelect }: {
  items: RequestItem[]
  findings: Map<string, Finding>
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <ol className="space-y-1.5">
      {items.map((item) => {
        const f = findings.get(item.id)
        const selected = item.id === selectedId
        return (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item.id)}
              aria-current={selected ? 'true' : undefined}
              className={cx(
                'w-full rounded-md border px-3 py-2.5 text-left transition-colors',
                selected ? 'border-accent bg-accent-soft' : 'border-line bg-surface hover:border-line-strong',
              )}
            >
              <span className="flex items-start gap-2">
                <span className="mt-0.5 text-xs font-semibold text-fg-subtle tabular">{item.ordinal + 1}.</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] leading-snug">{f?.summary || item.summary || item.exact_text}</span>
                  {f && (
                    <span className="mt-1.5 flex flex-wrap items-center gap-2">
                      <CategoryBadge category={f.final_category ?? f.category} />
                      {f.review_status === 'PENDING' && <ReviewStatusDot status="PENDING" />}
                    </span>
                  )}
                </span>
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-wide text-fg-subtle uppercase">{title}</h3>
      {children}
    </section>
  )
}

function AnalysisPanel({ finding, item, projectId }: { finding: Finding; item: RequestItem; projectId: string }) {
  const { t, td } = useI18n()
  const notify = useToast()
  const supporting = finding.evidence.filter((e) => e.polarity === 'SUPPORTING')
  const counter = finding.evidence.filter((e) => e.polarity === 'COUNTER')
  const policyChanged = finding.ai_category !== null && finding.ai_category !== finding.category

  const copyQuestions = async () => {
    try {
      await navigator.clipboard.writeText(finding.clarifying_questions.join('\n'))
      notify(t('common.copied'))
    } catch {
      notify(t('errors.generic'), 'danger')
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <CategoryBadge category={finding.category} />
          {policyChanged && finding.ai_category && (
            <span className="text-[13px] text-fg-muted">
              {t('review.aiSuggested', { category: t(`categories.${finding.ai_category}`) })} · {t('review.policyChanged')}
            </span>
          )}
        </div>
        <p className="mt-2 text-[15px] font-medium">{finding.summary || item.exact_text}</p>
        <p className="mt-1 text-[13px] text-fg-muted">«{item.exact_text}»</p>
      </div>

      {finding.policy_notes.length > 0 && (
        <div className="space-y-2">
          {finding.policy_notes.map((n) => (
            <Alert key={n} tone={n.includes('FABRICATED') || n.includes('INVALID') ? 'danger' : 'warning'}>{td(`policy.${n}`, n)}</Alert>
          ))}
        </div>
      )}

      {finding.reason && (
        <Section title={t('review.reason')}><p className="leading-relaxed">{finding.reason}</p></Section>
      )}

      <Section title={t('review.supporting')}>
        {supporting.length === 0 ? (
          <p className="text-[13px] text-fg-muted">{t('review.noEvidence')}</p>
        ) : (
          <div className="space-y-2">
            {supporting.map((e) => (
              <EvidenceQuote key={e.span_id} projectId={projectId} documentVersionId={e.document_version_id} spanId={e.span_id}
                documentTitle={e.document_title} documentVersion={e.document_version} anchor={e} text={e.span_text} quote={e.quote}
                label={e.scope_item_title ? t('review.fromItem', { title: e.scope_item_title }) : t('review.retrievedText')} />
            ))}
          </div>
        )}
      </Section>

      {counter.length > 0 && (
        <Section title={t('review.counter')}>
          <div className="space-y-2">
            {counter.map((e) => (
              <EvidenceQuote key={e.span_id} tone="counter" projectId={projectId} documentVersionId={e.document_version_id} spanId={e.span_id}
                documentTitle={e.document_title} documentVersion={e.document_version} anchor={e} text={e.span_text} quote={e.quote}
                label={e.scope_item_title ? t('review.fromItem', { title: e.scope_item_title }) : t('review.retrievedText')} />
            ))}
          </div>
        </Section>
      )}

      {finding.uncertainties.length > 0 && (
        <Section title={t('review.uncertainties')}>
          <ul className="list-disc space-y-1 pl-5 text-[13px]">{finding.uncertainties.map((u) => <li key={u}>{u}</li>)}</ul>
        </Section>
      )}

      {finding.clarifying_questions.length > 0 && (
        <Section title={t('review.questions')}>
          <ul className="list-disc space-y-1 pl-5 text-[13px]">{finding.clarifying_questions.map((q) => <li key={q}>{q}</li>)}</ul>
          <Button size="sm" variant="ghost" icon={<Copy size={14} aria-hidden />} onClick={copyQuestions}>{t('review.copyQuestions')}</Button>
        </Section>
      )}

      <div className="space-y-1 border-t border-line pt-3 text-xs text-fg-subtle">
        {finding.model_confidence !== null && <p>{t('review.confidence', { value: Number(finding.model_confidence).toFixed(2) })}</p>}
        {finding.validation_errors.length > 0 && (
          <p>{t('review.validation')}: {finding.validation_errors.map((v) => td(`validation.${v.split(':')[0]}`, v)).join('; ')}</p>
        )}
      </div>
    </div>
  )
}

function RunBanner({ request, project, onAnalyze, analyzing }: {
  request: ClientRequest
  project: ProjectSummary
  onAnalyze: () => void
  analyzing: boolean
}) {
  const { t, td, formatNumber } = useI18n()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const ws = useWorkspace()
  const run = request.latest_run
  const retry = useMutation({
    mutationFn: () => api.post(`/analysis-runs/${run?.id}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.request(request.id) }),
    onError: (e) => notify(errorMessage(e), 'danger'),
  })
  const contribute = canContribute(ws.role)

  if (!run) {
    return (
      <Alert
        tone="info"
        title={t('review.notAnalysed')}
        action={contribute && (
          <Button size="sm" variant="primary" icon={<Sparkles size={14} aria-hidden />} loading={analyzing}
            disabled={project.baseline_version === null} onClick={onAnalyze}>
            {t('requests.analyze')}
          </Button>
        )}
      >
        {project.baseline_version === null && t('requests.baselineRequired')}
      </Alert>
    )
  }
  if (run.status === 'QUEUED' || run.status === 'RUNNING') {
    const willRetry = run.status === 'QUEUED' && run.error_code
    return (
      <Alert tone="info" title={run.status === 'QUEUED' && !willRetry ? t('review.queued') : t('review.running', { n: run.baseline_version })}>
        <span className="flex items-center gap-2">
          <Spinner size={13} />
          {willRetry ? `${td(`errors.${run.error_code}`, run.error_code ?? '')} ${t('jobs.willRetry')}` : t('review.runningHint')}
        </span>
      </Alert>
    )
  }
  if (run.status === 'FAILED') {
    return (
      <Alert
        tone="danger"
        title={t('review.failed')}
        action={contribute && <Button size="sm" icon={<RefreshCw size={14} aria-hidden />} loading={retry.isPending} onClick={() => retry.mutate()}>{t('review.retry')}</Button>}
      >
        {td(`errors.${run.error_code ?? ''}`, run.error_message ?? t('errors.generic'))} {t('review.failedHint')}
      </Alert>
    )
  }
  return (
    <p className="text-xs text-fg-subtle">
      {t('review.runMeta', { baseline: run.baseline_version, model: run.model ?? '—', tokens: formatNumber(run.token_usage.total_tokens ?? 0) })}
      {run.prompt_version && ` · ${t('review.promptVersion', { v: run.prompt_version })}`}
    </p>
  )
}

type Pane = 'message' | 'analysis' | 'decision'

export function RequestReviewPage() {
  const { requestId = '' } = useParams()
  const { t, formatDate } = useI18n()
  const ws = useWorkspace()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const req = useRequest(requestId)
  const project = useProject(req.data?.project_id ?? '')
  const estimates = useEstimates(requestId)
  const [params, setParams] = useSearchParams()
  const [pane, setPane] = useState<Pane>('analysis')
  const [coOpen, setCoOpen] = useState(false)
  const analyzeKey = useRef(newIdempotencyKey())

  const analyze = useMutation({
    mutationFn: () => api.post(`/requests/${requestId}/analyze`, {}, analyzeKey.current),
    onSuccess: () => {
      analyzeKey.current = newIdempotencyKey()
      qc.invalidateQueries({ queryKey: qk.request(requestId) })
    },
    onError: (e) => notify(errorMessage(e), 'danger'),
  })

  const findings = useMemo(() => {
    const m = new Map<string, Finding>()
    req.data?.latest_run?.findings.forEach((f) => m.set(f.request_item_id, f))
    return m
  }, [req.data])

  if (req.isPending || (req.data && project.isPending)) return <LoadingBlock rows={6} />
  if (req.isError) return <ErrorState error={req.error} onRetry={() => req.refetch()} />
  if (project.isError) return <ErrorState error={project.error} onRetry={() => project.refetch()} />
  const r = req.data
  const p = project.data!

  const selectedId = params.get('item') ?? r.items.find((i) => findings.get(i.id)?.review_status === 'PENDING')?.id ?? r.items[0]?.id ?? null
  const select = (id: string) => {
    setParams({ item: id }, { replace: true })
    setPane('analysis')
  }
  const item = r.items.find((i) => i.id === selectedId) ?? null
  const finding = item ? (findings.get(item.id) ?? null) : null
  const approvedEstimates = (estimates.data ?? []).filter((e) => e.status === 'APPROVED')
  const manage = canManage(ws.role)

  const left = (
    <Panel className="p-4">
      <h2 className="mb-2 text-[15px] font-semibold">{t('review.original')}</h2>
      <p className="mb-3 text-xs text-fg-subtle">
        {[r.sender, r.subject].filter(Boolean).join(' · ')}{(r.sender || r.subject) && ' · '}{t('requests.received', { date: formatDate(r.received_at, true) })}
      </p>
      <div className="rounded-md bg-surface-muted p-3 text-[13px]">
        <MessageWithHighlights request={r} selectedId={selectedId} onSelect={select} />
      </div>
      {r.items.length > 0 && (
        <>
          <h2 className="mb-2 mt-5 text-[15px] font-semibold">{t('review.requirements')}</h2>
          <RequirementList items={r.items} findings={findings} selectedId={selectedId} onSelect={select} />
        </>
      )}
    </Panel>
  )
  const center = (
    <Panel className="p-4">
      <h2 className="mb-3 text-[15px] font-semibold">{t('review.analysis')}</h2>
      {item && finding ? <AnalysisPanel finding={finding} item={item} projectId={p.id} /> : <p className="text-fg-muted">{t('review.selectRequirement')}</p>}
    </Panel>
  )
  const right = (
    <Panel className="p-4">
      <h2 className="mb-3 text-[15px] font-semibold">{t('review.decision')}</h2>
      {item && finding ? (
        <DecisionPanel request={r} item={item} finding={finding} project={p} manage={manage} />
      ) : (
        <p className="text-fg-muted">{t('review.selectRequirement')}</p>
      )}
    </Panel>
  )

  return (
    <>
      <PageHeader
        eyebrow={
          <Link to={`/projects/${p.id}/requests`} className="inline-flex items-center gap-1 hover:text-fg">
            <ArrowLeft size={14} aria-hidden />{p.title}
          </Link>
        }
        title={r.subject || (r.message_text.length > 80 ? `${r.message_text.slice(0, 80).trimEnd()}…` : r.message_text)}
        subtitle={<span className="flex flex-wrap items-center gap-3"><RequestStatusBadge status={r.status} />{r.items.length > 0 && <span>{t('requests.items', { n: r.items.length })}</span>}</span>}
        actions={
          <>
            {r.latest_run && r.latest_run.status !== 'QUEUED' && r.latest_run.status !== 'RUNNING' && canContribute(ws.role) && (
              <Button icon={<RefreshCw size={15} aria-hidden />} loading={analyze.isPending} onClick={() => analyze.mutate()}>{t('requests.reanalyze')}</Button>
            )}
            {manage && approvedEstimates.length > 0 && (
              <Button variant="primary" icon={<FileSignature size={15} aria-hidden />} onClick={() => setCoOpen(true)}>{t('changeOrders.create')}</Button>
            )}
          </>
        }
      />
      <div className="mb-4"><RunBanner request={r} project={p} onAnalyze={() => analyze.mutate()} analyzing={analyze.isPending} /></div>
      {r.possible_duplicate_of && (
        <Alert tone="warning" className="mb-4" title={t('requests.duplicateWarning')}
          action={<Link to={`/requests/${r.possible_duplicate_of}`} className="text-[13px] font-medium text-accent-fg hover:underline">{t('requests.openDuplicate')}</Link>} />
      )}

      {/* Desktop: three columns. Small screens: one pane at a time. */}
      <div className="hidden gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,1fr)] lg:items-start">
        {left}{center}{right}
      </div>
      <div className="space-y-3 lg:hidden">
        <Segmented<Pane>
          label={t('review.analysis')}
          value={pane}
          onChange={setPane}
          options={[
            { value: 'message', label: t('review.tabs.message') },
            { value: 'analysis', label: t('review.tabs.analysis') },
            { value: 'decision', label: t('review.tabs.decision') },
          ]}
        />
        {pane === 'message' ? left : pane === 'analysis' ? center : right}
      </div>

      {manage && <CreateChangeOrderDialog open={coOpen} onClose={() => setCoOpen(false)} request={r} estimates={estimates.data ?? []} />}
    </>
  )
}
