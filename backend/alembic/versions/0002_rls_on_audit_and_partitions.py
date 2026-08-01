"""Close two RLS gaps found by the release-readiness audit.

1. `audit.audit_logs` carries `tenant_id` but was never registered for row level
   security, so any query that forgot an explicit tenant predicate could read
   another tenant's audit trail. The specification requires tenant isolation to
   hold across support and export paths, which read exactly this table.

2. Partition children do not inherit row level security from their parent.
   PostgreSQL applies the parent policy to queries routed through the parent, but
   a direct read of `app.messages_p202608` bypasses it entirely. Enabling RLS on
   every child closes that path and makes the guarantee hold regardless of how the
   table is addressed.

`audit.event_outbox` and `audit.idempotency_records` are deliberately left
platform-scoped: the outbox poller and the idempotency reaper must observe every
tenant. Both are documented as such and neither is reachable from a tenant API.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from infrastructure.database.ddl import PARTITIONED, RLS_NULLABLE_TEMPLATE, RLS_POLICY_TEMPLATE

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# audit_logs permits a NULL tenant for platform-actor events (support tooling,
# scheduled maintenance), which are only visible when no tenant is bound.
NEWLY_PROTECTED: tuple[tuple[str, str, bool], ...] = (("audit", "audit_logs", True),)


def _children(conn: object, schema: str, table: str) -> list[str]:
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


def upgrade() -> None:
    conn = op.get_bind()

    for schema, table, nullable_tenant in NEWLY_PROTECTED:
        template = RLS_NULLABLE_TEMPLATE if nullable_tenant else RLS_POLICY_TEMPLATE
        conn.execute(text(template.format(schema=schema, table=table)))
        for child in _children(conn, schema, table):
            conn.execute(text(template.format(schema=schema, table=child)))

    # Existing partition children of already-protected parents.
    for (schema, table), _ in PARTITIONED.items():
        if table == "event_outbox":
            continue  # deliberately platform-scoped
        template = (
            RLS_NULLABLE_TEMPLATE
            if (schema, table) in {("audit", "audit_logs")}
            else RLS_POLICY_TEMPLATE
        )
        for child in _children(conn, schema, table):
            conn.execute(text(template.format(schema=schema, table=child)))

    conn.execute(text("GRANT SELECT, INSERT ON audit.audit_logs TO airevenueos_app"))

    # Partition and retention DDL runs as a separate, elevated role. The runtime
    # application role keeps DML only: it must never be able to create or drop a
    # table, which is what keeps a compromised API task from reshaping the schema.
    conn.execute(
        text(
            """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'airevenueos_maintenance') THEN
        CREATE ROLE airevenueos_maintenance NOLOGIN NOBYPASSRLS;
      END IF;
    END $$;
    """
        )
    )
    for schema in ("app", "audit", "analytics"):
        conn.execute(text(f"GRANT USAGE, CREATE ON SCHEMA {schema} TO airevenueos_maintenance"))
        conn.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} "
                "TO airevenueos_maintenance"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    for schema, table, _ in NEWLY_PROTECTED:
        for child in _children(conn, schema, table):
            conn.execute(text(f"ALTER TABLE {schema}.{child} DISABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {schema}.{child}"))
        conn.execute(text(f"ALTER TABLE {schema}.{table} DISABLE ROW LEVEL SECURITY"))
        conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {schema}.{table}"))
    for (schema, table), _ in PARTITIONED.items():
        if table == "event_outbox":
            continue
        for child in _children(conn, schema, table):
            conn.execute(text(f"ALTER TABLE {schema}.{child} DISABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {schema}.{child}"))
