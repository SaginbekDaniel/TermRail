import { Outlet, useOutletContext, useParams } from 'react-router'
import { DemoBadge } from '../../components/domain'
import { ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { LinkTabs, PageHeader } from '../../components/ui/Layout'
import { useI18n } from '../../lib/i18n'
import { useProject } from '../../lib/queries'
import { canManage, useWorkspace } from '../../lib/session'
import type { ProjectSummary } from '../../lib/types'

export interface ProjectContext {
  project: ProjectSummary
  manage: boolean
}

export function useProjectContext(): ProjectContext {
  return useOutletContext<ProjectContext>()
}

export function ProjectLayout() {
  const { projectId = '' } = useParams()
  const { t, formatMoney } = useI18n()
  const ws = useWorkspace()
  const q = useProject(projectId)

  if (q.isPending) return <LoadingBlock rows={4} />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const p = q.data
  const base = `/projects/${p.id}`
  const manage = canManage(ws.role)

  return (
    <>
      <PageHeader
        eyebrow={<span className="flex items-center gap-2">{p.client_name}{p.is_demo && <DemoBadge />}</span>}
        title={p.title}
        subtitle={p.budget ? `${t('projects.contractValue')}: ${formatMoney(p.budget, p.currency)}` : undefined}
      />
      <LinkTabs
        label={p.title}
        items={[
          { to: base, label: t('projects.tabs.overview'), end: true },
          { to: `${base}/documents`, label: t('projects.tabs.documents') },
          { to: `${base}/scope`, label: t('projects.tabs.scope') },
          { to: `${base}/requests`, label: t('projects.tabs.requests'), count: p.open_reviews },
          { to: `${base}/rates`, label: t('projects.tabs.rates') },
          { to: `${base}/change-orders`, label: t('projects.tabs.changeOrders') },
          ...(manage ? [{ to: `${base}/activity`, label: t('projects.tabs.activity') }] : []),
        ]}
      />
      <Outlet context={{ project: p, manage } satisfies ProjectContext} />
    </>
  )
}
