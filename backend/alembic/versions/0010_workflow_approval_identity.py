"""Give each execution node one durable approval request.

Revision ID: 0010
Revises: 0009

Idempotent on purpose, and the reason is worth writing down because it applies to
every migration written after this one.

Migration `0001` builds the baseline with `Base.metadata.create_all()` - it
creates whatever the *current* models declare. This constraint is declared on the
model, so on a database created today `0001` already makes it, and this migration
then tried to add it a second time and failed with `DuplicateTable`. On the
databases that were migrated before the model gained the constraint, `0001` did
not create it and this migration is what put it there.

Both histories are real and both must work, so the migration asks the database
what it already has instead of assuming. Nothing is weakened: the constraint is
present afterwards either way, and a database that somehow lacks it still gets it.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

CONSTRAINT = "execution_node_approval"
TABLE = "workflow_approvals"
SCHEMA = "app"


def _constraint_exists() -> bool:
    """True when the unique constraint is already on the table."""
    found = op.get_bind().execute(
        text(
            "SELECT 1 FROM pg_constraint c"
            " JOIN pg_class t ON t.oid = c.conrelid"
            " JOIN pg_namespace n ON n.oid = t.relnamespace"
            " WHERE c.conname = :name AND t.relname = :table AND n.nspname = :schema"
        ),
        {"name": CONSTRAINT, "table": TABLE, "schema": SCHEMA},
    )
    return found.first() is not None


def upgrade() -> None:
    if _constraint_exists():
        return
    op.create_unique_constraint(
        CONSTRAINT,
        TABLE,
        ["execution_id", "node_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    if not _constraint_exists():
        return
    op.drop_constraint(
        CONSTRAINT,
        TABLE,
        schema=SCHEMA,
        type_="unique",
    )
