import { ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { Panel, PanelHeader } from '../../components/ui/Layout'
import { useI18n } from '../../lib/i18n'
import { useProjectAudit } from '../../lib/queries'
import { ActivityList } from './ActivityList'
import { useProjectContext } from './ProjectLayout'

export function ActivityTab() {
  const { project: p } = useProjectContext()
  const { t } = useI18n()
  const q = useProjectAudit(p.id)
  return (
    <Panel>
      <PanelHeader title={t('activity.title')} description={t('activity.subtitle')} />
      {q.isPending ? (
        <div className="p-4"><LoadingBlock /></div>
      ) : q.isError ? (
        <div className="p-4"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>
      ) : (
        <ActivityList events={q.data} emptyLabel={t('activity.empty')} />
      )}
    </Panel>
  )
}
