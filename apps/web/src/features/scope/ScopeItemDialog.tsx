import { Search } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useAnchorLabel } from '../../components/domain'
import { Button } from '../../components/ui/Button'
import { cx } from '../../components/ui/cx'
import { Alert, LoadingBlock } from '../../components/ui/Feedback'
import { Field, Input, Select, Textarea } from '../../components/ui/Field'
import { Dialog } from '../../components/ui/Dialog'
import { useI18n } from '../../lib/i18n'
import { useDocuments, useSpans } from '../../lib/queries'
import type { EvidenceRef, InclusionType, SourceSpan } from '../../lib/types'

export interface DraftItem {
  key: string
  id?: string
  title: string
  description: string
  inclusion_type: InclusionType
  acceptance_criteria: string
  evidence: EvidenceRef[]
  accepted: boolean
  origin: 'AI_CANDIDATE' | 'MANUAL'
}

const TYPES: InclusionType[] = ['INCLUDED', 'EXCLUDED', 'CONDITION']

function toEvidence(span: SourceSpan, docTitle: string, docVersion: number): EvidenceRef {
  return {
    span_id: span.id,
    document_version_id: span.document_version_id,
    document_title: docTitle,
    document_version: docVersion,
    anchor_type: span.anchor_type,
    page: span.page,
    paragraph_index: span.paragraph_index,
    table_ref: span.table_ref,
    text: span.normalized_text,
  }
}

export function ScopeItemDialog({ open, projectId, initial, onClose, onSave }: {
  open: boolean
  projectId: string
  initial: DraftItem
  onClose: () => void
  onSave: (item: DraftItem) => void
}) {
  const { t } = useI18n()
  const anchorLabel = useAnchorLabel()
  const docs = useDocuments(projectId)
  const parsedDocs = useMemo(() => docs.data?.filter((d) => d.parse_status === 'PARSED') ?? [], [docs.data])
  // The dialog is mounted once per edit session (see ScopeTab), so state starts from `initial`.
  const [item, setItem] = useState<DraftItem>(initial)
  const [docId, setDocId] = useState<string | null>(initial.evidence[0]?.document_version_id ?? null)
  const [query, setQuery] = useState('')
  const [showError, setShowError] = useState(false)

  const activeDoc = parsedDocs.find((d) => d.id === docId) ?? parsedDocs[0] ?? null
  const spans = useSpans(activeDoc?.id ?? null)
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (spans.data ?? []).filter((s) => !q || s.normalized_text.toLowerCase().includes(q))
  }, [spans.data, query])

  const selected = new Set(item.evidence.map((e) => e.span_id))

  const toggle = (span: SourceSpan) => {
    if (!activeDoc) return
    setItem({
      ...item,
      evidence: selected.has(span.id)
        ? item.evidence.filter((e) => e.span_id !== span.id)
        : [...item.evidence, toEvidence(span, activeDoc.title, activeDoc.version)],
    })
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!item.title.trim() || item.evidence.length === 0) {
      setShowError(true)
      return
    }
    onSave({ ...item, title: item.title.trim(), accepted: true })
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={initial.id || initial.title ? t('scope.form.editTitle') : t('scope.form.addTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" form="scope-item" variant="primary">{t('common.save')}</Button>
        </>
      }
    >
      <form id="scope-item" onSubmit={submit} className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="space-y-4">
          <Field label={t('scope.form.title')} error={showError && !item.title.trim() ? t('errors.TITLE_REQUIRED') : null}>
            {(p) => <Input {...p} maxLength={300} value={item.title} onChange={(e) => setItem({ ...item, title: e.target.value })} />}
          </Field>
          <Field label={t('scope.form.type')} hint={t(`scope.typeHints.${item.inclusion_type}`)}>
            {(p) => (
              <Select {...p} value={item.inclusion_type} onChange={(e) => setItem({ ...item, inclusion_type: e.target.value as InclusionType })}>
                {TYPES.map((ty) => <option key={ty} value={ty}>{t(`scope.types.${ty}`)}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('scope.form.description')} optional>
            {(p) => <Textarea {...p} rows={3} value={item.description} onChange={(e) => setItem({ ...item, description: e.target.value })} />}
          </Field>
          <Field label={t('scope.form.acceptance')} optional>
            {(p) => <Textarea {...p} rows={2} value={item.acceptance_criteria} onChange={(e) => setItem({ ...item, acceptance_criteria: e.target.value })} />}
          </Field>
        </div>

        <fieldset className="min-w-0 space-y-2.5">
          <legend className="text-[13px] font-medium">{t('scope.sources')}</legend>
          {showError && item.evidence.length === 0 && <Alert tone="danger" title={t('scope.form.sourcesRequired')} />}
          <div className="flex gap-2">
            {parsedDocs.length > 1 && (
              <Select aria-label={t('projects.tabs.documents')} value={activeDoc?.id ?? ''} onChange={(e) => setDocId(e.target.value)} className="max-w-[45%]">
                {parsedDocs.map((d) => <option key={d.id} value={d.id}>{d.title} ({t('common.version', { n: d.version })})</option>)}
              </Select>
            )}
            <div className="relative flex-1">
              <Search size={15} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
              <Input aria-label={t('scope.form.searchFragments')} placeholder={t('scope.form.searchFragments')} className="pl-8" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
          <div className="max-h-80 overflow-y-auto rounded-md border border-line">
            {spans.isPending && activeDoc ? (
              <div className="p-3"><LoadingBlock rows={3} /></div>
            ) : (
              <ul className="divide-y divide-line">
                {filtered.map((s) => {
                  const on = selected.has(s.id)
                  return (
                    <li key={s.id}>
                      <label className={cx('flex cursor-pointer gap-2.5 px-3 py-2 text-[13px]', on ? 'bg-accent-soft' : 'hover:bg-surface-muted')}>
                        <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-(--sl-accent)" checked={on} onChange={() => toggle(s)} />
                        <span className="min-w-0">
                          <span className="block leading-snug">{s.normalized_text}</span>
                          <span className="text-xs text-fg-subtle">{anchorLabel(s)}</span>
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
          <p className="text-xs text-fg-subtle">{t('scope.form.sourcesRequired')}</p>
        </fieldset>
      </form>
    </Dialog>
  )
}
