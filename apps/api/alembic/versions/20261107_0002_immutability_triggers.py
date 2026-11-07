"""Database-level immutability guarantees (defence in depth behind the domain services).

- audit_events, approvals, finding_reviews, change_order_revisions: append-only.
- scope_baselines: once APPROVED, the row can never change.
- scope_items / scope_evidence / baseline_documents of an APPROVED baseline cannot change.
- source_spans: never updated after creation.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = ["audit_events", "approvals", "finding_reviews", "change_order_revisions"]


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scopelock_forbid_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'IMMUTABLE_ROW: % on % is not allowed', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION scopelock_forbid_mutation();"
        )
    op.execute(
        "CREATE TRIGGER source_spans_immutable BEFORE UPDATE ON source_spans "
        "FOR EACH ROW EXECUTE FUNCTION scopelock_forbid_mutation();"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION scopelock_guard_baseline() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'APPROVED' THEN
            RAISE EXCEPTION 'IMMUTABLE_ROW: approved baseline % cannot be modified', OLD.id
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER scope_baselines_guard BEFORE UPDATE OR DELETE ON scope_baselines "
        "FOR EACH ROW EXECUTE FUNCTION scopelock_guard_baseline();"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION scopelock_guard_baseline_child() RETURNS trigger AS $$
        DECLARE
          b_id uuid;
          b_status text;
        BEGIN
          IF TG_TABLE_NAME = 'scope_evidence' THEN
            SELECT si.baseline_id INTO b_id FROM scope_items si
              WHERE si.id = COALESCE(NEW.scope_item_id, OLD.scope_item_id);
          ELSE
            b_id := COALESCE(NEW.baseline_id, OLD.baseline_id);
          END IF;
          SELECT status INTO b_status FROM scope_baselines WHERE id = b_id;
          IF b_status = 'APPROVED' THEN
            RAISE EXCEPTION 'IMMUTABLE_ROW: % on % of approved baseline % is not allowed',
              TG_OP, TG_TABLE_NAME, b_id USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("scope_items", "scope_evidence", "baseline_documents"):
        op.execute(
            f"CREATE TRIGGER {table}_baseline_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION scopelock_guard_baseline_child();"
        )


def downgrade() -> None:
    for table in ("scope_items", "scope_evidence", "baseline_documents"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_baseline_guard ON {table};")
    op.execute("DROP TRIGGER IF EXISTS scope_baselines_guard ON scope_baselines;")
    op.execute("DROP TRIGGER IF EXISTS source_spans_immutable ON source_spans;")
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.execute("DROP FUNCTION IF EXISTS scopelock_guard_baseline_child();")
    op.execute("DROP FUNCTION IF EXISTS scopelock_guard_baseline();")
    op.execute("DROP FUNCTION IF EXISTS scopelock_forbid_mutation();")
