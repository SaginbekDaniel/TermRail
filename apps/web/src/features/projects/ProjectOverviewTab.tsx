import { CheckCircle2, Circle, CircleDot } from 'lucide-react'
import type { ReactNode } from 'react'
import { ButtonLink } from '../../components/ui/Button'
import { cx } from '../../components/ui/cx'
import { KeyValue, Panel, PanelHeader } from '../../components/ui/Layout'
import { useI18n, type MessageKey } from '../../lib/i18n'
import { useDocuments } from '../../lib/queries'
import { useProjectContext } from './ProjectLayout'

type StepState = 'done' | 'current' | 'todo'

export function ProjectOverviewTab() {
  const { project: p } = useProjectContext()
  const { t, formatMoney } = useI18n()
  const docs = useDocuments(p.id)
  const base = `/projects/${p.id}`

  const hasDocs = p.documents > 0
  const parsing = docs.data?.some((d) => d.parse_status === 'PENDING' || d.parse_status === 'PARSING') ?? false
  const hasBaseline = p.baseline_version !== null

  let next: { key: MessageKey; to: string; cta: MessageKey }
  if (!hasDocs) next = { key: 'projects.next.upload', to: `${base}/documents`, cta: 'documents.upload' }
  else if (parsing) next = { key: 'projects.next.parsing', to: `${base}/documents`, cta: 'projects.tabs.documents' }
  else if (!hasBaseline && !p.has_draft) next = { key: 'projects.next.extract', to: `${base}/scope`, cta: 'projects.tabs.scope' }
  else if (!hasBaseline) next = { key: 'projects.next.approve', to: `${base}/scope`, cta: 'projects.tabs.scope' }
  else if (p.open_reviews > 0) next = { key: 'projects.next.review', to: `${base}/requests`, cta: 'projects.tabs.requests' }
  else if (p.requests === 0) next = { key: 'projects.next.request', to: `${base}/requests?new=1`, cta: 'requests.new' }
  else next = { key: 'projects.next.done', to: `${base}/requests?new=1`, cta: 'requests.new' }

  const steps: { label: MessageKey; state: StepState }[] = [
    { label: 'onboarding.steps.upload', state: hasDocs ? 'done' : 'current' },
    { label: 'onboarding.steps.scope', state: hasBaseline ? 'done' : hasDocs ? 'current' : 'todo' },
    { label: 'onboarding.steps.request', state: p.requests > 0 ? 'done' : hasBaseline ? 'current' : 'todo' },
    { label: 'onboarding.steps.order', state: p.requests > 0 && p.open_reviews === 0 ? 'current' : 'todo' },
  ]
  const icon: Record<StepState, ReactNode> = {
    done: <CheckCircle2 size={18} className="text-success" aria-hidden />,
    current: <CircleDot size={18} className="text-accent" aria-hidden />,
    todo: <Circle size={18} className="text-fg-subtle" aria-hidden />,
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <Panel>
        <PanelHeader title={t('projects.next.title')} />
        <div className="space-y-4 p-4">
          <p className="text-[15px]">{t(next.key)}</p>
          <ButtonLink to={next.to} variant="primary">{t(next.cta)}</ButtonLink>
          <ol className="space-y-2.5 border-t border-line pt-4">
            {steps.map((s) => (
              <li key={s.label} className="flex items-start gap-2.5">
                <span className="mt-px">{icon[s.state]}</span>
                <span className={cx(s.state === 'todo' ? 'text-fg-subtle' : 'text-fg', s.state === 'current' && 'font-medium')}>{t(s.label)}</span>
              </li>
            ))}
          </ol>
        </div>
      </Panel>
      <Panel>
        <PanelHeader title={t('common.details')} />
        <div className="p-4">
          <KeyValue
            items={[
              { label: t('projects.client'), value: p.client_name },
              { label: t('projects.contractValue'), value: p.budget ? formatMoney(p.budget, p.currency) : t('projects.notSet') },
              { label: t('projects.form.currency'), value: p.currency },
              { label: t('projects.baseline'), value: p.baseline_version ? t('projects.baselineVersion', { n: p.baseline_version }) : t('projects.noBaseline') },
              { label: t('projects.documents'), value: p.documents },
              { label: t('projects.requests'), value: p.requests },
            ]}
          />
          {p.description && <p className="mt-4 whitespace-pre-line border-t border-line pt-4 text-fg-muted">{p.description}</p>}
        </div>
      </Panel>
    </div>
  )
}
