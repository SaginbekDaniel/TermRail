// DTOs mirroring apps/api/app/api/schemas.py. Money/decimal values arrive as strings and are never
// converted to floats for arithmetic; the server computes every amount.

export type UUID = string
export type Decimal = string

export type Role = 'OWNER' | 'MANAGER' | 'MEMBER' | 'VIEWER'
export type Category = 'IN_SCOPE' | 'BUG_FIX' | 'CHANGE_CANDIDATE' | 'AMBIGUOUS' | 'INSUFFICIENT_EVIDENCE'
export type InclusionType = 'INCLUDED' | 'EXCLUDED' | 'CONDITION'
export type ParseStatus = 'PENDING' | 'PARSING' | 'PARSED' | 'NEEDS_OCR_OR_REVIEW' | 'FAILED'
export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
export type RunStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'NEEDS_REVIEW' | 'FAILED'
export type RequestStatus = 'NEW' | 'ANALYZING' | 'NEEDS_REVIEW' | 'REVIEWED' | 'FAILED'
export type ReviewStatus = 'PENDING' | 'AUTO_ACCEPTED' | 'ACCEPTED' | 'OVERRIDDEN' | 'CLARIFICATION_REQUESTED'
export type ReviewDecision = 'ACCEPT' | 'OVERRIDE' | 'REQUEST_CLARIFICATION'
export type ChangeOrderStatus = 'DRAFT' | 'INTERNAL_REVIEW' | 'APPROVED_INTERNAL' | 'EXPORTED' | 'CANCELLED'
export type ChangeOrderAction = 'edit' | 'submit' | 'cancel' | 'preview' | 'approve' | 'request_changes' | 'export'
export type AnchorType = 'PDF_PAGE' | 'DOCX_PARAGRAPH' | 'DOCX_TABLE_CELL'

export interface TokenOut { access_token: string; token_type: string; expires_at: number }
export interface User { id: UUID; email: string; display_name: string }
export interface Workspace { id: UUID; name: string; role: Role; created_at: string }
export interface Me { user: User; workspaces: Workspace[]; auth_provider: string }
export interface Member { user_id: UUID; email: string; display_name: string; role: Role; status: string }

export interface Project {
  id: UUID
  workspace_id: UUID
  title: string
  client_name: string
  description: string
  currency: string
  budget: Decimal | null
  status: 'ACTIVE' | 'ARCHIVED'
  is_demo: boolean
  version: number
  created_at: string
}
export interface ProjectSummary extends Project {
  documents: number
  baseline_version: number | null
  has_draft: boolean
  open_reviews: number
  requests: number
}

export interface Job {
  id: UUID
  kind: string
  status: JobStatus
  attempts: number
  max_attempts: number
  progress: string | null
  last_error_code: string | null
  last_error: string | null
  next_run_at: string
  created_at: string
  finished_at: string | null
}

export interface DocumentVersion {
  id: UUID
  project_id: UUID
  version: number
  title: string
  original_name: string
  mime: string
  bytes: number
  sha256: string
  parse_status: ParseStatus
  parse_error: string | null
  parser_version: string | null
  page_count: number | null
  text_chars: number | null
  quality: { issues?: string[]; [k: string]: unknown }
  span_count: number
  created_at: string
}

export interface Anchor {
  anchor_type: AnchorType
  page: number | null
  paragraph_index: number | null
  table_ref: string | null
}

export interface SourceSpan extends Anchor {
  id: UUID
  document_version_id: UUID
  ordinal: number
  char_start: number
  char_end: number
  exact_quote: string
  normalized_text: string
  heading: string | null
}

export interface EvidenceRef extends Anchor {
  span_id: UUID
  document_version_id: UUID
  document_title: string
  document_version: number
  text: string
}

export interface ScopeItem {
  id: UUID
  ordinal: number
  title: string
  description: string
  inclusion_type: InclusionType
  acceptance_criteria: string
  origin: 'AI_CANDIDATE' | 'MANUAL'
  accepted: boolean
  evidence: EvidenceRef[]
}

export interface Baseline {
  id: UUID
  project_id: UUID
  version: number
  status: 'DRAFT' | 'APPROVED'
  draft_revision: number
  baseline_hash: string | null
  approved_by: UUID | null
  approved_by_name: string | null
  approved_at: string | null
  approval_note: string | null
  based_on_baseline_id: UUID | null
  created_at: string
  items: ScopeItem[]
}

export interface ScopeState {
  current: Baseline | null
  draft: Baseline | null
  history: { id: UUID; version: number; status: string; baseline_hash: string | null; approved_at: string | null }[]
  extraction_job: Job | null
}

export interface ScopeItemInput {
  id?: UUID
  title: string
  description: string
  inclusion_type: InclusionType
  acceptance_criteria: string
  source_span_ids: UUID[]
  accepted: boolean
}

export interface RequestItem {
  id: UUID
  ordinal: number
  exact_text: string
  start_offset: number
  end_offset: number
  summary: string
}

export interface FindingEvidence extends Anchor {
  span_id: UUID
  polarity: 'SUPPORTING' | 'COUNTER'
  quote: string
  scope_item_id: UUID | null
  scope_item_title: string | null
  inclusion_type: InclusionType | null
  document_version_id: UUID
  document_title: string
  document_version: number
  span_text: string
}

export interface FindingReview {
  decision: ReviewDecision
  category: Category
  reason: string
  actor_name: string
  created_at: string
}

export interface Finding {
  id: UUID
  request_item_id: UUID
  category: Category
  ai_category: Category | null
  final_category: Category | null
  summary: string
  reason: string
  uncertainties: string[]
  clarifying_questions: string[]
  policy_notes: string[]
  validation_errors: string[]
  model_confidence: Decimal | null
  needs_review: boolean
  review_status: ReviewStatus
  evidence: FindingEvidence[]
  reviews: FindingReview[]
}

export interface AnalysisRun {
  id: UUID
  request_id: UUID
  baseline_id: UUID
  baseline_version: number
  status: RunStatus
  provider: string | null
  model: string | null
  prompt_version: string | null
  schema_version: string | null
  token_usage: Record<string, number>
  error_code: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  job: Job | null
  findings: Finding[]
}

export interface ClientRequest {
  id: UUID
  project_id: UUID
  project_title: string
  channel: string
  sender: string
  subject: string
  message_text: string
  status: RequestStatus
  received_at: string
  created_at: string
  possible_duplicate_of: UUID | null
  items: RequestItem[]
  latest_run: AnalysisRun | null
}

export interface RequestListItem {
  id: UUID
  project_id: UUID
  project_title: string
  sender: string
  subject: string
  excerpt: string
  status: RequestStatus
  received_at: string
  items: number
  pending_reviews: number
  categories: Partial<Record<Category, number>>
}

export interface Rate { id: UUID; role: string; currency: string; hourly_rate: Decimal; created_at: string }
export interface Rates { revision: number; currency: string; rates: Rate[] }

export interface EstimateLine {
  ordinal: number
  kind: 'HOURLY' | 'FIXED'
  description: string
  role: string | null
  hours: Decimal | null
  rate_snapshot: Decimal | null
  amount: Decimal
}
export interface Estimate {
  id: UUID
  request_id: UUID
  request_item_id: UUID
  finding_id: UUID
  version: number
  status: 'DRAFT' | 'APPROVED'
  currency: string
  rate_card_revision: number
  subtotal: Decimal
  timeline_days: number | null
  notes: string
  approved_at: string | null
  created_at: string
  lines: EstimateLine[]
}
export interface EstimateLineInput {
  kind: 'HOURLY' | 'FIXED'
  description: string
  role?: string | null
  hours?: string | null
  amount?: string | null
}

export interface ChangeOrderContentItem {
  request_item_id: UUID
  requirement: string
  summary: string
  category: Category
  reason: string
  evidence: { span_id: UUID; quote: string; document_title: string; document_version: number; anchor: string }[]
  estimate: {
    id: UUID
    version: number
    rate_card_revision: number
    timeline_days: number | null
    subtotal: Decimal
    lines: { kind: 'HOURLY' | 'FIXED'; description: string; role: string | null; hours: Decimal | null; rate: Decimal | null; amount: Decimal }[]
  }
}
export interface ChangeOrderContent {
  schema: string
  language: 'en' | 'ru'
  number: number
  title: string
  summary: string
  project: { id: UUID; title: string; client_name: string }
  currency: string
  baseline: { id: UUID; version: number; hash: string | null }
  request: { id: UUID; received_at: string; sender: string; subject: string }
  items: ChangeOrderContentItem[]
  total: Decimal
  timeline_days: number | null
  terms: string
  acceptance_criteria: string
  exclusions: string
  valid_until: string | null
}
export interface Revision {
  id: UUID
  revision_no: number
  content_hash: string
  content: ChangeOrderContent
  created_by_name: string
  created_at: string
}
export interface Approval {
  id: UUID
  target_id: UUID
  decision: 'APPROVED' | 'CHANGES_REQUESTED' | 'REJECTED'
  comment: string
  content_hash: string
  actor_name: string
  decided_at: string
}
export interface ExportRecord {
  id: UUID
  revision_id: UUID
  content_hash: string
  pdf_sha256: string
  is_draft: boolean
  created_at: string
  download_path: string
}
export interface ChangeOrder {
  id: UUID
  project_id: UUID
  project_title: string
  request_id: UUID
  number: number
  status: ChangeOrderStatus
  current_revision_id: UUID | null
  approved_revision_id: UUID | null
  current: Revision
  revisions: Revision[]
  approvals: Approval[]
  exports: ExportRecord[]
  allowed_actions: ChangeOrderAction[]
  created_at: string
  updated_at: string
}
export interface ChangeOrderListItem {
  id: UUID
  project_id: UUID
  project_title: string
  number: number
  title: string
  status: ChangeOrderStatus
  currency: string
  total: Decimal
  revision_no: number
  updated_at: string
}

export interface AuditEvent {
  id: UUID
  project_id: UUID | null
  actor_type: 'USER' | 'SYSTEM' | 'WORKER'
  actor_name: string | null
  event_type: string
  object_type: string
  object_id: UUID | null
  object_version: number | null
  metadata: Record<string, unknown>
  occurred_at: string
}
export interface MoneyByCurrency { currency: string; amount: Decimal }
export interface Overview {
  active_projects: number
  needs_review: number
  requests_total: number
  potential_change_value: MoneyByCurrency[]
  approved_change_value: MoneyByCurrency[]
  change_orders_by_status: Partial<Record<ChangeOrderStatus, number>>
  recent_activity: AuditEvent[]
}
export interface InboxItem {
  finding_id: UUID
  request_item_id: UUID
  request_id: UUID
  project_id: UUID
  project_title: string
  requirement: string
  category: Category
  summary: string
  received_at: string
  created_at: string
}
export interface AIStatus { provider: string; model: string | null; configured: boolean; error: string | null; data_notice: string }
