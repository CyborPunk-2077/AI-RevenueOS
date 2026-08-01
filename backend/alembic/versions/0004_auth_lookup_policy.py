"""Allow authentication to resolve a principal before a tenant is known.

Sign-in is inherently a pre-tenant operation: the email address is what identifies
the tenant, so the user row must be readable before `app.tenant_id` can be bound.
Under the strict tenant policy that read returns nothing and every login fails.

Rather than widen the tenant policy, or let authentication use the migration
credential, this adds a **SELECT-only** second policy on the two tables the login
and refresh paths must read. PostgreSQL ORs permissive policies together, so:

  * with `app.platform_context` bound, SELECT succeeds (this is what
    `platform_session()` does, and it logs the reason);
  * INSERT, UPDATE and DELETE remain governed solely by the tenant policy, so no
    caller can write across tenants;
  * with no context bound at all, nothing is visible, exactly as before.

The blast radius is therefore "a deliberate, logged read of users and refresh
tokens", not a general bypass.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

AUTH_LOOKUP_TABLES: tuple[tuple[str, str], ...] = (
    ("app", "users"),
    ("app", "refresh_tokens"),
)

POLICY = """
DROP POLICY IF EXISTS auth_lookup ON {schema}.{table};
CREATE POLICY auth_lookup ON {schema}.{table}
  FOR SELECT
  USING (coalesce(current_setting('app.platform_context', true), '') <> '');
"""


def upgrade() -> None:
    conn = op.get_bind()
    for schema, table in AUTH_LOOKUP_TABLES:
        conn.execute(text(POLICY.format(schema=schema, table=table)))
    # Authentication also updates the failed-attempt counter and rotates refresh
    # tokens, both of which happen once the tenant is known.
    conn.execute(text("GRANT SELECT, UPDATE ON app.users TO airevenueos_app"))
    conn.execute(text("GRANT SELECT, INSERT, UPDATE ON app.refresh_tokens TO airevenueos_app"))


def downgrade() -> None:
    conn = op.get_bind()
    for schema, table in AUTH_LOOKUP_TABLES:
        conn.execute(text(f"DROP POLICY IF EXISTS auth_lookup ON {schema}.{table}"))
