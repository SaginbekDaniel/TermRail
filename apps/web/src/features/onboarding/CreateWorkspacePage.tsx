import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'
import { StandalonePage } from '../../components/layout/StandalonePage'
import { Button } from '../../components/ui/Button'
import { Alert, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input } from '../../components/ui/Field'
import { api } from '../../lib/api'
import { useI18n, type MessageKey } from '../../lib/i18n'
import { useSession } from '../../lib/session'
import type { Workspace } from '../../lib/types'

const STEPS: MessageKey[] = [
  'onboarding.steps.project',
  'onboarding.steps.upload',
  'onboarding.steps.scope',
  'onboarding.steps.request',
  'onboarding.steps.order',
]

export function CreateWorkspacePage() {
  const { t } = useI18n()
  const { me, refresh, selectWorkspace, logout } = useSession()
  const errorMessage = useErrorMessage()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (me && me.workspaces.length > 0) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      const ws = await api.post<Workspace>('/workspaces', { name: name.trim() })
      selectWorkspace(ws.id)
      await refresh()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <StandalonePage width="lg">
      <div className="grid gap-8 md:grid-cols-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t('onboarding.title')}</h1>
          <p className="mt-1 text-fg-muted">{t('onboarding.subtitle')}</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            {error && <Alert tone="danger" title={error} />}
            <Field label={t('onboarding.workspaceName')}>
              {(p) => (
                <Input {...p} required maxLength={200} placeholder={t('onboarding.workspacePlaceholder')} value={name}
                  onChange={(e) => setName(e.target.value)} />
              )}
            </Field>
            <div className="flex items-center gap-2">
              <Button type="submit" variant="primary" loading={busy} disabled={!name.trim()}>{t('onboarding.create')}</Button>
              <Button variant="ghost" onClick={logout}>{t('nav.signOut')}</Button>
            </div>
          </form>
        </div>
        <section className="rounded-lg border border-line bg-surface p-5" aria-labelledby="how">
          <h2 id="how" className="text-[15px] font-semibold">{t('onboarding.stepsTitle')}</h2>
          <ol className="mt-3 space-y-3">
            {STEPS.map((key, i) => (
              <li key={key} className="flex gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-fg tabular">{i + 1}</span>
                <span className="pt-0.5 text-fg-muted">{t(key)}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </StandalonePage>
  )
}
