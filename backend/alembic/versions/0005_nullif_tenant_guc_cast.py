"""Make the tenant policy cast fail closed instead of erroring.

`set_config('app.tenant_id', ..., true)` is transaction-local, and when that
transaction ends PostgreSQL resets the custom GUC to the empty string rather than
NULL. The next statement on that pooled connection without a bound tenant then
evaluated `''::uuid` inside the policy and raised 22P02
(`invalid input syntax for type uuid`) -- a 500, not a clean denial.

PostgreSQL does not guarantee short-circuit evaluation of OR, so the guard clauses
added in later migrations did not prevent the cast from being evaluated.

`NULLIF(..., '')::uuid` yields NULL for an unbound tenant, and `tenant_id = NULL`
is NULL, so the row is hidden. Same isolation guarantee, no error path.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from infrastructure.database import models as _models  # noqa: F401  (populates registry)
from infrastructure.database.base import (
    SCHEMA_ANALYTICS,
    SCHEMA_APP,
    SCHEMA_AUDIT,
    TENANT_OWNED_TABLES,
    Base,
)
from infrastructure.database.ddl import (
    RLS_NULLABLE_TEMPLATE,
    RLS_PLATFORM_MAINTENANCE_TEMPLATE,
    RLS_POLICY_TEMPLATE,
)

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NULLABLE_TENANT_TABLES = frozenset(
    {"reconciliation_runs", "provider_webhook_events", "dead_letters", "audit_logs"}
)
PLATFORM_MAINTAINED = frozenset({"dead_letters"})


def _schema_of(table_name: str) -> str:
    for schema in (SCHEMA_APP, SCHEMA_AUDIT, SCHEMA_ANALYTICS):
        if Base.metadata.tables.get(f"{schema}.{table_name}") is not None:
            return schema
    return SCHEMA_APP


def _children(schema: str, table: str) -> list[str]:
    rows = (
        op.get_bind()
        .execute(
            text(
                "SELECT c.relname FROM pg_inherits i "
                "JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent "
                "JOIN pg_namespace n ON n.oid = p.relnamespace "
                "WHERE n.nspname = :s AND p.relname = :t"
            ),
            {"s": schema, "t": table},
        )
        .scalars()
    )
    return list(rows)


def _template_for(table: str) -> str:
    if table in PLATFORM_MAINTAINED:
        return RLS_PLATFORM_MAINTENANCE_TEMPLATE
    if table in NULLABLE_TENANT_TABLES:
        return RLS_NULLABLE_TEMPLATE
    return RLS_POLICY_TEMPLATE


def upgrade() -> None:
    conn = op.get_bind()
    for table in sorted(TENANT_OWNED_TABLES):
        schema = _schema_of(table)
        template = _template_for(table)
        conn.execute(text(template.format(schema=schema, table=table)))
        for child in _children(schema, table):
            conn.execute(text(template.format(schema=schema, table=child)))

    # Re-applying the tenant policy drops and recreates it, which would otherwise
    # remove the SELECT-only authentication lookup added in 0004.
    auth_policy = """
    DROP POLICY IF EXISTS auth_lookup ON {schema}.{table};
    CREATE POLICY auth_lookup ON {schema}.{table}
      FOR SELECT
      USING (coalesce(current_setting('app.platform_context', true), '') <> '');
    """
    for schema, table in (("app", "users"), ("app", "refresh_tokens")):
        conn.execute(text(auth_policy.format(schema=schema, table=table)))


def downgrade() -> None:
    # The previous form differed only by the unguarded cast, which is a defect.
    # Re-applying the corrected policy is the safe downgrade.
    upgrade()
