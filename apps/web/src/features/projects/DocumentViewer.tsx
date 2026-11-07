import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { useAnchorLabel } from '../../components/domain'
import { cx } from '../../components/ui/cx'
import { EmptyState, ErrorState, LoadingBlock } from '../../components/ui/Feedback'
import { Panel, PanelHeader } from '../../components/ui/Layout'
import { api } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { useScope, useSpans } from '../../lib/queries'
import type { DocumentVersion } from '../../lib/types'
import { useProjectContext } from './ProjectLayout'

/** Shows the exact extracted fragments of a document; `?span=` scrolls to and highlights a citation. */
export function DocumentViewer() {
  const { docId = '' } = useParams()
  const [params] = useSearchParams()
  const focusSpan = params.get('span')
  const { project: p } = useProjectContext()
  const { t } = useI18n()
  const anchorLabel = useAnchorLabel()
  const doc = useQuery({ queryKey: ['document', docId], queryFn: () => api.get<DocumentVersion>(`/documents/${docId}`) })
  const spans = useSpans(docId)
  const scope = useScope(p.id)
  const focusRef = useRef<HTMLLIElement>(null)

  const current = scope.data?.current
  const draft = scope.data?.draft
  const cited = useMemo(() => {
    const ids = new Set<string>()
    for (const b of [current, draft]) b?.items.forEach((i) => i.evidence.forEach((e) => ids.add(e.span_id)))
    return ids
  }, [current, draft])

  // Page dividers and section headings are shown where they change from the previous fragment.
  const rows = useMemo(
    () =>
      (spans.data ?? []).map((s, i, all) => {
        const prev = i > 0 ? all[i - 1] : undefined
        return {
          span: s,
          showPage: s.page !== null && s.page !== prev?.page,
          showHeading: Boolean(s.heading) && s.heading !== prev?.heading && s.normalized_text.replace(/:$/, '') !== s.heading,
        }
      }),
    [spans.data],
  )

  useEffect(() => {
    if (focusSpan && spans.data) focusRef.current?.scrollIntoView({ block: 'center' })
  }, [focusSpan, spans.data])

  if (doc.isError) return <ErrorState error={doc.error} onRetry={() => doc.refetch()} />

  return (
    <Panel>
      <PanelHeader
        title={doc.data ? `${doc.data.title} · ${t('common.version', { n: doc.data.version })}` : t('documents.viewer.title')}
        description={t('documents.viewer.intro')}
        actions={
          <Link to={`/projects/${p.id}/documents`} className="inline-flex items-center gap-1 text-[13px] font-medium text-accent-fg hover:underline">
            <ArrowLeft size={14} aria-hidden />{t('projects.tabs.documents')}
          </Link>
        }
      />
      {spans.isPending ? (
        <div className="p-4"><LoadingBlock rows={6} /></div>
      ) : spans.isError ? (
        <div className="p-4"><ErrorState error={spans.error} onRetry={() => spans.refetch()} /></div>
      ) : spans.data.length === 0 ? (
        <div className="p-4"><EmptyState title={t('documents.viewer.empty')} /></div>
      ) : (
        <ol className="mx-auto max-w-3xl space-y-1 px-4 py-5">
          {rows.map(({ span: s, showPage, showHeading }) => {
            const isFocus = s.id === focusSpan
            const isCited = cited.has(s.id)
            return (
              <li key={s.id} ref={isFocus ? focusRef : undefined} id={`span-${s.id}`} className="scroll-mt-24">
                {showPage && (
                  <div className="mb-2 mt-4 flex items-center gap-2 text-xs font-medium text-fg-subtle first:mt-0">
                    {anchorLabel(s)}<span className="h-px flex-1 bg-line" />
                  </div>
                )}
                {showHeading && <p className="mt-3 text-xs font-semibold tracking-wide text-fg-muted uppercase">{s.heading}</p>}
                <div
                  className={cx(
                    'group flex gap-3 rounded-md px-2 py-1.5',
                    isFocus ? 'bg-highlight ring-2 ring-accent' : isCited ? 'bg-accent-soft' : 'hover:bg-surface-muted',
                  )}
                >
                  <p className="min-w-0 flex-1 leading-relaxed whitespace-pre-line">{s.exact_quote}</p>
                  <span className="hidden shrink-0 pt-0.5 text-[11px] text-fg-subtle tabular sm:block">
                    {s.anchor_type === 'PDF_PAGE' ? `${s.char_start}–${s.char_end}` : anchorLabel(s)}
                  </span>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </Panel>
  )
}
