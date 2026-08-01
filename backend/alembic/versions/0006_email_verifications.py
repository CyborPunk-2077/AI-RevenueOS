"""Email verification tokens.

Sign-up issues a single-use confirmation link. Password resets already had
`app.password_resets`; email confirmation had nowhere to store a token, so the
verify-email endpoint could not exist.

The table is tenant-owned and carries the ordinary tenant policy: a verification
row belongs to exactly one tenant's user and must never be visible to another.
Only a SHA-256 of the token is stored, so a database reader cannot mint a
confirmation link, and `used_at` makes replay a no-op.

`0001` builds the schema with `Base.metadata.create_all`, so a database created
from scratch after this change already has the table. This migration exists for
databases that are already at `0005`, and is written to be safe in both cases.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from infrastructure.database import models as _models  # noqa: F401  (populates registry)
from infrastructure.database.base import SCHEMA_APP, Base
from infrastructure.database.ddl import RLS_POLICY_TEMPLATE

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLE = "email_verifications"


def upgrade() -> None:
    conn = op.get_bind()
    table = Base.metadata.tables[f"{SCHEMA_APP}.{TABLE}"]
    table.create(bind=conn, checkfirst=True)

    # The runtime role needs the same DML rights it has on the sibling token
    # tables; 0001 grants schema-wide but only over tables that existed then.
    conn.execute(
        text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA_APP}.{TABLE} TO airevenueos_app")
    )
    conn.execute(text(RLS_POLICY_TEMPLATE.format(schema=SCHEMA_APP, table=TABLE)))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {SCHEMA_APP}.{TABLE}"))
    conn.execute(text(f"DROP TABLE IF EXISTS {SCHEMA_APP}.{TABLE}"))
