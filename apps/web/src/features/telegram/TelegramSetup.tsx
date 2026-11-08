import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, ExternalLink, MessageCircle, ShieldCheck } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { StatusDot, type BadgeTone } from '../../components/ui/Badge'
import { Button, ButtonLink } from '../../components/ui/Button'
import { cx } from '../../components/ui/cx'
import { Dialog } from '../../components/ui/Dialog'
import { Alert, EmptyState, ErrorState, LoadingBlock, useErrorMessage } from '../../components/ui/Feedback'
import { KeyValue, Panel, PanelHeader } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useEligibleChats } from '../../lib/queries'
import type { BindingStatus, LinkIntent, TelegramBinding, TelegramState, TelegramStatus } from '../../lib/types'

/** Confirmation for destructive actions; the action itself reports errors inline. */
export function ConfirmDialog({ open, onClose, title, body, confirmLabel, onConfirm, pending, error, children }: {
  open: boolean
  onClose: () => void
  title: string
  body?: string
  confirmLabel: string
  onConfirm: () => void
  pending: boolean
  error?: unknown
  children?: ReactNode
}) {
  const { t } = useI18n()
  const errorMessage = useErrorMessage()
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={body}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="danger" loading={pending} onClick={onConfirm}>{confirmLabel}</Button>
        </>
      }
    >
      {(children || error) ? (
        <div className="space-y-3">
          {error ? <Alert tone="danger" title={errorMessage(error)} /> : null}
          {children}
        </div>
      ) : null}
    </Dialog>
  )
}

// ---------------------------------------------------------------- progress
export function SetupSteps({ hasBaseline, connected, bound, monitoring }: {
  hasBaseline: boolean
  connected: boolean
  bound: boolean
  monitoring: boolean
}) {
  const { t } = useI18n()
  const steps = [
    { key: 'baseline', label: t('telegram.steps.baseline'), done: hasBaseline },
    { key: 'connect', label: t('telegram.steps.connect'), done: connected },
    { key: 'chat', label: t('telegram.steps.chat'), done: bound },
    { key: 'monitor', label: t('telegram.steps.monitor'), done: monitoring },
  ]
  const current = steps.findIndex((s) => !s.done)
  return (
    <ol aria-label={t('telegram.steps.label')} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {steps.map((s, i) => (
        <li
          key={s.key}
          aria-current={i === current ? 'step' : undefined}
          className={cx(
            'flex min-w-0 items-center gap-2 rounded-md border px-2.5 py-2 text-[13px]',
            s.done ? 'border-line bg-surface text-fg-muted' : i === current ? 'border-accent bg-accent-soft text-fg' : 'border-line bg-surface text-fg-subtle',
          )}
        >
          <span
            className={cx(
              'flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular',
              s.done ? 'bg-success text-fg-inverse' : i === current ? 'bg-accent text-fg-inverse' : 'bg-surface-muted text-fg-muted',
            )}
            aria-hidden
          >
            {s.done ? <Check size={12} /> : i + 1}
          </span>
          <span className="truncate">{s.label}</span>
          {s.done && <span className="sr-only">({t('telegram.steps.done')})</span>}
        </li>
      ))}
    </ol>
  )
}

// ---------------------------------------------------------------- connection
const stateTone: Record<TelegramState, BadgeTone> = {
  UNLINKED: 'neutral',
  LINK_PENDING: 'info',
  CONNECTED: 'success',
  ACCESS_REVOKED: 'warning',
  LINK_CONFLICT: 'danger',
}

export function ConnectionPanel({ workspaceId, status, manage }: { workspaceId: string; status: TelegramStatus; manage: boolean }) {
  const { t, formatDate } = useI18n()
  const qc = useQueryClient()
  const notify = useToast()
  const [intent, setIntent] = useState<LinkIntent | null>(null)
  const [confirm, setConfirm] = useState(false)
  const errorMessage = useErrorMessage()
  const bot = status.bot_username ?? ''

  const createLink = useMutation({
    mutationFn: () => api.post<LinkIntent>(`/workspaces/${workspaceId}/integrations/telegram/link-intents`),
    onSuccess: (data) => {
      setIntent(data)
      qc.invalidateQueries({ queryKey: qk.telegramStatus(workspaceId) })
    },
  })
  const disconnect = useMutation({
    mutationFn: () => api.post(`/workspaces/${workspaceId}/integrations/telegram/disconnect`),
    onSuccess: () => {
      setConfirm(false)
      setIntent(null)
      qc.invalidateQueries({ queryKey: ['telegram'] })
      notify(t('telegram.connection.disconnected'))
    },
  })

  const state = status.state
  const pending = status.pending_link
  const connection = status.connection
  const linkLive = intent && new Date(intent.expires_at).getTime() > Date.now() && !pending?.verified

  return (
    <Panel aria-labelledby="tg-connection">
      <PanelHeader
        id="tg-connection"
        title={t('telegram.connection.title')}
        description={t('telegram.connection.description')}
        actions={<StatusDot tone={stateTone[state]}>{t(`telegram.connection.state.${state}`)}</StatusDot>}
      />
      <div className="space-y-4 px-4 py-4">
        {(state === 'UNLINKED' || state === 'LINK_PENDING' || state === 'LINK_CONFLICT') && (
          <>
            {state === 'LINK_CONFLICT' && <Alert tone="danger" title={t('telegram.connection.conflictBody')} />}
            {pending?.verified ? (
              <Alert
                tone="success"
                title={t('telegram.connection.verified', {
                  user: pending.telegram_username ? ` (@${pending.telegram_username})` : '',
                  bot,
                })}
              />
            ) : null}
            <div>
              <h3 className="text-[13px] font-medium">{t('telegram.connection.howTitle')}</h3>
              <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-[13px] text-fg-muted marker:text-fg-subtle">
                <li className={cx(pending?.verified && 'line-through decoration-fg-subtle')}>{t('telegram.connection.how1')}</li>
                <li>{t('telegram.connection.how2', { bot })}</li>
                <li>{t('telegram.connection.how3')}</li>
              </ol>
              <p className="mt-2 text-xs text-fg-subtle">{t('telegram.connection.oneBotNote')}</p>
            </div>
            <PrivacyNote />
            {createLink.isError && <Alert tone="danger" title={errorMessage(createLink.error)} />}
            {manage && (
              <div className="flex flex-wrap items-center gap-2">
                {linkLive ? (
                  <>
                    <a
                      href={intent.deep_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3.5 text-sm font-medium text-fg-inverse hover:bg-accent-hover"
                    >
                      <ExternalLink size={16} aria-hidden />
                      {t('telegram.connection.openTelegram')}
                    </a>
                    <span className="text-xs text-fg-subtle">
                      {t('telegram.connection.linkExpires', { time: formatDate(intent.expires_at, true) })}
                    </span>
                  </>
                ) : !pending?.verified ? (
                  <Button variant="primary" icon={<MessageCircle size={16} aria-hidden />} loading={createLink.isPending}
                    onClick={() => createLink.mutate()}>
                    {state === 'UNLINKED' ? t('telegram.connection.connect') : t('telegram.connection.newLink')}
                  </Button>
                ) : null}
              </div>
            )}
            {linkLive && (
              <p role="status" className="text-[13px] text-fg-muted">{t('telegram.connection.waiting')}</p>
            )}
          </>
        )}

        {connection && (
          <>
            {state === 'ACCESS_REVOKED' && <Alert tone="warning" title={t('telegram.connection.revokedBody')} />}
            <KeyValue
              items={[
                { label: t('telegram.connection.account'), value: connection.telegram_username ? `@${connection.telegram_username}` : t('common.none') },
                {
                  label: t('telegram.connection.rights'),
                  value: connection.rights.length ? connection.rights.join(', ') : t('telegram.connection.noRights'),
                },
                { label: t('telegram.connection.linkedAt'), value: formatDate(connection.linked_at, true) },
                {
                  label: t('telegram.connection.lastEvent'),
                  value: connection.last_event_at ? formatDate(connection.last_event_at, true) : t('telegram.connection.never'),
                },
              ]}
            />
            {manage && (
              <Button variant="danger" size="sm" onClick={() => setConfirm(true)}>{t('telegram.connection.disconnect')}</Button>
            )}
          </>
        )}
      </div>
      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title={t('telegram.connection.disconnectTitle')}
        body={t('telegram.connection.disconnectBody')}
        confirmLabel={t('telegram.connection.disconnect')}
        onConfirm={() => disconnect.mutate()}
        pending={disconnect.isPending}
        error={disconnect.error}
      />
    </Panel>
  )
}

export function PrivacyNote() {
  const { t } = useI18n()
  return (
    <div className="flex gap-2.5 rounded-md bg-surface-muted px-3 py-2.5">
      <ShieldCheck size={16} className="mt-0.5 shrink-0 text-fg-muted" aria-hidden />
      <div>
        <p className="text-[13px] font-medium">{t('telegram.connection.privacyTitle')}</p>
        <p className="mt-0.5 text-[13px] text-fg-muted">{t('telegram.connection.privacyBody')}</p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- chat
export function ChatPanel({ workspaceId, projectId, binding, connected, manage }: {
  workspaceId: string
  projectId: string
  binding: TelegramBinding
  connected: boolean
  manage: boolean
}) {
  const { t, formatDate } = useI18n()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const [confirm, setConfirm] = useState(false)
  const bound = binding.binding_id !== null
  const chats = useEligibleChats(workspaceId, connected && !bound && manage)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: qk.telegramBinding(projectId) })
    qc.invalidateQueries({ queryKey: qk.telegramChats(workspaceId) })
  }
  const bind = useMutation({
    mutationFn: (chatId: number) => api.post<TelegramBinding>(`/projects/${projectId}/telegram/chat-binding`, { chat_id: chatId }),
    onSuccess: invalidate,
  })
  const unbind = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}/telegram/chat-binding`),
    onSuccess: () => {
      setConfirm(false)
      invalidate()
      notify(t('telegram.chat.unbound'))
    },
  })

  if (!connected && !bound) return null

  return (
    <Panel aria-labelledby="tg-chat">
      <PanelHeader id="tg-chat" title={t('telegram.chat.title')} description={t('telegram.chat.description')} />
      <div className="px-4 py-4">
        {bound ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-fg" aria-hidden>
                <MessageCircle size={16} />
              </span>
              <div className="min-w-0">
                <p className="truncate font-medium">{binding.display_name}</p>
                <p className="text-xs text-fg-subtle">{t('telegram.chat.selected')}</p>
              </div>
            </div>
            {manage && <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>{t('telegram.chat.unbind')}</Button>}
          </div>
        ) : !manage ? (
          <p className="text-[13px] text-fg-muted">{t('telegram.viewerNote')}</p>
        ) : chats.isPending ? (
          <LoadingBlock rows={2} />
        ) : chats.isError ? (
          <ErrorState error={chats.error} onRetry={() => chats.refetch()} />
        ) : chats.data.length === 0 ? (
          <EmptyState icon={<MessageCircle size={24} aria-hidden />} title={t('telegram.chat.emptyTitle')} body={t('telegram.chat.emptyBody')} />
        ) : (
          <>
            {bind.isError && <Alert tone="danger" className="mb-3" title={errorMessage(bind.error)} />}
            <ul className="divide-y divide-line rounded-md border border-line">
              {chats.data.map((c) => {
                const elsewhere = c.bound_project_id !== null && c.bound_project_id !== projectId
                return (
                  <li key={c.chat_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{c.display_name}</p>
                      <p className="text-xs text-fg-subtle">
                        {elsewhere ? t('telegram.chat.boundElsewhere') : t('telegram.chat.lastSeen', { date: formatDate(c.last_seen_at, true) })}
                      </p>
                    </div>
                    <Button size="sm" disabled={elsewhere} loading={bind.isPending && bind.variables === c.chat_id}
                      onClick={() => bind.mutate(c.chat_id)}>
                      {t('telegram.chat.select')}
                    </Button>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </div>
      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title={t('telegram.chat.unbindTitle')}
        body={t('telegram.chat.unbindBody')}
        confirmLabel={t('telegram.chat.unbind')}
        onConfirm={() => unbind.mutate()}
        pending={unbind.isPending}
        error={unbind.error}
      />
    </Panel>
  )
}

// ---------------------------------------------------------------- monitoring
const bindingTone: Record<BindingStatus, BadgeTone> = {
  UNBOUND: 'neutral',
  AWAITING_CHAT: 'neutral',
  NEEDS_BASELINE: 'warning',
  READY: 'info',
  MONITORING: 'success',
  PAUSED: 'warning',
}

export function MonitoringPanel({ projectId, binding, manage }: { projectId: string; binding: TelegramBinding; manage: boolean }) {
  const { t, formatDate } = useI18n()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const [consent, setConsent] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const s = binding.settings
  const minutes = (sec: number) => Math.max(1, Math.round(sec / 60))

  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      api.patch<TelegramBinding>(`/projects/${projectId}/telegram/monitoring`, {
        enabled, privacy_acknowledged: consent, expected_version: binding.version,
      }),
    onSuccess: (data) => {
      qc.setQueryData(qk.telegramBinding(projectId), data)
      setConsent(false)
      notify(data.monitoring_enabled ? t('telegram.monitoring.started') : t('telegram.monitoring.paused'))
    },
  })
  const purge = useMutation({
    mutationFn: () => api.delete<{ messages_purged: number }>(`/projects/${projectId}/telegram/data`),
    onSuccess: (data) => {
      setConfirmDelete(false)
      qc.invalidateQueries({ queryKey: ['signals', projectId] })
      qc.invalidateQueries({ queryKey: qk.telegramBinding(projectId) })
      notify(t('telegram.monitoring.deleted', { n: data.messages_purged }))
    },
  })

  if (binding.binding_id === null) return null
  const lb = binding.last_batch
  const batchTime = lb ? (lb.state === 'OPEN' ? lb.quiet_until : (lb.processed_at ?? lb.last_message_at)) : null

  return (
    <Panel aria-labelledby="tg-monitoring">
      <PanelHeader
        id="tg-monitoring"
        title={t('telegram.monitoring.title')}
        actions={<StatusDot tone={bindingTone[binding.status]}>{t(`telegram.monitoring.status.${binding.status}`)}</StatusDot>}
      />
      <div className="space-y-4 px-4 py-4">
        {binding.status === 'NEEDS_BASELINE' && (
          <Alert tone="warning" title={t('telegram.monitoring.needsBaseline')}
            action={<ButtonLink size="sm" to={`/projects/${projectId}/scope`}>{t('telegram.monitoring.goToScope')}</ButtonLink>} />
        )}
        {binding.status === 'PAUSED' && <Alert tone="warning" title={t('telegram.monitoring.pausedBody')} />}
        {toggle.isError && <Alert tone="danger" title={errorMessage(toggle.error)} />}

        <div>
          <h3 className="text-[13px] font-medium">{t('telegram.monitoring.rulesTitle')}</h3>
          <ul className="mt-2 space-y-1.5 text-[13px] text-fg-muted">
            {[
              s.message_debounce_seconds < 60
                ? t('telegram.monitoring.rules.debounceSeconds', { n: s.message_debounce_seconds })
                : t('telegram.monitoring.rules.debounce', { n: minutes(s.message_debounce_seconds) }),
              t('telegram.monitoring.rules.cap', { n: minutes(s.max_batch_window_seconds) }),
              t('telegram.monitoring.rules.dedupe'),
              t('telegram.monitoring.rules.drafts'),
              t('telegram.monitoring.rules.attachments'),
            ].map((rule) => (
              <li key={rule} className="flex gap-2">
                <Check size={14} className="mt-0.5 shrink-0 text-success" aria-hidden />
                <span>{rule}</span>
              </li>
            ))}
          </ul>
        </div>

        {lb && batchTime && (
          <p className="text-[13px] text-fg-muted">
            <span className="font-medium text-fg">{t('telegram.monitoring.lastBatch')}:</span>{' '}
            {t(`telegram.monitoring.batch.${lb.state}`, { time: formatDate(batchTime, true) })}
            {' · '}
            <span className="tabular">{t('telegram.monitoring.messages', { n: lb.message_count })}</span>
          </p>
        )}

        {manage && !binding.monitoring_enabled && binding.has_approved_baseline && binding.status !== 'PAUSED' && (
          <div className="space-y-3 border-t border-line pt-4">
            <PrivacyNote />
            <label className="flex items-start gap-2.5 text-[13px]">
              <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-(--tr-accent)" checked={consent}
                onChange={(e) => setConsent(e.target.checked)} />
              <span>{t('telegram.monitoring.consent')}</span>
            </label>
            <Button variant="primary" disabled={!consent} loading={toggle.isPending} onClick={() => toggle.mutate(true)}>
              {t('telegram.monitoring.start')}
            </Button>
          </div>
        )}

        {manage && (
          <div className="flex flex-wrap gap-2 border-t border-line pt-4">
            {binding.monitoring_enabled && (
              <Button size="sm" loading={toggle.isPending} onClick={() => toggle.mutate(false)}>{t('telegram.monitoring.pause')}</Button>
            )}
            <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>{t('telegram.monitoring.deleteData')}</Button>
          </div>
        )}
      </div>
      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t('telegram.monitoring.deleteTitle')}
        body={t('telegram.monitoring.deleteBody')}
        confirmLabel={t('telegram.monitoring.deleteData')}
        onConfirm={() => purge.mutate()}
        pending={purge.isPending}
        error={purge.error}
      />
    </Panel>
  )
}
