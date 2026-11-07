import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, FileText, Upload } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router'
import { ParseStatusBadge } from '../../components/domain'
import { Button } from '../../components/ui/Button'
import { cx } from '../../components/ui/cx'
import { Alert, EmptyState, ErrorState, LoadingBlock, useErrorMessage } from '../../components/ui/Feedback'
import { Panel, PanelHeader } from '../../components/ui/Layout'
import { useToast } from '../../components/ui/Toast'
import { api, downloadFile } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { qk, useDocuments } from '../../lib/queries'
import type { DocumentVersion } from '../../lib/types'
import { useProjectContext } from './ProjectLayout'

const MAX_MB = 15

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function DocumentRow({ d, projectId }: { d: DocumentVersion; projectId: string }) {
  const { t, td, formatDate } = useI18n()
  const errorMessage = useErrorMessage()
  const notify = useToast()
  const issues = d.quality.issues ?? []
  return (
    <li className="px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <FileText size={18} className="mt-0.5 shrink-0 text-fg-subtle" aria-hidden />
          <div className="min-w-0">
            <p className="truncate font-medium">
              {d.title} <span className="font-normal text-fg-subtle">· {t('common.version', { n: d.version })}</span>
            </p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-fg-muted">
              <ParseStatusBadge status={d.parse_status} />
              <span>{formatBytes(d.bytes)}</span>
              {d.page_count !== null && <span>{t('documents.pages', { n: d.page_count })}</span>}
              {d.parse_status === 'PARSED' && <span>{t('documents.fragments', { n: d.span_count })}</span>}
              <span>{formatDate(d.created_at, true)}</span>
            </p>
            <p className="mt-1 truncate font-mono text-[11px] text-fg-subtle" title={d.sha256}>{t('documents.sha')} {d.sha256.slice(0, 16)}…</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {d.span_count > 0 && (
            <Link to={`/projects/${projectId}/documents/${d.id}`} className="inline-flex h-8 items-center rounded-md px-2.5 text-[13px] font-medium text-accent-fg hover:bg-accent-soft">
              {t('documents.viewText')}
            </Link>
          )}
          <Button
            size="sm"
            variant="ghost"
            icon={<Download size={14} aria-hidden />}
            onClick={() => downloadFile(`/documents/${d.id}/file`, d.original_name).catch((e) => notify(errorMessage(e), 'danger'))}
          >
            <span className="sr-only sm:not-sr-only">{t('documents.downloadOriginal')}</span>
          </Button>
        </div>
      </div>
      {issues.length > 0 && (
        <Alert tone="warning" className="mt-3">
          {issues.map((i) => <p key={i}>{td(`documents.issues.${i}`, i)}</p>)}
        </Alert>
      )}
      {d.parse_status === 'FAILED' && (
        <Alert tone="danger" className="mt-3" title={td(`documents.parseErrors.${d.parse_error ?? ''}`, t('errors.generic'))} />
      )}
    </li>
  )
}

export function DocumentsTab() {
  const { project: p, manage } = useProjectContext()
  const { t } = useI18n()
  const qc = useQueryClient()
  const notify = useToast()
  const errorMessage = useErrorMessage()
  const docs = useDocuments(p.id)
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.upload<{ document: DocumentVersion; duplicate: boolean }>(`/projects/${p.id}/documents`, form)
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: qk.documents(p.id) })
      qc.invalidateQueries({ queryKey: qk.project(p.id) })
      notify(res.duplicate ? t('documents.duplicate', { n: res.document.version }) : t('documents.uploaded'))
    },
    onError: (e) => notify(errorMessage(e), 'danger'),
  })

  const pick = (files: FileList | null) => {
    const f = files?.[0]
    if (!f) return
    if (f.size > MAX_MB * 1024 * 1024) {
      notify(t('errors.PAYLOAD_TOO_LARGE'), 'danger')
      return
    }
    upload.mutate(f)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files)
  }

  return (
    <div className="space-y-5">
      {manage && (
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            'flex flex-col items-center gap-3 rounded-lg border border-dashed px-4 py-6 text-center transition-colors sm:flex-row sm:justify-between sm:text-left',
            dragging ? 'border-accent bg-accent-soft' : 'border-line-strong bg-surface',
          )}
        >
          <div>
            <p className="font-medium">{t('documents.dropHint')}</p>
            <p className="mt-0.5 text-[13px] text-fg-muted">{t('documents.formats', { mb: MAX_MB })}</p>
          </div>
          <input
            ref={inputRef}
            type="file"
            className="sr-only"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(e) => {
              pick(e.target.files)
              e.target.value = ''
            }}
            aria-label={t('documents.upload')}
          />
          <Button variant="primary" icon={<Upload size={16} aria-hidden />} loading={upload.isPending} onClick={() => inputRef.current?.click()}>
            {upload.isPending ? t('documents.uploading') : t('documents.upload')}
          </Button>
        </div>
      )}

      <Panel>
        <PanelHeader title={t('documents.title')} description={t('documents.subtitle')} />
        {docs.isPending ? (
          <div className="p-4"><LoadingBlock /></div>
        ) : docs.isError ? (
          <div className="p-4"><ErrorState error={docs.error} onRetry={() => docs.refetch()} /></div>
        ) : docs.data.length === 0 ? (
          <div className="p-4"><EmptyState title={t('documents.emptyTitle')} body={t('documents.emptyBody')} /></div>
        ) : (
          <ul className="divide-y divide-line">
            {docs.data.map((d) => <DocumentRow key={d.id} d={d} projectId={p.id} />)}
          </ul>
        )}
      </Panel>
    </div>
  )
}
