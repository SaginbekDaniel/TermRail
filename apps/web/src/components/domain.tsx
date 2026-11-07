import { Bug, CircleHelp, FileQuestion, FileText, PlusCircle, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useI18n } from '../lib/i18n'
import type {
  Anchor,
  Category,
  ChangeOrderStatus,
  InclusionType,
  JobStatus,
  ParseStatus,
  RequestStatus,
  ReviewStatus,
} from '../lib/types'
import { Badge, StatusDot, type BadgeTone } from './ui/Badge'
import { cx } from './ui/cx'

export const CATEGORY_ORDER: Category[] = ['CHANGE_CANDIDATE', 'BUG_FIX', 'IN_SCOPE', 'AMBIGUOUS', 'INSUFFICIENT_EVIDENCE']

const categoryTone: Record<Category, BadgeTone> = {
  IN_SCOPE: 'success',
  BUG_FIX: 'info',
  CHANGE_CANDIDATE: 'warning',
  AMBIGUOUS: 'violet',
  INSUFFICIENT_EVIDENCE: 'danger',
}
const categoryIcon: Record<Category, ReactNode> = {
  IN_SCOPE: <ShieldCheck size={13} aria-hidden />,
  BUG_FIX: <Bug size={13} aria-hidden />,
  CHANGE_CANDIDATE: <PlusCircle size={13} aria-hidden />,
  AMBIGUOUS: <CircleHelp size={13} aria-hidden />,
  INSUFFICIENT_EVIDENCE: <FileQuestion size={13} aria-hidden />,
}

export function CategoryBadge({ category, className }: { category: Category; className?: string }) {
  const { t } = useI18n()
  return (
    <Badge tone={categoryTone[category]} icon={categoryIcon[category]} className={className} title={t(`categoryHints.${category}`)}>
      {t(`categories.${category}`)}
    </Badge>
  )
}

const inclusionTone: Record<InclusionType, BadgeTone> = { INCLUDED: 'success', EXCLUDED: 'danger', CONDITION: 'info' }

export function InclusionBadge({ type }: { type: InclusionType }) {
  const { t } = useI18n()
  return <Badge tone={inclusionTone[type]} title={t(`scope.typeHints.${type}`)}>{t(`scope.types.${type}`)}</Badge>
}

const parseTone: Record<ParseStatus, BadgeTone> = {
  PENDING: 'neutral', PARSING: 'info', PARSED: 'success', NEEDS_OCR_OR_REVIEW: 'warning', FAILED: 'danger',
}
export function ParseStatusBadge({ status }: { status: ParseStatus }) {
  const { t } = useI18n()
  return <StatusDot tone={parseTone[status]}>{t(`documents.status.${status}`)}</StatusDot>
}

const requestTone: Record<RequestStatus, BadgeTone> = {
  NEW: 'neutral', ANALYZING: 'info', NEEDS_REVIEW: 'warning', REVIEWED: 'success', FAILED: 'danger',
}
export function RequestStatusBadge({ status }: { status: RequestStatus }) {
  const { t } = useI18n()
  return <StatusDot tone={requestTone[status]}>{t(`requests.status.${status}`)}</StatusDot>
}

const coTone: Record<ChangeOrderStatus, BadgeTone> = {
  DRAFT: 'neutral', INTERNAL_REVIEW: 'warning', APPROVED_INTERNAL: 'success', EXPORTED: 'accent', CANCELLED: 'danger',
}
export function ChangeOrderStatusBadge({ status }: { status: ChangeOrderStatus }) {
  const { t } = useI18n()
  return <Badge tone={coTone[status]}>{t(`changeOrders.status.${status}`)}</Badge>
}

const reviewTone: Record<ReviewStatus, BadgeTone> = {
  PENDING: 'warning', AUTO_ACCEPTED: 'neutral', ACCEPTED: 'success', OVERRIDDEN: 'accent', CLARIFICATION_REQUESTED: 'violet',
}
export function ReviewStatusDot({ status }: { status: ReviewStatus }) {
  const { t } = useI18n()
  return <StatusDot tone={reviewTone[status]}>{t(`review.reviewStatus.${status}`)}</StatusDot>
}

const jobTone: Record<JobStatus, BadgeTone> = { QUEUED: 'neutral', RUNNING: 'info', SUCCEEDED: 'success', FAILED: 'danger' }
export function JobStatusDot({ status }: { status: JobStatus }) {
  const { t } = useI18n()
  return <StatusDot tone={jobTone[status]}>{t(`jobs.status.${status}`)}</StatusDot>
}

export function useAnchorLabel(): (a: Anchor) => string {
  const { t } = useI18n()
  return (a) => {
    if (a.anchor_type === 'PDF_PAGE') return t('anchors.page', { n: a.page ?? '?' })
    if (a.anchor_type === 'DOCX_PARAGRAPH') return t('anchors.paragraph', { n: (a.paragraph_index ?? 0) + 1 })
    const m = /^t(\d+):r(\d+):c(\d+)$/.exec(a.table_ref ?? '')
    return m ? t('anchors.cell', { t: Number(m[1]) + 1, r: Number(m[2]) + 1, c: Number(m[3]) + 1 }) : (a.table_ref ?? '')
  }
}

/** Highlights `quote` inside `text` (both server-sourced). */
export function HighlightedText({ text, quote }: { text: string; quote?: string }) {
  if (!quote || quote === text) return <>{text}</>
  const idx = text.toLowerCase().indexOf(quote.toLowerCase())
  if (idx < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded-[2px] bg-highlight px-0.5 text-fg">{text.slice(idx, idx + quote.length)}</mark>
      {text.slice(idx + quote.length)}
    </>
  )
}

/** A citation of an exact source span, linking to the document viewer at that span. */
export function EvidenceQuote({ projectId, documentVersionId, spanId, documentTitle, documentVersion, anchor, text, quote,
  label, tone = 'neutral' }: {
  projectId: string
  documentVersionId: string
  spanId: string
  documentTitle: string
  documentVersion: number
  anchor: Anchor
  text: string
  quote?: string
  label?: ReactNode
  tone?: 'neutral' | 'counter'
}) {
  const { t } = useI18n()
  const anchorLabel = useAnchorLabel()
  return (
    <figure
      className={cx(
        'rounded-md border-l-[3px] bg-surface-muted px-3 py-2.5',
        tone === 'counter' ? 'border-warning' : 'border-accent',
      )}
    >
      {label && <div className="mb-1 text-xs font-medium text-fg-muted">{label}</div>}
      <blockquote className="text-[13px] leading-relaxed text-fg">
        <HighlightedText text={text} quote={quote} />
      </blockquote>
      <figcaption className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-muted">
        <FileText size={12} aria-hidden />
        <span className="min-w-0 truncate">
          {documentTitle} · {t('common.version', { n: documentVersion })} · {anchorLabel(anchor)}
        </span>
        <Link
          to={`/projects/${projectId}/documents/${documentVersionId}?span=${spanId}`}
          className="font-medium text-accent-fg hover:underline"
        >
          {t('review.openSource')}
        </Link>
      </figcaption>
    </figure>
  )
}

export function Money({ amount, currency, className }: { amount: string | null | undefined; currency: string; className?: string }) {
  const { formatMoney } = useI18n()
  return <span className={cx('tabular', className)}>{formatMoney(amount, currency)}</span>
}

export function DemoBadge() {
  const { t } = useI18n()
  return <Badge tone="violet">{t('common.demo')}</Badge>
}
