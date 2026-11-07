import { FileSignature } from 'lucide-react'
import { Link } from 'react-router'
import { ChangeOrderStatusBadge, Money } from '../../components/domain'
import { EmptyState, ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { PageHeader } from '../../components/ui/Layout'
import { useI18n } from '../../lib/i18n'
import { useChangeOrders } from '../../lib/queries'
import { useWorkspace } from '../../lib/session'
import { useProjectContext } from '../projects/ProjectLayout'

function List({ projectId, showProject }: { projectId?: string; showProject: boolean }) {
  const { t, formatDate } = useI18n()
  const ws = useWorkspace()
  const q = useChangeOrders(ws.id, projectId)
  if (q.isPending) return <LoadingBlock />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  if (q.data.length === 0) {
    return <EmptyState icon={<FileSignature size={28} aria-hidden />} title={t('changeOrders.emptyTitle')} body={t('changeOrders.emptyBody')} />
  }
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
      {q.data.map((co) => (
        <li key={co.id}>
          <Link to={`/change-orders/${co.id}`} className="flex flex-col gap-2 px-4 py-3.5 transition-colors hover:bg-surface-muted sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="truncate font-medium">{t('changeOrders.number', { n: co.number })} · {co.title}</p>
              <p className="mt-0.5 text-xs text-fg-subtle">
                {showProject && `${co.project_title} · `}{t('changeOrders.revision', { n: co.revision_no })} · {t('changeOrders.updated', { date: formatDate(co.updated_at, true) })}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <Money amount={co.total} currency={co.currency} className="font-medium" />
              <ChangeOrderStatusBadge status={co.status} />
            </div>
          </Link>
        </li>
      ))}
    </ul>
  )
}

export function ChangeOrdersPage() {
  const { t } = useI18n()
  return (
    <>
      <PageHeader title={t('changeOrders.title')} subtitle={t('changeOrders.subtitle')} />
      <List showProject />
    </>
  )
}

export function ProjectChangeOrdersTab() {
  const { project } = useProjectContext()
  return <List projectId={project.id} showProject={false} />
}
