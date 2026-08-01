"""Worker tier database policies.

The dead letter queue is tenant data — a task payload can contain anything the
tenant owns — so it stays under row level security. But the retention sweep and the
operator replay path must, by definition, observe every tenant.

Rather than give maintenance a `BYPASSRLS` role (which would silently disable the
policy for every table it touches), the dead letter policy widens only when
`app.platform_context` is deliberately bound. `platform_session()` binds it and logs
the reason, so a cross-tenant read is always an explicit, attributable act.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from infrastructure.database.ddl import (
    RLS_PLATFORM_MAINTENANCE_TEMPLATE,
    RLS_POLICY_TEMPLATE,
)

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PLATFORM_MAINTAINED: tuple[tuple[str, str], ...] = (("app", "dead_letters"),)

# Partitioned parents whose children the maintenance job must create each month.
PARTITIONED_PARENTS: tuple[tuple[str, str], ...] = (
    ("audit", "audit_logs"),
    ("audit", "event_outbox"),
    ("app", "messages"),
)


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


def upgrade() -> None:
    conn = op.get_bind()
    for schema, table in PLATFORM_MAINTAINED:
        conn.execute(text(RLS_PLATFORM_MAINTENANCE_TEMPLATE.format(schema=schema, table=table)))

    # The worker writes dead letters and reads them back during replay.
    conn.execute(
        text("GRANT SELECT, INSERT, UPDATE, DELETE ON app.dead_letters TO airevenueos_app")
    )

    # Creating a partition child and enabling row level security on it requires
    # ownership of the parent, not merely CREATE on the schema. The maintenance
    # role therefore owns the partitioned parents. This is safe because every one
    # of them is FORCE ROW LEVEL SECURITY, which applies to the owner as well.
    for schema, table in PARTITIONED_PARENTS:
        conn.execute(text(f"ALTER TABLE {schema}.{table} OWNER TO airevenueos_maintenance"))
        for child in _children(schema, table):
            conn.execute(text(f"ALTER TABLE {schema}.{child} OWNER TO airevenueos_maintenance"))


def downgrade() -> None:
    conn = op.get_bind()
    for schema, table in PLATFORM_MAINTAINED:
        conn.execute(text(RLS_POLICY_TEMPLATE.format(schema=schema, table=table)))
