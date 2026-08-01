"""M03 initial: schemas, extensions, full baseline, RLS, partitions, triggers.

Revision ID: 0001
Revises:
Create Date: 2026-08-01
"""
from __future__ import annotations

from datetime import date

from alembic import op
from sqlalchemy import text

from infrastructure.database.base import (
    SCHEMA_ANALYTICS, SCHEMA_APP, SCHEMA_AUDIT, SCHEMA_PUBLIC, TENANT_OWNED_TABLES,
)
from infrastructure.database.ddl import (
    APPEND_ONLY_FUNCTION, APPEND_ONLY_TABLES, PARTITIONED, RLS_NULLABLE_TEMPLATE,
    RLS_POLICY_TEMPLATE, SCHEMAS, UPDATED_AT_FUNCTION, append_only_trigger,
    partition_statements, updated_at_trigger,
)
from infrastructure.database.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Tables whose tenant_id column is nullable (platform-scoped rows are permitted).
NULLABLE_TENANT_TABLES = frozenset({
    "reconciliation_runs", "provider_webhook_events", "dead_letters",
})


def _schema_of(table_name: str) -> str:
    tbl = Base.metadata.tables.get(f"{SCHEMA_APP}.{table_name}")
    if tbl is not None:
        return SCHEMA_APP
    if Base.metadata.tables.get(f"{SCHEMA_AUDIT}.{table_name}") is not None:
        return SCHEMA_AUDIT
    if Base.metadata.tables.get(f"{SCHEMA_ANALYTICS}.{table_name}") is not None:
        return SCHEMA_ANALYTICS
    return SCHEMA_PUBLIC


def upgrade() -> None:
    conn = op.get_bind()

    for schema in SCHEMAS:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    conn.execute(text(UPDATED_AT_FUNCTION))
    conn.execute(text(APPEND_ONLY_FUNCTION))

    Base.metadata.create_all(bind=conn, checkfirst=True)

    # Mirror scalar python defaults as database defaults so raw SQL, workers,
    # ops scripts and recovery tooling all produce valid rows.
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.server_default is not None or column.default is None:
                continue
            arg = getattr(column.default, "arg", None)
            if callable(arg) or arg is None:
                continue
            if isinstance(arg, bool):
                literal = "true" if arg else "false"
            elif isinstance(arg, (int, float)):
                literal = str(arg)
            elif isinstance(arg, str):
                escaped = arg.replace("'", "''")
                literal = f"'{escaped}'"
            elif isinstance(arg, dict):
                literal = "'{}'::jsonb"
            elif isinstance(arg, list):
                literal = "'[]'::jsonb"
            else:
                continue
            conn.execute(
                text(
                    f'ALTER TABLE {table.schema}."{table.name}" '
                    f'ALTER COLUMN "{column.name}" SET DEFAULT {literal}'
                )
            )

    # Partition children for the three partitioned parents.
    for (schema, table), (_col, granularity) in PARTITIONED.items():
        for stmt in partition_statements(schema, table, granularity, date.today(), periods=3):
            conn.execute(text(stmt))

    # updated_at triggers for every table that carries the column.
    for table in Base.metadata.sorted_tables:
        if "updated_at" in table.c and table.schema:
            conn.execute(text(updated_at_trigger(table.schema, table.name)))

    # Append-only enforcement at the database, not only in application code.
    for schema, table in APPEND_ONLY_TABLES:
        conn.execute(text(append_only_trigger(schema, table)))

    # Row level security for every tenant-owned table.
    for table_name in sorted(TENANT_OWNED_TABLES):
        schema = _schema_of(table_name)
        template = (
            RLS_NULLABLE_TEMPLATE if table_name in NULLABLE_TENANT_TABLES else RLS_POLICY_TEMPLATE
        )
        conn.execute(text(template.format(schema=schema, table=table_name)))

    # The application must never connect as a superuser or table owner: BYPASSRLS
    # and ownership both defeat FORCE ROW LEVEL SECURITY. This role is the only
    # identity the API, workers and scheduler are permitted to use.
    conn.execute(text("""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'airevenueos_app') THEN
        CREATE ROLE airevenueos_app NOLOGIN NOBYPASSRLS;
      END IF;
    END $$;
    """))
    for schema in SCHEMAS:
        conn.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO airevenueos_app"))
        conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} "
            "TO airevenueos_app"
        ))
        conn.execute(text(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO airevenueos_app"
        ))
        conn.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO airevenueos_app"
        ))
    # Reference data is read-only to the application at runtime.
    for ref in ("plans", "feature_flags", "industry_templates", "permissions"):
        conn.execute(text(
            f"REVOKE INSERT, UPDATE, DELETE ON public.{ref} FROM airevenueos_app"
        ))

    # Vector indexes: HNSW m=16, ef_construction=200 per the AI System specification.
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        f"ON {SCHEMA_APP}.document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 200)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_lead_embeddings_embedding_hnsw "
        f"ON {SCHEMA_APP}.lead_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 200)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP OWNED BY airevenueos_app CASCADE"))
    for schema in (SCHEMA_ANALYTICS, SCHEMA_AUDIT, SCHEMA_APP):
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    for table in Base.metadata.sorted_tables:
        if table.schema == SCHEMA_PUBLIC:
            conn.execute(text(f'DROP TABLE IF EXISTS public."{table.name}" CASCADE'))
    conn.execute(text("DROP FUNCTION IF EXISTS public.set_updated_at() CASCADE"))
    conn.execute(text("DROP FUNCTION IF EXISTS public.reject_mutation() CASCADE"))
