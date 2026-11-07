import { useI18n } from '../../lib/i18n'
import type { AuditEvent } from '../../lib/types'

export function ActivityList({ events, emptyLabel }: { events: AuditEvent[]; emptyLabel: string }) {
  const { t, td, formatDate } = useI18n()
  if (!events.length) return <p className="px-4 py-6 text-fg-muted">{emptyLabel}</p>
  return (
    <ol className="divide-y divide-line">
      {events.map((e) => (
        <li key={e.id} className="flex flex-col gap-0.5 px-4 py-2.5 sm:flex-row sm:items-baseline sm:gap-3">
          <time className="shrink-0 text-xs text-fg-subtle tabular sm:w-40" dateTime={e.occurred_at}>
            {formatDate(e.occurred_at, true)}
          </time>
          <p className="min-w-0">
            <span className="font-medium">{e.actor_name ?? t('activity.system')}</span>{' '}
            <span className="text-fg-muted">{td(`activity.events.${e.event_type}`, e.event_type)}</span>
            {e.object_version !== null && e.object_type !== 'project' && (
              <span className="text-fg-subtle"> · {t('common.version', { n: e.object_version })}</span>
            )}
          </p>
        </li>
      ))}
    </ol>
  )
}
