import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarClock, CircleHelp, Coins, FileQuestion, MessagesSquare, PlusCircle, ShieldCheck, Bug, Hourglass } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { EvidenceQuote } from '../../components/domain'
import { Badge, StatusDot, type BadgeTone } from '../../components/ui/Badge'
import { Button, ButtonLink } from '../../components/ui/Button'
import { cx } from '../../components/ui/cx'
import { Dialog } from '../../components/ui/Dialog'
import { Alert, EmptyState, ErrorState, LoadingBlock, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Textarea } from '../../components/ui/Field'
import { Panel, PanelHeader } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useSignal, useSignals } from '../../lib/queries'
import type { CommercialSignal, CommercialSignalDetail, SignalCategory, SignalStatus } from '../../lib/types'

const categoryTone: Record<SignalCategory, BadgeTone> = {
  CHANGE_CANDIDATE: 'warning',
  AMBIGUOUS: 'violet',
  INSUFFICIENT_EVIDENCE: 'danger',
  BUG_FIX: 'info',
  IN_SCOPE: 'success',
  TIMELINE_CHANGE_CANDIDATE: 'warning',
  PAYMENT_COMMITMENT_MENTION: 'neutral',
  UNANALYZED: 'danger',
}
const categoryIcon: Record<SignalCategory, ReactNode> = {
  CHANGE_CANDIDATE: <PlusCircle size={13} aria-hidden />,
  AMBIGUOUS: <CircleHelp size={13} aria-hidden />,
  INSUFFICIENT_EVIDENCE: <FileQuestion size={13} aria-hidden />,
  BUG_FIX: <Bug size={13} aria-hidden />,
  IN_SCOPE: <ShieldCheck size={13} aria-hidden />,
  TIMELINE_CHANGE_CANDIDATE: <CalendarClock size={13} aria-hidden />,
  PAYMENT_COMMITMENT_MENTION: <Coins size={13} aria-hidden />,
  UNANALYZED: <Hourglass size={13} aria-hidden />,
}
const statusTone: Record<SignalStatus, BadgeTone> = {
  OPEN: 'warning',
  CLARIFICATION_REQUESTED: 'violet',
  DISMISSED: 'neutral',
  RESOLVED: 'success',
  CONVERTED: 'accent',
}
const ACTIVE: SignalStatus[] = ['OPEN', 'CLARIFICATION_REQUESTED']

export function SignalCategoryBadge({ category }: { category: SignalCategory }) {
  const { t } = useI18n()
  return <Badge tone={categoryTone[category]} icon={categoryIcon[category]}>{t(`telegram.signals.category.${category}`)}</Badge>
}

function SignalRow({ s, onOpen }: { s: CommercialSignal; onOpen: () => void }) {
  const { t, formatDate } = useI18n()
  const needsAttention = s.evidence_state !== 'VALID'
  return (
    <li>
      <button type="button" onClick={onOpen}
        className="block w-full px-4 py-3.5 text-left transition-colors hover:bg-surface-muted focus-visible:bg-surface-muted">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <SignalCategoryBadge category={s.category} />
            {s.stale_baseline && <Badge tone="neutral">{t('telegram.signals.staleShort')}</Badge>}
            {needsAttention && (
              <Badge tone="danger" icon={<AlertTriangle size={12} aria-hidden />}>
                {s.evidence_state === 'REVOKED' ? t('telegram.signals.deletedShort') : t('telegram.signals.editedShort')}
              </Badge>
            )}
          </div>
          <StatusDot tone={statusTone[s.status]}>{t(`telegram.signals.status.${s.status}`)}</StatusDot>
        </div>
        <p className="mt-1.5 line-clamp-2 font-medium">{s.summary}</p>
        <p className="mt-1 text-xs text-fg-subtle">
          {t('telegram.signals.lastSeen', { date: formatDate(s.last_seen_at, true) })}
          {s.occurrences > 1 && <> · <span className="tabular">{t('telegram.signals.occurrences', { n: s.occurrences })}</span></>}
        </p>
      </button>
    </li>
  )
}

export function SignalsPanel({ projectId, manage }: { projectId: string; manage: boolean }) {
  const { t } = useI18n()
  const [scope, setScope] = useState<'active' | 'all'>('active')
  const [openId, setOpenId] = useState<string | null>(null)
  const q = useSignals(projectId, scope)

  return (
    <Panel aria-labelledby="tg-signals">
      <PanelHeader
        id="tg-signals"
        title={t('telegram.signals.title')}
        description={t('telegram.signals.subtitle')}
        actions={
          <Button size="sm" variant="ghost" aria-pressed={scope === 'all'} onClick={() => setScope(scope === 'all' ? 'active' : 'all')}>
            {scope === 'all' ? t('telegram.signals.hideClosed') : t('telegram.signals.showClosed')}
          </Button>
        }
      />
      {q.isPending ? (
        <div className="p-4"><LoadingBlock rows={3} /></div>
      ) : q.isError ? (
        <div className="p-4"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>
      ) : q.data.length === 0 ? (
        <div className="p-4">
          <EmptyState icon={<MessagesSquare size={26} aria-hidden />} title={t('telegram.signals.emptyTitle')} body={t('telegram.signals.emptyBody')} />
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {q.data.map((s) => <SignalRow key={s.id} s={s} onOpen={() => setOpenId(s.id)} />)}
        </ul>
      )}
      <SignalDialog id={openId} projectId={projectId} manage={manage} onClose={() => setOpenId(null)} />
    </Panel>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-[13px] font-semibold tracking-wide text-fg-muted uppercase">{title}</h3>
      {children}
    </section>
  )
}

type Decision = 'DISMISS' | 'IN_SCOPE' | 'BUG_FIX'
const DECISIONS: Decision[] = ['DISMISS', 'IN_SCOPE', 'BUG_FIX']

function SignalDialog({ id, projectId, manage, onClose }: { id: string | null; projectId: string; manage: boolean; onClose: () => void }) {
  const { t, formatDate } = useI18n()
  const q = useSignal(id)
  const qc = useQueryClient()
  const notify = useToast()
  const navigate = useNavigate()
  const errorMessage = useErrorMessage()
  const [closing, setClosing] = useState(false)
  const [decision, setDecision] = useState<Decision>('DISMISS')
  const [reason, setReason] = useState('')
  const [questions, setQuestions] = useState<string[] | null>(null)

  const close = () => {
    setClosing(false)
    setDecision('DISMISS')
    setReason('')
    setQuestions(null)
    onClose()
  }
  const refresh = (data?: CommercialSignalDetail) => {
    if (data) qc.setQueryData(qk.signal(data.id), data)
    qc.invalidateQueries({ queryKey: ['signals', projectId] })
    qc.invalidateQueries({ queryKey: qk.project(projectId) })
  }

  const decide = useMutation({
    mutationFn: (d: Decision) => {
      const s = q.data!
      return d === 'DISMISS'
        ? api.post<CommercialSignalDetail>(`/commercial-signals/${s.id}/dismiss`, { expected_version: s.version, reason })
        : api.post<CommercialSignalDetail>(`/commercial-signals/${s.id}/resolve`, { expected_version: s.version, reason, category: d })
    },
    onSuccess: (data) => {
      refresh(data)
      notify(t('telegram.signals.done'))
      close()
    },
  })
  const clarify = useMutation({
    mutationFn: () => api.post<{ suggested_questions: string[] }>(`/commercial-signals/${q.data!.id}/request-clarification`, { expected_version: q.data!.version }),
    onSuccess: (data) => {
      setQuestions(data.suggested_questions)
      refresh()
      qc.invalidateQueries({ queryKey: qk.signal(q.data!.id) })
    },
  })
  const review = useMutation({
    mutationFn: async () => {
      const s = q.data!
      if (s.request_id) return s.request_id
      const r = await api.post<{ request_id: string }>(`/commercial-signals/${s.id}/convert-to-request`)
      return r.request_id
    },
    onSuccess: (requestId) => {
      refresh()
      navigate(`/requests/${requestId}`)
    },
  })

  const s = q.data
  const active = s ? ACTIVE.includes(s.status) : false
  const evidence = s?.finding?.evidence ?? []
  const supporting = evidence.filter((e) => e.polarity === 'SUPPORTING')
  const counter = evidence.filter((e) => e.polarity === 'COUNTER')
  const hint = s && (s.category === 'UNANALYZED' || s.category === 'PAYMENT_COMMITMENT_MENTION' || s.category === 'TIMELINE_CHANGE_CANDIDATE')
    ? t(`telegram.signals.hints.${s.category}`) : null
  const actionError = decide.error ?? clarify.error ?? review.error

  // Mobile: secondary actions share one row, the primary action gets its own full-width row.
  const secondary = 'flex-1 sm:flex-none'
  const footer = s && manage ? (
    closing ? (
      <>
        <Button className={secondary} onClick={() => setClosing(false)}>{t('common.cancel')}</Button>
        <Button className={secondary} variant="primary" disabled={reason.trim().length < 3} loading={decide.isPending}
          onClick={() => decide.mutate(decision)}>
          {t('common.confirm')}
        </Button>
      </>
    ) : active ? (
      <>
        <Button className={secondary} onClick={() => setClosing(true)}>{t('telegram.signals.actions.close')}</Button>
        {s.status === 'OPEN' && (
          <Button className={secondary} loading={clarify.isPending} onClick={() => clarify.mutate()}>{t('telegram.signals.actions.clarify')}</Button>
        )}
        <Button className="w-full sm:w-auto" variant="primary" loading={review.isPending} disabled={s.evidence_state === 'REVOKED' && !s.request_id}
          onClick={() => review.mutate()}>
          {s.request_id ? t('telegram.signals.actions.review') : t('telegram.signals.actions.convert')}
        </Button>
      </>
    ) : s.change_order_id ? (
      <ButtonLink variant="primary" to={`/change-orders/${s.change_order_id}`}>{t('telegram.signals.actions.openChangeOrder')}</ButtonLink>
    ) : undefined
  ) : undefined

  return (
    <Dialog open={id !== null} onClose={close} size="lg" title={s ? t(`telegram.signals.category.${s.category}`) : t('telegram.signals.detailTitle')}
      description={s ? s.summary : undefined} footer={footer}>
      {q.isPending ? (
        <LoadingBlock rows={4} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <SignalCategoryBadge category={s!.category} />
            <StatusDot tone={statusTone[s!.status]}>{t(`telegram.signals.status.${s!.status}`)}</StatusDot>
            {s!.occurrences > 1 && <span className="text-xs text-fg-subtle tabular">{t('telegram.signals.occurrences', { n: s!.occurrences })}</span>}
          </div>
          {actionError ? <Alert tone="danger" title={errorMessage(actionError)} /> : null}
          {s!.evidence_state === 'CHANGED' && <Alert tone="warning" title={t('telegram.signals.evidenceChanged')} />}
          {s!.evidence_state === 'REVOKED' && <Alert tone="warning" title={t('telegram.signals.evidenceRevoked')} />}
          {s!.stale_baseline && s!.baseline_version !== null && (
            <Alert tone="info" title={t('telegram.signals.staleBaseline', { n: s!.baseline_version })} />
          )}
          {hint && <Alert tone="info" title={hint} />}
          {s!.resolution_reason && !active && <p className="text-[13px] text-fg-muted">{t('telegram.signals.resolution', { reason: s!.resolution_reason })}</p>}

          {closing && (
            <div className="space-y-3 rounded-md border border-line p-3">
              <fieldset>
                <legend className="text-[13px] font-medium">{t('telegram.signals.decision')}</legend>
                <div className="mt-2 space-y-1.5">
                  {DECISIONS.map((d) => (
                    <label key={d} className="flex items-center gap-2 text-[13px]">
                      <input type="radio" name="signal-decision" className="size-4 accent-(--tr-accent)" checked={decision === d}
                        onChange={() => setDecision(d)} />
                      {t(`telegram.signals.decisions.${d}`)}
                    </label>
                  ))}
                </div>
              </fieldset>
              <Field label={t('telegram.signals.reason')}>
                {(p) => (
                  <Textarea {...p} rows={3} maxLength={2000} placeholder={t('telegram.signals.reasonPlaceholder')}
                    value={reason} onChange={(e) => setReason(e.target.value)} />
                )}
              </Field>
            </div>
          )}

          {questions !== null && (
            <Alert tone="info" title={t('telegram.signals.clarifyTitle')}>
              <p>{t('telegram.signals.clarifyBody')}</p>
              {questions.length ? (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-fg">{questions.map((x) => <li key={x}>{x}</li>)}</ul>
              ) : (
                <p className="mt-2">{t('telegram.signals.noQuestions')}</p>
              )}
            </Alert>
          )}

          <Section title={t('telegram.signals.clientSaid')}>
            <ul className="space-y-2">
              {s!.evidence.map((e) => (
                <li key={e.id}>
                  <figure className={cx('rounded-md border-l-[3px] bg-surface-muted px-3 py-2.5',
                    e.state === 'VALID' ? 'border-accent' : 'border-line-strong')}>
                    <blockquote className={cx('text-[13px] leading-relaxed whitespace-pre-wrap', e.quote ? 'text-fg' : 'text-fg-subtle italic')}>
                      {e.quote ?? t('telegram.signals.unavailable')}
                    </blockquote>
                    <figcaption className="mt-1.5 text-xs text-fg-muted">
                      {e.direction === 'INBOUND' ? t('telegram.signals.fromClient') : t('telegram.signals.fromYou')} · {formatDate(e.sent_at, true)}
                    </figcaption>
                  </figure>
                </li>
              ))}
            </ul>
          </Section>

          {s!.finding && (
            <>
              <Section title={t('telegram.signals.contract')}>
                {supporting.length === 0 && counter.length === 0 ? (
                  <p className="text-[13px] text-fg-muted">{t('telegram.signals.noContract')}</p>
                ) : (
                  <div className="space-y-2">
                    {[...supporting, ...counter].map((e) => (
                      <EvidenceQuote key={`${e.polarity}-${e.span_id}`} tone={e.polarity === 'COUNTER' ? 'counter' : 'neutral'}
                        projectId={projectId} documentVersionId={e.document_version_id} spanId={e.span_id}
                        documentTitle={e.document_title} documentVersion={e.document_version} anchor={e} text={e.span_text} quote={e.quote}
                        label={e.scope_item_title ? t('review.fromItem', { title: e.scope_item_title }) : t('review.retrievedText')} />
                    ))}
                  </div>
                )}
              </Section>
              <Section title={t('telegram.signals.why')}>
                {s!.finding.reason && <p className="text-[13px] leading-relaxed">{s!.finding.reason}</p>}
                {s!.finding.uncertainties.length > 0 && (
                  <>
                    <p className="text-[13px] font-medium">{t('telegram.signals.uncertainties')}</p>
                    <ul className="list-disc space-y-1 pl-5 text-[13px] text-fg-muted">
                      {s!.finding.uncertainties.map((u) => <li key={u}>{u}</li>)}
                    </ul>
                  </>
                )}
                <p className="text-xs text-fg-subtle">{t('telegram.signals.aiNote')}</p>
              </Section>
            </>
          )}

          {active && manage && !closing && (
            <Section title={t('telegram.signals.nextStep')}>
              <p className="text-[13px] text-fg-muted">{t('telegram.signals.nextStepBody')}</p>
            </Section>
          )}
        </div>
      )}
    </Dialog>
  )
}
