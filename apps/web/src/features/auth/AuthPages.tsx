import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { StandalonePage } from '../../components/layout/StandalonePage'
import { Button } from '../../components/ui/Button'
import { Alert, useErrorMessage } from '../../components/ui/Feedback'
import { Field, Input } from '../../components/ui/Field'
import { useI18n } from '../../lib/i18n'
import { useSession } from '../../lib/session'

function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode }) {
  return (
    <StandalonePage>
      <div className="rounded-lg border border-line bg-surface p-6 sm:p-7">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1.5 text-fg-muted">{subtitle}</p>
        <div className="mt-6">{children}</div>
      </div>
      <p className="mt-5 text-center text-fg-muted">{footer}</p>
    </StandalonePage>
  )
}

export function LoginPage() {
  const { t } = useI18n()
  const { login, status, expired } = useSession()
  const location = useLocation()
  const errorMessage = useErrorMessage()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status !== 'anonymous') {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from ?? '/'} replace />
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title={t('auth.signInTitle')}
      subtitle={t('auth.signInSubtitle')}
      footer={<>{t('auth.noAccount')} <Link to="/register" className="font-medium text-accent-fg hover:underline">{t('auth.createAccount')}</Link></>}
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {expired && !error && <Alert tone="warning" title={t('auth.sessionExpired')} />}
        {error && <Alert tone="danger" title={error} />}
        <Field label={t('auth.email')}>
          {(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label={t('auth.password')}>
          {(p) => <Input {...p} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>{t('auth.signIn')}</Button>
      </form>
    </AuthLayout>
  )
}

export function RegisterPage() {
  const { t } = useI18n()
  const { register, status } = useSession()
  const errorMessage = useErrorMessage()
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status !== 'anonymous') return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (form.password.length < 10) {
      setError(t('errors.WEAK_PASSWORD'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await register(form.email, form.password, form.name)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      title={t('auth.registerTitle')}
      subtitle={t('auth.registerSubtitle')}
      footer={<>{t('auth.haveAccount')} <Link to="/login" className="font-medium text-accent-fg hover:underline">{t('auth.signIn')}</Link></>}
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && <Alert tone="danger" title={error} />}
        <Field label={t('auth.displayName')}>
          {(p) => <Input {...p} autoComplete="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}
        </Field>
        <Field label={t('auth.email')}>
          {(p) => <Input {...p} type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />}
        </Field>
        <Field label={t('auth.password')} hint={t('auth.passwordHint')}>
          {(p) => <Input {...p} type="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />}
        </Field>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>{t('auth.createAccount')}</Button>
      </form>
    </AuthLayout>
  )
}
