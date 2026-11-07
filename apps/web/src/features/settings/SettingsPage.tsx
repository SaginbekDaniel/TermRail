import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, XCircle } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Alert, ErrorState, LoadingBlock, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input, Select } from '../../components/ui/Field'
import { KeyValue, PageHeader, Panel, PanelHeader, Segmented } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api } from '../../lib/api'
import { LANGUAGE_NAMES, LOCALES, useI18n, type Locale } from '../../lib/i18n'
import { qk, useAiStatus, useMembers } from '../../lib/queries'
import { useSession, useWorkspace } from '../../lib/session'
import { useTheme, type ThemePref } from '../../lib/theme'
import type { Role } from '../../lib/types'

const ASSIGNABLE: Exclude<Role, 'OWNER'>[] = ['MANAGER', 'MEMBER', 'VIEWER']

function Members() {
  const { t } = useI18n()
  const ws = useWorkspace()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const members = useMembers(ws.id)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Exclude<Role, 'OWNER'>>('MANAGER')
  const add = useMutation({
    mutationFn: () => api.post(`/workspaces/${ws.id}/members`, { email, role }),
    onSuccess: () => {
      setEmail('')
      notify(t('settings.memberAdded'))
      qc.invalidateQueries({ queryKey: qk.members(ws.id) })
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate()
  }

  return (
    <Panel>
      <PanelHeader title={t('settings.members')} />
      {members.isPending ? (
        <div className="p-4"><LoadingBlock rows={2} /></div>
      ) : members.isError ? (
        <div className="p-4"><ErrorState error={members.error} onRetry={() => members.refetch()} /></div>
      ) : (
        <ul className="divide-y divide-line">
          {members.data.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
              <span className="min-w-0">
                <span className="block truncate font-medium">{m.display_name || m.email}</span>
                <span className="block truncate text-[13px] text-fg-muted">{m.email}</span>
              </span>
              <Badge tone={m.role === 'OWNER' ? 'accent' : 'neutral'} title={t(`settings.roleHints.${m.role}`)}>{t(`settings.roles.${m.role}`)}</Badge>
            </li>
          ))}
        </ul>
      )}
      {ws.role === 'OWNER' && (
        <form onSubmit={submit} className="space-y-3 border-t border-line p-4">
          <h3 className="text-[13px] font-semibold">{t('settings.addMember')}</h3>
          {add.isError && <Alert tone="danger" title={errorMessage(add.error)} />}
          <div className="grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
            <Field label={t('auth.email')}>
              {(p) => <Input {...p} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
            </Field>
            <Field label={t('settings.role')}>
              {(p) => (
                <Select {...p} value={role} onChange={(e) => setRole(e.target.value as Exclude<Role, 'OWNER'>)}>
                  {ASSIGNABLE.map((r) => <option key={r} value={r}>{t(`settings.roles.${r}`)}</option>)}
                </Select>
              )}
            </Field>
            <Button type="submit" variant="primary" loading={add.isPending} disabled={!email}>{t('common.add')}</Button>
          </div>
          <p className="text-[13px] text-fg-subtle">{t(`settings.roleHints.${role}`)} · {t('settings.addMemberHint')}</p>
        </form>
      )}
    </Panel>
  )
}

function AiConnection() {
  const { t } = useI18n()
  const ai = useAiStatus()
  return (
    <Panel>
      <PanelHeader title={t('settings.ai')} />
      <div className="space-y-4 p-4">
        {ai.isPending ? (
          <LoadingBlock rows={2} />
        ) : ai.isError ? (
          <ErrorState error={ai.error} onRetry={() => ai.refetch()} />
        ) : (
          <>
            <KeyValue
              items={[
                {
                  label: t('settings.ai'),
                  value: ai.data.configured ? (
                    <span className="inline-flex items-center gap-1.5 text-success"><CheckCircle2 size={15} aria-hidden />{t('settings.aiConfigured')}</span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-danger"><XCircle size={15} aria-hidden />{t('settings.aiNotConfigured')}</span>
                  ),
                },
                { label: t('settings.provider'), value: ai.data.provider },
                { label: t('settings.model'), value: ai.data.model ?? '—' },
              ]}
            />
            {!ai.data.configured && <Alert tone="warning">{t('settings.aiNotConfiguredHint')}</Alert>}
            <div>
              <h3 className="text-[13px] font-semibold">{t('settings.dataNotice')}</h3>
              <p className="mt-1 text-[13px] text-fg-muted">{ai.data.data_notice}</p>
            </div>
          </>
        )}
      </div>
    </Panel>
  )
}

export function SettingsPage() {
  const { t, locale, setLocale } = useI18n()
  const { me } = useSession()
  const ws = useWorkspace()
  const [theme, setTheme] = useTheme()

  return (
    <>
      <PageHeader title={t('settings.title')} subtitle={`${t('settings.workspace')}: ${ws.name}`} />
      <div className="grid gap-5 lg:grid-cols-2 lg:items-start">
        <div className="space-y-5">
          <Members />
          <Panel>
            <PanelHeader title={t('settings.privacy')} />
            <p className="p-4 text-[13px] text-fg-muted">{t('settings.privacyBody')}</p>
          </Panel>
        </div>
        <div className="space-y-5">
          <AiConnection />
          <Panel>
            <PanelHeader title={t('settings.preferences')} />
            <div className="space-y-4 p-4">
              <Field label={t('settings.language')}>
                {(p) => (
                  <Select {...p} value={locale} onChange={(e) => setLocale(e.target.value as Locale)} className="max-w-xs">
                    {LOCALES.map((l) => <option key={l} value={l}>{LANGUAGE_NAMES[l]}</option>)}
                  </Select>
                )}
              </Field>
              <div className="max-w-xs space-y-1.5">
                <p className="text-[13px] font-medium">{t('settings.theme')}</p>
                <Segmented<ThemePref>
                  label={t('settings.theme')}
                  value={theme}
                  onChange={setTheme}
                  options={(['system', 'light', 'dark'] as const).map((v) => ({ value: v, label: t(`settings.themes.${v}`) }))}
                />
              </div>
              <p className="border-t border-line pt-3 text-[13px] text-fg-muted">{t('settings.signedInAs', { email: me?.user.email ?? '' })}</p>
            </div>
          </Panel>
        </div>
      </div>
    </>
  )
}
