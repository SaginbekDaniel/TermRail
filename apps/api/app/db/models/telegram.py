"""Telegram Business connector + commercial signals.

Tenant integrity is enforced by the database, not only by API checks: every row carries workspace_id and
references its parent through a composite (id, workspace_id) foreign key, so a binding can never point at
another workspace's project or connection, and a message can never hang off another tenant's binding.

Privacy: message bodies are stored only for chats the owner explicitly bound AND enabled monitoring on, and
only as ciphertext (see app/integrations/telegram/crypto.py). No raw webhook body is ever stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, updated_at_col, uuid_pk

CONNECTION_STATUSES = ("UNCLAIMED", "CONNECTED", "ACCESS_REVOKED", "DISCONNECTED")
INTENT_STATUSES = ("PENDING", "VERIFIED", "CLAIMED", "EXPIRED", "CONFLICT")
BATCH_STATES = ("OPEN", "PROCESSED", "NO_ACTION", "CANCELLED")
SIGNAL_CATEGORIES = (
    # Reused from the analysis domain (canonical requirement categories)
    "CHANGE_CANDIDATE",
    "AMBIGUOUS",
    "INSUFFICIENT_EVIDENCE",
    "BUG_FIX",
    "IN_SCOPE",
    # Integration-layer, non-monetary signals
    "TIMELINE_CHANGE_CANDIDATE",
    "PAYMENT_COMMITMENT_MENTION",
    "UNANALYZED",
)
SIGNAL_STATUSES = ("OPEN", "CLARIFICATION_REQUESTED", "DISMISSED", "RESOLVED", "CONVERTED")
EVIDENCE_STATES = ("VALID", "CHANGED", "REVOKED")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


class TelegramLinkIntent(Base):
    """One-time ownership proof: the signed-in user opens t.me/<bot>?start=<nonce>; Telegram then tells us
    which Telegram user id holds that nonce. Only sha256(nonce) is stored."""

    __tablename__ = "telegram_link_intents"
    __table_args__ = (CheckConstraint(f"status in {_in(INTENT_STATUSES)}", name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    initiated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)  # display only
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class TelegramBusinessConnection(Base):
    __tablename__ = "telegram_business_connections"
    __table_args__ = (
        UniqueConstraint("bot_id", "business_connection_id", name="uq_tg_connections_bot_connection"),
        UniqueConstraint("id", "workspace_id", name="uq_tg_connections_id_workspace"),
        CheckConstraint(f"status in {_in(CONNECTION_STATUSES)}", name="status"),
        CheckConstraint("(status = 'UNCLAIMED') = (workspace_id is null)", name="claimed_has_workspace"),
        Index(
            "uq_tg_connections_one_connected_per_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("status in ('CONNECTED','ACCESS_REVOKED')"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    linked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    business_connection_id: Mapped[str] = mapped_column(String(200), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)  # display only
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNCLAIMED")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class TelegramChatCandidate(Base):
    """Minimal metadata of a chat Telegram actually delivered an update for (never a contact list).
    Lets the owner pick a chat; no message text is ever stored here."""

    __tablename__ = "telegram_chat_candidates"
    __table_args__ = (
        UniqueConstraint("connection_id", "chat_id", name="uq_tg_candidates_connection_chat"),
        ForeignKeyConstraint(
            ["connection_id", "workspace_id"],
            ["telegram_business_connections.id", "telegram_business_connections.workspace_id"],
            ondelete="CASCADE",
            name="fk_tg_candidates_connection_ws",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_type: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelegramChatBinding(Base):
    __tablename__ = "telegram_chat_bindings"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_tg_bindings_id_workspace"),
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name="fk_tg_bindings_project_ws",
        ),
        ForeignKeyConstraint(
            ["connection_id", "workspace_id"],
            ["telegram_business_connections.id", "telegram_business_connections.workspace_id"],
            name="fk_tg_bindings_connection_ws",
        ),
        # One active project per chat, one active chat per project (MVP: no disambiguation UX).
        Index("uq_tg_bindings_active_chat", "connection_id", "chat_id", unique=True, postgresql_where=text("active")),
        Index("uq_tg_bindings_active_project", "project_id", unique=True, postgresql_where=text("active")),
        CheckConstraint("not monitoring_enabled or active", name="monitoring_requires_active"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    consent_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class TelegramUpdateReceipt(Base):
    """Idempotency ledger for webhook deliveries. Contains no message content."""

    __tablename__ = "telegram_update_receipts"
    __table_args__ = (UniqueConstraint("bot_id", "update_id", name="uq_tg_receipts_bot_update"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    update_type: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False, default="RECEIVED")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"
    __table_args__ = (
        UniqueConstraint("connection_id", "chat_id", "message_id", name="uq_tg_messages_connection_chat_message"),
        ForeignKeyConstraint(
            ["binding_id", "workspace_id"],
            ["telegram_chat_bindings.id", "telegram_chat_bindings.workspace_id"],
            name="fk_tg_messages_binding_ws",
        ),
        CheckConstraint("direction in ('INBOUND','OUTBOUND')", name="direction"),
        CheckConstraint("content_version >= 1", name="content_version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    text_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_unsupported_media: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramBatch(Base):
    __tablename__ = "telegram_batches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["binding_id", "workspace_id"],
            ["telegram_chat_bindings.id", "telegram_chat_bindings.workspace_id"],
            name="fk_tg_batches_binding_ws",
        ),
        CheckConstraint(f"state in {_in(BATCH_STATES)}", name="state"),
        Index("uq_tg_batches_one_open", "binding_id", unique=True, postgresql_where=text("state = 'OPEN'")),
        Index("ix_tg_batches_state_quiet", "state", "quiet_until"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    first_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quiet_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scope_baselines.id"), nullable=True
    )
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class TelegramBatchMessage(Base):
    """Batch membership + the snapshot taken at finalization (which content version was analysed and where
    it sits inside the composed request text, so findings can be cited back to exact Telegram messages)."""

    __tablename__ = "telegram_batch_messages"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_batches.id", ondelete="CASCADE"), primary_key=True
    )
    message_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_messages.id", ondelete="CASCADE"), primary_key=True
    )
    version_at_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_hash_at_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prefilter_label: Mapped[str | None] = mapped_column(String(30), nullable=True)
    segment_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CommercialSignal(Base):
    """One deduplicated, human-reviewable case ("potential change"), never a decision."""

    __tablename__ = "commercial_signals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"], ["projects.id", "projects.workspace_id"], name="fk_signals_project_ws"
        ),
        CheckConstraint(f"category in {_in(SIGNAL_CATEGORIES)}", name="category"),
        CheckConstraint(f"status in {_in(SIGNAL_STATUSES)}", name="status"),
        CheckConstraint(f"evidence_state in {_in(EVIDENCE_STATES)}", name="evidence_state"),
        CheckConstraint("severity in ('HIGH','MEDIUM','LOW')", name="severity"),
        Index("ix_signals_project_status", "project_id", "status", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    binding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=True)
    latest_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id"), nullable=True
    )
    baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scope_baselines.id"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fingerprint_terms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    evidence_state: Mapped[str] = mapped_column(String(20), nullable=False, default="VALID")
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="MEDIUM")
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_orders.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class SignalMessageEvidence(Base):
    """Exact citation of a Telegram message version: [quote_start, quote_end) within that version's text,
    pinned by its sha256 so a later edit/delete is detected and the evidence invalidated, never rewritten."""

    __tablename__ = "signal_message_evidence"
    __table_args__ = (
        UniqueConstraint(
            "signal_id",
            "message_row_id",
            "message_content_version",
            "quote_start",
            "quote_end",
            name="uq_signal_evidence_exact",
        ),
        CheckConstraint(f"state in {_in(EVIDENCE_STATES)}", name="state"),
        CheckConstraint("quote_end > quote_start and quote_start >= 0", name="offsets"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commercial_signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    message_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quote_start: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_end: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("findings.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="VALID")
    created_at: Mapped[datetime] = created_at_col()
