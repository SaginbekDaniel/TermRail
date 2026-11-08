"""Telegram Business connector (read-only) and commercial signals. Additive only.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08 09:38:06.850361
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Target of the composite (project_id, workspace_id) FKs below; must exist before them.
    op.create_unique_constraint('uq_projects_id_workspace', 'projects', ['id', 'workspace_id'])
    op.create_table('telegram_update_receipts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('bot_id', sa.BigInteger(), nullable=False),
    sa.Column('update_id', sa.BigInteger(), nullable=False),
    sa.Column('update_type', sa.String(length=40), nullable=False),
    sa.Column('outcome', sa.String(length=40), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_update_receipts')),
    sa.UniqueConstraint('bot_id', 'update_id', name='uq_tg_receipts_bot_update')
    )
    op.create_table('telegram_business_connections',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('linked_by', sa.UUID(), nullable=True),
    sa.Column('bot_id', sa.BigInteger(), nullable=False),
    sa.Column('business_connection_id', sa.String(length=200), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('telegram_username', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('rights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('linked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'UNCLAIMED') = (workspace_id is null)", name=op.f('ck_telegram_business_connections_claimed_has_workspace')),
    sa.CheckConstraint("status in ('UNCLAIMED','CONNECTED','ACCESS_REVOKED','DISCONNECTED')", name=op.f('ck_telegram_business_connections_status')),
    sa.ForeignKeyConstraint(['linked_by'], ['users.id'], name=op.f('fk_telegram_business_connections_linked_by_users')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_telegram_business_connections_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_business_connections')),
    sa.UniqueConstraint('bot_id', 'business_connection_id', name='uq_tg_connections_bot_connection'),
    sa.UniqueConstraint('id', 'workspace_id', name='uq_tg_connections_id_workspace')
    )
    op.create_index(op.f('ix_telegram_business_connections_telegram_user_id'), 'telegram_business_connections', ['telegram_user_id'], unique=False)
    op.create_index('uq_tg_connections_one_connected_per_workspace', 'telegram_business_connections', ['workspace_id'], unique=True, postgresql_where=sa.text("status in ('CONNECTED','ACCESS_REVOKED')"))
    op.create_table('telegram_link_intents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('initiated_by', sa.UUID(), nullable=False),
    sa.Column('nonce_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=True),
    sa.Column('telegram_username', sa.String(length=64), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claimed_connection_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status in ('PENDING','VERIFIED','CLAIMED','EXPIRED','CONFLICT')", name=op.f('ck_telegram_link_intents_status')),
    sa.ForeignKeyConstraint(['initiated_by'], ['users.id'], name=op.f('fk_telegram_link_intents_initiated_by_users')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_telegram_link_intents_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_link_intents')),
    sa.UniqueConstraint('nonce_hash', name=op.f('uq_telegram_link_intents_nonce_hash'))
    )
    op.create_index(op.f('ix_telegram_link_intents_telegram_user_id'), 'telegram_link_intents', ['telegram_user_id'], unique=False)
    op.create_index(op.f('ix_telegram_link_intents_workspace_id'), 'telegram_link_intents', ['workspace_id'], unique=False)
    op.create_table('telegram_chat_bindings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('monitoring_enabled', sa.Boolean(), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('consent_by', sa.UUID(), nullable=True),
    sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('not monitoring_enabled or active', name=op.f('ck_telegram_chat_bindings_monitoring_requires_active')),
    sa.ForeignKeyConstraint(['connection_id', 'workspace_id'], ['telegram_business_connections.id', 'telegram_business_connections.workspace_id'], name='fk_tg_bindings_connection_ws'),
    sa.ForeignKeyConstraint(['consent_by'], ['users.id'], name=op.f('fk_telegram_chat_bindings_consent_by_users')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_telegram_chat_bindings_created_by_users')),
    sa.ForeignKeyConstraint(['project_id', 'workspace_id'], ['projects.id', 'projects.workspace_id'], name='fk_tg_bindings_project_ws'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_chat_bindings')),
    sa.UniqueConstraint('id', 'workspace_id', name='uq_tg_bindings_id_workspace')
    )
    op.create_index(op.f('ix_telegram_chat_bindings_project_id'), 'telegram_chat_bindings', ['project_id'], unique=False)
    op.create_index(op.f('ix_telegram_chat_bindings_workspace_id'), 'telegram_chat_bindings', ['workspace_id'], unique=False)
    op.create_index('uq_tg_bindings_active_chat', 'telegram_chat_bindings', ['connection_id', 'chat_id'], unique=True, postgresql_where=sa.text('active'))
    op.create_index('uq_tg_bindings_active_project', 'telegram_chat_bindings', ['project_id'], unique=True, postgresql_where=sa.text('active'))
    op.create_table('telegram_chat_candidates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('chat_type', sa.String(length=20), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['connection_id', 'workspace_id'], ['telegram_business_connections.id', 'telegram_business_connections.workspace_id'], name='fk_tg_candidates_connection_ws', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_chat_candidates')),
    sa.UniqueConstraint('connection_id', 'chat_id', name='uq_tg_candidates_connection_chat')
    )
    op.create_index(op.f('ix_telegram_chat_candidates_workspace_id'), 'telegram_chat_candidates', ['workspace_id'], unique=False)
    op.create_table('telegram_batches',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('binding_id', sa.UUID(), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('first_message_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('quiet_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('max_deadline', sa.DateTime(timezone=True), nullable=False),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('baseline_id', sa.UUID(), nullable=True),
    sa.Column('snapshot_hash', sa.String(length=64), nullable=True),
    sa.Column('outcome', sa.String(length=60), nullable=True),
    sa.Column('job_id', sa.UUID(), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state in ('OPEN','PROCESSED','NO_ACTION','CANCELLED')", name=op.f('ck_telegram_batches_state')),
    sa.ForeignKeyConstraint(['baseline_id'], ['scope_baselines.id'], name=op.f('fk_telegram_batches_baseline_id_scope_baselines')),
    sa.ForeignKeyConstraint(['binding_id', 'workspace_id'], ['telegram_chat_bindings.id', 'telegram_chat_bindings.workspace_id'], name='fk_tg_batches_binding_ws'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_telegram_batches_job_id_jobs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_batches'))
    )
    op.create_index(op.f('ix_telegram_batches_binding_id'), 'telegram_batches', ['binding_id'], unique=False)
    op.create_index('ix_tg_batches_state_quiet', 'telegram_batches', ['state', 'quiet_until'], unique=False)
    op.create_index('uq_tg_batches_one_open', 'telegram_batches', ['binding_id'], unique=True, postgresql_where=sa.text("state = 'OPEN'"))
    op.create_table('telegram_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('binding_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.BigInteger(), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('text_ciphertext', sa.LargeBinary(), nullable=True),
    sa.Column('text_hash', sa.String(length=64), nullable=True),
    sa.Column('text_length', sa.Integer(), nullable=False),
    sa.Column('has_unsupported_media', sa.Boolean(), nullable=False),
    sa.Column('content_version', sa.Integer(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("direction in ('INBOUND','OUTBOUND')", name=op.f('ck_telegram_messages_direction')),
    sa.CheckConstraint('content_version >= 1', name=op.f('ck_telegram_messages_content_version')),
    sa.ForeignKeyConstraint(['binding_id', 'workspace_id'], ['telegram_chat_bindings.id', 'telegram_chat_bindings.workspace_id'], name='fk_tg_messages_binding_ws'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_telegram_messages')),
    sa.UniqueConstraint('connection_id', 'chat_id', 'message_id', name='uq_tg_messages_connection_chat_message')
    )
    op.create_index(op.f('ix_telegram_messages_binding_id'), 'telegram_messages', ['binding_id'], unique=False)
    op.create_index(op.f('ix_telegram_messages_workspace_id'), 'telegram_messages', ['workspace_id'], unique=False)
    op.create_table('telegram_batch_messages',
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('message_row_id', sa.UUID(), nullable=False),
    sa.Column('version_at_snapshot', sa.Integer(), nullable=True),
    sa.Column('text_hash_at_snapshot', sa.String(length=64), nullable=True),
    sa.Column('prefilter_label', sa.String(length=30), nullable=True),
    sa.Column('segment_start', sa.Integer(), nullable=True),
    sa.Column('segment_end', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['telegram_batches.id'], name=op.f('fk_telegram_batch_messages_batch_id_telegram_batches'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_row_id'], ['telegram_messages.id'], name=op.f('fk_telegram_batch_messages_message_row_id_telegram_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('batch_id', 'message_row_id', name=op.f('pk_telegram_batch_messages'))
    )
    op.create_table('commercial_signals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('binding_id', sa.UUID(), nullable=True),
    sa.Column('request_id', sa.UUID(), nullable=True),
    sa.Column('latest_finding_id', sa.UUID(), nullable=True),
    sa.Column('baseline_id', sa.UUID(), nullable=True),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('fingerprint_terms', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fingerprint_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('evidence_state', sa.String(length=20), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('notify', sa.Boolean(), nullable=False),
    sa.Column('occurrences', sa.Integer(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolution_reason', sa.Text(), nullable=True),
    sa.Column('resolved_category', sa.String(length=40), nullable=True),
    sa.Column('resolved_by', sa.UUID(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('change_order_id', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category in ('CHANGE_CANDIDATE','AMBIGUOUS','INSUFFICIENT_EVIDENCE','BUG_FIX','IN_SCOPE','TIMELINE_CHANGE_CANDIDATE','PAYMENT_COMMITMENT_MENTION','UNANALYZED')", name=op.f('ck_commercial_signals_category')),
    sa.CheckConstraint("evidence_state in ('VALID','CHANGED','REVOKED')", name=op.f('ck_commercial_signals_evidence_state')),
    sa.CheckConstraint("severity in ('HIGH','MEDIUM','LOW')", name=op.f('ck_commercial_signals_severity')),
    sa.CheckConstraint("status in ('OPEN','CLARIFICATION_REQUESTED','DISMISSED','RESOLVED','CONVERTED')", name=op.f('ck_commercial_signals_status')),
    sa.ForeignKeyConstraint(['baseline_id'], ['scope_baselines.id'], name=op.f('fk_commercial_signals_baseline_id_scope_baselines')),
    sa.ForeignKeyConstraint(['change_order_id'], ['change_orders.id'], name=op.f('fk_commercial_signals_change_order_id_change_orders')),
    sa.ForeignKeyConstraint(['latest_finding_id'], ['findings.id'], name=op.f('fk_commercial_signals_latest_finding_id_findings')),
    sa.ForeignKeyConstraint(['project_id', 'workspace_id'], ['projects.id', 'projects.workspace_id'], name='fk_signals_project_ws'),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], name=op.f('fk_commercial_signals_request_id_requests')),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_commercial_signals_resolved_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_commercial_signals'))
    )
    op.create_index(op.f('ix_commercial_signals_workspace_id'), 'commercial_signals', ['workspace_id'], unique=False)
    op.create_index('ix_signals_project_status', 'commercial_signals', ['project_id', 'status', 'last_seen_at'], unique=False)
    op.create_table('signal_message_evidence',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('signal_id', sa.UUID(), nullable=False),
    sa.Column('message_row_id', sa.UUID(), nullable=False),
    sa.Column('message_content_version', sa.Integer(), nullable=False),
    sa.Column('message_text_hash', sa.String(length=64), nullable=False),
    sa.Column('quote_start', sa.Integer(), nullable=False),
    sa.Column('quote_end', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.UUID(), nullable=True),
    sa.Column('finding_id', sa.UUID(), nullable=True),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state in ('VALID','CHANGED','REVOKED')", name=op.f('ck_signal_message_evidence_state')),
    sa.CheckConstraint('quote_end > quote_start and quote_start >= 0', name=op.f('ck_signal_message_evidence_offsets')),
    sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], name=op.f('fk_signal_message_evidence_finding_id_findings')),
    sa.ForeignKeyConstraint(['message_row_id'], ['telegram_messages.id'], name=op.f('fk_signal_message_evidence_message_row_id_telegram_messages'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['signal_id'], ['commercial_signals.id'], name=op.f('fk_signal_message_evidence_signal_id_commercial_signals'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signal_message_evidence')),
    sa.UniqueConstraint('signal_id', 'message_row_id', 'message_content_version', 'quote_start', 'quote_end', name='uq_signal_evidence_exact')
    )
    op.create_index(op.f('ix_signal_message_evidence_message_row_id'), 'signal_message_evidence', ['message_row_id'], unique=False)
    op.create_index(op.f('ix_signal_message_evidence_signal_id'), 'signal_message_evidence', ['signal_id'], unique=False)
    op.add_column('requests', sa.Column('origin', sa.String(length=20), server_default='USER', nullable=False))
    op.add_column('requests', sa.Column('source_batch_id', sa.UUID(), nullable=True))
    op.create_unique_constraint(op.f('uq_requests_source_batch_id'), 'requests', ['source_batch_id'])
    op.create_foreign_key(op.f('fk_requests_source_batch_id_telegram_batches'), 'requests', 'telegram_batches', ['source_batch_id'], ['id'], use_alter=True)
    op.drop_constraint(op.f('ck_requests_channel'), 'requests', type_='check')
    op.create_check_constraint('channel', 'requests', "channel in ('MANUAL','EMAIL','TELEGRAM')")
    op.create_check_constraint('origin', 'requests', "origin in ('USER','INTEGRATION')")


def downgrade() -> None:
    # Never destroy data on downgrade: refuse while Telegram-originated requests exist.
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM requests WHERE channel = 'TELEGRAM' OR source_batch_id IS NOT NULL) THEN
            RAISE EXCEPTION 'Telegram-originated requests exist; export/remove them deliberately before downgrading';
          END IF;
        END $$;
        """
    )
    op.drop_constraint(op.f('ck_requests_origin'), 'requests', type_='check')
    op.drop_constraint(op.f('ck_requests_channel'), 'requests', type_='check')
    op.create_check_constraint('channel', 'requests', "channel in ('MANUAL','EMAIL')")
    op.drop_constraint(op.f('fk_requests_source_batch_id_telegram_batches'), 'requests', type_='foreignkey')
    op.drop_constraint(op.f('uq_requests_source_batch_id'), 'requests', type_='unique')
    op.drop_column('requests', 'source_batch_id')
    op.drop_column('requests', 'origin')
    op.drop_index(op.f('ix_signal_message_evidence_signal_id'), table_name='signal_message_evidence')
    op.drop_index(op.f('ix_signal_message_evidence_message_row_id'), table_name='signal_message_evidence')
    op.drop_table('signal_message_evidence')
    op.drop_index('ix_signals_project_status', table_name='commercial_signals')
    op.drop_index(op.f('ix_commercial_signals_workspace_id'), table_name='commercial_signals')
    op.drop_table('commercial_signals')
    op.drop_table('telegram_batch_messages')
    op.drop_index(op.f('ix_telegram_messages_workspace_id'), table_name='telegram_messages')
    op.drop_index(op.f('ix_telegram_messages_binding_id'), table_name='telegram_messages')
    op.drop_table('telegram_messages')
    op.drop_index('uq_tg_batches_one_open', table_name='telegram_batches', postgresql_where=sa.text("state = 'OPEN'"))
    op.drop_index('ix_tg_batches_state_quiet', table_name='telegram_batches')
    op.drop_index(op.f('ix_telegram_batches_binding_id'), table_name='telegram_batches')
    op.drop_table('telegram_batches')
    op.drop_index(op.f('ix_telegram_chat_candidates_workspace_id'), table_name='telegram_chat_candidates')
    op.drop_table('telegram_chat_candidates')
    op.drop_index('uq_tg_bindings_active_project', table_name='telegram_chat_bindings', postgresql_where=sa.text('active'))
    op.drop_index('uq_tg_bindings_active_chat', table_name='telegram_chat_bindings', postgresql_where=sa.text('active'))
    op.drop_index(op.f('ix_telegram_chat_bindings_workspace_id'), table_name='telegram_chat_bindings')
    op.drop_index(op.f('ix_telegram_chat_bindings_project_id'), table_name='telegram_chat_bindings')
    op.drop_table('telegram_chat_bindings')
    op.drop_index(op.f('ix_telegram_link_intents_workspace_id'), table_name='telegram_link_intents')
    op.drop_index(op.f('ix_telegram_link_intents_telegram_user_id'), table_name='telegram_link_intents')
    op.drop_table('telegram_link_intents')
    op.drop_index('uq_tg_connections_one_connected_per_workspace', table_name='telegram_business_connections', postgresql_where=sa.text("status in ('CONNECTED','ACCESS_REVOKED')"))
    op.drop_index(op.f('ix_telegram_business_connections_telegram_user_id'), table_name='telegram_business_connections')
    op.drop_table('telegram_business_connections')
    op.drop_table('telegram_update_receipts')
    op.drop_constraint('uq_projects_id_workspace', 'projects', type_='unique')
