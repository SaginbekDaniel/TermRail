import { ArrowRight, FolderPlus } from 'lucide-react'
import { Link } from 'react-router'
import { ButtonLink } from '../../components/ui/Button'
import { ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { PageHeader, Panel, PanelHeader, Stat } from '../../components/ui/Layout'
import { useI18n } from '../../lib/i18n'
import { useOverview } from '../../lib/queries'
import { canManage, useWorkspace } from '../../lib/session'
import type { MoneyByCurrency } from '../../lib/types'
import { ActivityList } from '../projects/ActivityList'

function MoneyList({ values }: { values: MoneyByCurrency[] }) {
  const { t, formatMoney } = useI18n()
  if (!values.length) return <span className="text-fg-subtle">{t('overview.noValue')}</span>
  return (
    <span className="flex flex-col">
      {values.map((v) => <span key={v.currency}>{formatMoney(v.amount, v.currency)}</span>)}
    </span>
  )
}

export function OverviewPage() {
  const { t, formatNumber } = useI18n()
  const ws = useWorkspace()
  const q = useOverview(ws.id)

  return (
    <>
      <PageHeader title={t('overview.title')} subtitle={t('overview.subtitle')} />
      {q.isPending ? (
        <LoadingBlock rows={4} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="space-y-5">
          <Panel>
            <dl className="grid grid-cols-2 divide-line sm:grid-cols-3 lg:grid-cols-5 lg:divide-x [&>*]:border-line max-lg:[&>*]:border-b">
              <Stat label={t('overview.activeProjects')} value={formatNumber(q.data.active_projects)} />
              <div className="min-w-0 px-4 py-3.5">
                <dt className="text-[13px] text-fg-muted">{t('overview.needsReview')}</dt>
                <dd className="mt-1 flex items-baseline gap-2">
                  <span className="text-xl font-semibold tabular">{formatNumber(q.data.needs_review)}</span>
                  {q.data.needs_review > 0 && (
                    <Link to="/inbox" className="text-[13px] font-medium text-accent-fg hover:underline">{t('overview.reviewNow')}</Link>
                  )}
                </dd>
              </div>
              <Stat label={t('overview.requests')} value={formatNumber(q.data.requests_total)} />
              <Stat label={t('overview.potential')} value={<MoneyList values={q.data.potential_change_value} />} hint={t('overview.potentialHint')} />
              <Stat label={t('overview.approved')} value={<MoneyList values={q.data.approved_change_value} />} hint={t('overview.approvedHint')} />
            </dl>
          </Panel>

          {q.data.active_projects === 0 && (
            <Panel className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-[15px] font-semibold">{t('overview.gettingStarted')}</h2>
                <p className="mt-0.5 text-fg-muted">{t('overview.gettingStartedBody')}</p>
              </div>
              {canManage(ws.role) && (
                <ButtonLink to="/projects?new=1" variant="primary" icon={<FolderPlus size={16} aria-hidden />}>
                  {t('overview.newProject')}
                </ButtonLink>
              )}
            </Panel>
          )}

          <Panel>
            <PanelHeader
              title={t('overview.recentActivity')}
              actions={<Link to="/projects" className="inline-flex items-center gap-1 text-[13px] font-medium text-accent-fg hover:underline">{t('nav.projects')}<ArrowRight size={14} aria-hidden /></Link>}
            />
            <ActivityList events={q.data.recent_activity} emptyLabel={t('overview.noActivity')} />
          </Panel>
        </div>
      )}
    </>
  )
}
