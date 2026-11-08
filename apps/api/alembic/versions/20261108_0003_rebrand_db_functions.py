"""Rebrand: rename the immutability trigger functions created in 0002 to the termrail_* prefix.

Triggers reference their function by OID, so ALTER FUNCTION ... RENAME is atomic, keeps every trigger
attached and touches no data. Migration 0002 stays unchanged as history; the legacy names below are the
only place they are still needed (documented exception in scripts/verify_brand.py).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (legacy name created by 0002, new name)
RENAMES = [
    ("scopelock_forbid_mutation", "termrail_forbid_mutation"),
    ("scopelock_guard_baseline", "termrail_guard_baseline"),
    ("scopelock_guard_baseline_child", "termrail_guard_baseline_child"),
]


def upgrade() -> None:
    for old, new in RENAMES:
        op.execute(f"ALTER FUNCTION {old}() RENAME TO {new};")


def downgrade() -> None:
    for old, new in RENAMES:
        op.execute(f"ALTER FUNCTION {new}() RENAME TO {old};")
