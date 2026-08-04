"""Team invitations.

`app.invitations` existed as a SQLAlchemy model since 0001 but no migration ever
created it, so a database upgraded through the revision chain did not have the
table while a database built with `Base.metadata.create_all` did. Nothing failed,
because nothing wrote to it: there was no invitation service. Adding one made the
gap load-bearing.

The table is tenant-owned and carries the ordinary tenant policy. Only a SHA-256
of the token is stored, so a database reader cannot mint an invitation link, and
`accepted_at`/`revoked_at` make replay a no-op rather than a second membership.

The partial unique index is the interesting part: an email may hold at most one
*live* invitation per tenant, while historical accepted and revoked rows stay for
the audit trail. Without it, two admins inviting the same person concurrently both
succeed and the second link silently supersedes the first.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from infrastructure.database import models as _models  # noqa: F401  (populates registry)
from infrastructure.database.base import SCHEMA_APP, Base
from infrastructure.database.ddl import RLS_POLICY_TEMPLATE

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

TABLE = "invitations"


def upgrade() -> None:
    conn = op.get_bind()
    table = Base.metadata.tables[f"{SCHEMA_APP}.{TABLE}"]
    table.create(bind=conn, checkfirst=True)

    conn.execute(
        text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA_APP}.{TABLE} TO airevenueos_app")
    )
    conn.execute(text(RLS_POLICY_TEMPLATE.format(schema=SCHEMA_APP, table=TABLE)))

    conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_invitations_tenant_email_pending"
            f" ON {SCHEMA_APP}.{TABLE} (tenant_id, lower(email))"
            f" WHERE accepted_at IS NULL AND revoked_at IS NULL"
        )
    )
    conn.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_invitations_tenant_expires"
            f" ON {SCHEMA_APP}.{TABLE} (tenant_id, expires_at)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(f"DROP INDEX IF EXISTS {SCHEMA_APP}.uq_invitations_tenant_email_pending"))
    conn.execute(text(f"DROP INDEX IF EXISTS {SCHEMA_APP}.ix_invitations_tenant_expires"))
    conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {SCHEMA_APP}.{TABLE}"))
    conn.execute(text(f"DROP TABLE IF EXISTS {SCHEMA_APP}.{TABLE}"))
