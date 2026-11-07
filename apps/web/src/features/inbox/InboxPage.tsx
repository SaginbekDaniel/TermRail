import { Inbox } from 'lucide-react'
import { Link } from 'react-router'
import { CategoryBadge } from '../../components/domain'
import { EmptyState, ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { PageHeader } from '../../components/ui/Layout'
import { useI18n } from '../../lib/i18n'
import { useInbox } from '../../lib/queries'
import { useWorkspace } from '../../lib/session'

export function InboxPage() {
  const { t, formatDate } = useI18n()
  const ws = useWorkspace()
  const q = useInbox(ws.id)
  return (
    <>
      <PageHeader title={t('inbox.title')} subtitle={t('inbox.subtitle')} />
      {q.isPending ? (
        <LoadingBlock />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <EmptyState icon={<Inbox size={28} aria-hidden />} title={t('inbox.emptyTitle')} body={t('inbox.emptyBody')} />
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
          {q.data.map((f) => (
            <li key={f.finding_id}>
              <Link
                to={`/requests/${f.request_id}?item=${f.request_item_id}`}
                className="flex flex-col gap-2 px-4 py-3.5 transition-colors hover:bg-surface-muted sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="font-medium">{f.summary || f.requirement}</p>
                  <p className="mt-0.5 line-clamp-1 text-[13px] text-fg-muted">«{f.requirement}»</p>
                  <p className="mt-1 text-xs text-fg-subtle">{f.project_title} · {t('requests.received', { date: formatDate(f.received_at, true) })}</p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <CategoryBadge category={f.category} />
                  <span className="text-[13px] font-medium text-accent-fg">{t('inbox.open')}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
