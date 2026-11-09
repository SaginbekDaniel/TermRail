import { Alert, ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { useI18n } from '../../lib/i18n'
import { useTelegramBinding, useTelegramStatus } from '../../lib/queries'
import { useWorkspace } from '../../lib/session'
import { useProjectContext } from '../projects/ProjectLayout'
import { SignalsPanel } from './SignalsPanel'
import { ChatPanel, ConnectionPanel, MonitoringPanel, SetupSteps } from './TelegramSetup'

/**
 * Project → Telegram. Order follows what the person needs next: during setup the connection and chat
 * come first; once a chat is linked, the cases found in it lead and the setup panels follow.
 * Manual request intake keeps working regardless of anything on this tab.
 */
export function TelegramTab() {
  const { project, manage } = useProjectContext()
  const { t } = useI18n()
  const ws = useWorkspace()
  const status = useTelegramStatus(ws.id)
  const binding = useTelegramBinding(project.id)

  if (status.isPending || binding.isPending) return <LoadingBlock rows={4} />
  if (status.isError) return <ErrorState error={status.error} onRetry={() => status.refetch()} />
  if (binding.isError) return <ErrorState error={binding.error} onRetry={() => binding.refetch()} />

  const st = status.data
  const b = binding.data
  if (!st.configured) {
    return <Alert tone="info" title={t('telegram.notConfiguredTitle')}>{t('telegram.notConfiguredBody')}</Alert>
  }
  const connected = st.state === 'CONNECTED'
  const bound = b.binding_id !== null

  const connection = <ConnectionPanel key="connection" workspaceId={ws.id} status={st} manage={manage} />
  const chat = <ChatPanel key="chat" workspaceId={ws.id} projectId={project.id} binding={b} connected={connected} manage={manage} />
  const monitoring = <MonitoringPanel key="monitoring" projectId={project.id} binding={b} manage={manage} />

  return (
    <div className="max-w-4xl space-y-4">
      <p className="max-w-2xl text-fg-muted">{t('telegram.intro')}</p>
      {b.status !== 'MONITORING' && (
        <SetupSteps hasBaseline={b.has_approved_baseline} connected={connected} bound={bound} monitoring={b.monitoring_enabled} />
      )}
      {!manage && <p className="text-[13px] text-fg-subtle">{t('telegram.viewerNote')}</p>}
      {bound ? (
        <>
          <SignalsPanel projectId={project.id} manage={manage} />
          {monitoring}
          {chat}
          {connection}
        </>
      ) : (
        <>
          {connection}
          {chat}
        </>
      )}
    </div>
  )
}
