from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Category = Literal["IN_SCOPE", "BUG_FIX", "CHANGE_CANDIDATE", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE"]
InclusionType = Literal["INCLUDED", "EXCLUDED", "CONDITION"]
RoleName = Literal["OWNER", "MANAGER", "MEMBER", "VIEWER"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth / identity
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - not a secret
    expires_at: int


class UserOut(ORM):
    id: uuid.UUID
    email: str
    display_name: str


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    role: RoleName
    created_at: datetime


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]
    auth_provider: str


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: RoleName
    status: str


class MemberIn(BaseModel):
    email: EmailStr
    role: Literal["MANAGER", "MEMBER", "VIEWER"]


# ---------------------------------------------------------------- projects
class ProjectIn(BaseModel):
    workspace_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    client_name: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    budget: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    description: str = Field(default="", max_length=5000)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        v = v.upper()
        if not v.isalpha():
            raise ValueError("currency must be an ISO 4217 code")
        return v


class ProjectPatch(BaseModel):
    expected_version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    client_name: str | None = Field(default=None, min_length=1, max_length=200)
    budget: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    description: str | None = Field(default=None, max_length=5000)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class ProjectOut(ORM):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    client_name: str
    description: str
    currency: str
    budget: Decimal | None
    status: str
    is_demo: bool
    version: int
    created_at: datetime


class ProjectSummaryOut(ProjectOut):
    documents: int = 0
    baseline_version: int | None = None
    has_draft: bool = False
    open_reviews: int = 0
    open_signals: int = 0  # notify-worthy Telegram cases awaiting a human decision
    requests: int = 0


# ---------------------------------------------------------------- jobs
class JobOut(ORM):
    id: uuid.UUID
    kind: str
    status: str
    attempts: int
    max_attempts: int
    progress: str | None
    last_error_code: str | None
    last_error: str | None
    next_run_at: datetime
    created_at: datetime
    finished_at: datetime | None


# ---------------------------------------------------------------- documents
class DocumentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    title: str
    original_name: str
    mime: str
    bytes: int
    sha256: str
    parse_status: str
    parse_error: str | None
    parser_version: str | None
    page_count: int | None
    text_chars: int | None
    quality: dict[str, Any]
    span_count: int
    created_at: datetime


class UploadOut(BaseModel):
    document: DocumentOut
    duplicate: bool


class SpanOut(ORM):
    id: uuid.UUID
    document_version_id: uuid.UUID
    ordinal: int
    anchor_type: str
    page: int | None
    paragraph_index: int | None
    table_ref: str | None
    char_start: int
    char_end: int
    exact_quote: str
    normalized_text: str
    heading: str | None


# ---------------------------------------------------------------- scope
class EvidenceRefOut(BaseModel):
    span_id: uuid.UUID
    document_version_id: uuid.UUID
    document_title: str
    document_version: int
    anchor_type: str
    page: int | None
    paragraph_index: int | None
    table_ref: str | None
    text: str


class ScopeItemOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    title: str
    description: str
    inclusion_type: InclusionType
    acceptance_criteria: str
    origin: str
    accepted: bool
    evidence: list[EvidenceRefOut]


class BaselineOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    status: str
    draft_revision: int
    baseline_hash: str | None
    approved_by: uuid.UUID | None
    approved_by_name: str | None
    approved_at: datetime | None
    approval_note: str | None
    based_on_baseline_id: uuid.UUID | None
    created_at: datetime
    items: list[ScopeItemOut]


class ScopeItemIn(BaseModel):
    id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    inclusion_type: InclusionType
    acceptance_criteria: str = Field(default="", max_length=5000)
    source_span_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    accepted: bool = True


class DraftIn(BaseModel):
    expected_revision: int
    items: list[ScopeItemIn]


class ExtractIn(BaseModel):
    document_version_ids: list[uuid.UUID] | None = None


class ExtractOut(BaseModel):
    baseline_id: uuid.UUID
    job: JobOut


class ApproveBaselineIn(BaseModel):
    expected_revision: int
    note: str = Field(default="", max_length=2000)


class ScopeStateOut(BaseModel):
    current: BaselineOut | None
    draft: BaselineOut | None
    history: list[dict[str, Any]]
    extraction_job: JobOut | None


# ---------------------------------------------------------------- requests / analysis
class RequestIn(BaseModel):
    message_text: str = Field(min_length=1, max_length=20000)
    sender: str = Field(default="", max_length=300)
    subject: str = Field(default="", max_length=300)


class AnalyzeIn(BaseModel):
    baseline_id: uuid.UUID | None = None


class RequestItemOut(ORM):
    id: uuid.UUID
    ordinal: int
    exact_text: str
    start_offset: int
    end_offset: int
    summary: str


class FindingEvidenceOut(BaseModel):
    span_id: uuid.UUID
    polarity: Literal["SUPPORTING", "COUNTER"]
    quote: str
    scope_item_id: uuid.UUID | None
    scope_item_title: str | None
    inclusion_type: str | None
    document_version_id: uuid.UUID
    document_title: str
    document_version: int
    anchor_type: str
    page: int | None
    paragraph_index: int | None
    table_ref: str | None
    span_text: str


class FindingReviewOut(BaseModel):
    decision: str
    category: str
    reason: str
    actor_name: str
    created_at: datetime


class FindingOut(BaseModel):
    id: uuid.UUID
    request_item_id: uuid.UUID
    category: Category
    ai_category: Category | None
    final_category: Category | None
    summary: str
    reason: str
    uncertainties: list[str]
    clarifying_questions: list[str]
    policy_notes: list[str]
    validation_errors: list[str]
    model_confidence: Decimal | None
    needs_review: bool
    review_status: str
    evidence: list[FindingEvidenceOut]
    reviews: list[FindingReviewOut]


class AnalysisRunOut(BaseModel):
    id: uuid.UUID
    request_id: uuid.UUID
    baseline_id: uuid.UUID
    baseline_version: int
    status: str
    provider: str | None
    model: str | None
    prompt_version: str | None
    schema_version: str | None
    token_usage: dict[str, Any]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    job: JobOut | None
    findings: list[FindingOut]


class AnalyzeOut(BaseModel):
    analysis_run_id: uuid.UUID
    job_id: uuid.UUID | None
    status: str
    created: bool


class RequestOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    channel: str
    sender: str
    subject: str
    message_text: str
    status: str
    received_at: datetime
    created_at: datetime
    possible_duplicate_of: uuid.UUID | None = None
    items: list[RequestItemOut]
    latest_run: AnalysisRunOut | None


class RequestListItemOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    sender: str
    subject: str
    excerpt: str
    status: str
    received_at: datetime
    items: int
    pending_reviews: int
    categories: dict[str, int]


class ReviewIn(BaseModel):
    decision: Literal["ACCEPT", "OVERRIDE", "REQUEST_CLARIFICATION"]
    category: Category | None = None
    reason: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------- rates / estimates
class RateIn(BaseModel):
    role: str = Field(min_length=1, max_length=100)
    hourly_rate: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str | None = None


class RatesIn(BaseModel):
    expected_revision: int
    rates: list[RateIn] = Field(max_length=50)


class RateOut(ORM):
    id: uuid.UUID
    role: str
    currency: str
    hourly_rate: Decimal
    created_at: datetime


class RatesOut(BaseModel):
    revision: int
    currency: str
    rates: list[RateOut]


class EstimateLineIn(BaseModel):
    kind: Literal["HOURLY", "FIXED"]
    description: str = Field(default="", max_length=500)
    role: str | None = Field(default=None, max_length=100)
    hours: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)


class EstimateIn(BaseModel):
    request_item_id: uuid.UUID
    lines: list[EstimateLineIn] = Field(min_length=1, max_length=30)
    timeline_days: int | None = Field(default=None, ge=0, le=3650)
    notes: str = Field(default="", max_length=2000)


class EstimateLineOut(ORM):
    ordinal: int
    kind: str
    description: str
    role: str | None
    hours: Decimal | None
    rate_snapshot: Decimal | None
    amount: Decimal


class EstimateOut(BaseModel):
    id: uuid.UUID
    request_id: uuid.UUID
    request_item_id: uuid.UUID
    finding_id: uuid.UUID
    version: int
    status: str
    currency: str
    rate_card_revision: int
    subtotal: Decimal
    timeline_days: int | None
    notes: str
    approved_at: datetime | None
    created_at: datetime
    lines: list[EstimateLineOut]


# ---------------------------------------------------------------- change orders
class ChangeOrderIn(BaseModel):
    request_id: uuid.UUID
    estimate_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    title: str = Field(default="", max_length=300)
    language: Literal["en", "ru"] = "en"


class ChangeOrderPatch(BaseModel):
    expected_revision_no: int
    title: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=5000)
    terms: str | None = Field(default=None, max_length=5000)
    acceptance_criteria: str | None = Field(default=None, max_length=5000)
    exclusions: str | None = Field(default=None, max_length=5000)
    valid_until: str | None = None
    timeline_days: int | None = Field(default=None, ge=0, le=3650)


class ApproveCOIn(BaseModel):
    revision_id: uuid.UUID
    content_hash: str = Field(min_length=64, max_length=64)
    comment: str = Field(default="", max_length=2000)


class CommentIn(BaseModel):
    comment: str = Field(default="", max_length=2000)


class ExportIn(BaseModel):
    draft: bool = False


class RevisionOut(BaseModel):
    id: uuid.UUID
    revision_no: int
    content_hash: str
    content: dict[str, Any]
    created_by_name: str
    created_at: datetime


class ApprovalOut(BaseModel):
    id: uuid.UUID
    target_id: uuid.UUID
    decision: str
    comment: str
    content_hash: str
    actor_name: str
    decided_at: datetime


class ExportOut(BaseModel):
    id: uuid.UUID
    revision_id: uuid.UUID
    content_hash: str
    pdf_sha256: str
    is_draft: bool
    created_at: datetime
    download_path: str


class ChangeOrderOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    request_id: uuid.UUID
    number: int
    status: str
    current_revision_id: uuid.UUID | None
    approved_revision_id: uuid.UUID | None
    current: RevisionOut
    revisions: list[RevisionOut]
    approvals: list[ApprovalOut]
    exports: list[ExportOut]
    allowed_actions: list[str]
    created_at: datetime
    updated_at: datetime


class ChangeOrderListItemOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    number: int
    title: str
    status: str
    currency: str
    total: Decimal
    revision_no: int
    updated_at: datetime


# ---------------------------------------------------------------- overview / audit
class AuditOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    actor_type: str
    actor_name: str | None
    event_type: str
    object_type: str
    object_id: uuid.UUID | None
    object_version: int | None
    metadata: dict[str, Any]
    occurred_at: datetime


class MoneyByCurrency(BaseModel):
    currency: str
    amount: Decimal


class OverviewOut(BaseModel):
    active_projects: int
    needs_review: int
    requests_total: int
    potential_change_value: list[MoneyByCurrency]
    approved_change_value: list[MoneyByCurrency]
    change_orders_by_status: dict[str, int]
    recent_activity: list[AuditOut]


class InboxItemOut(BaseModel):
    finding_id: uuid.UUID
    request_item_id: uuid.UUID
    request_id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    requirement: str
    category: Category
    summary: str
    received_at: datetime
    created_at: datetime


class AIStatusOut(BaseModel):
    provider: str
    model: str | None
    configured: bool
    error: str | None
    data_notice: str
