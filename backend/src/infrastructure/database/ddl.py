"""Reusable DDL helpers: schemas, triggers, partitions and the RLS policy template.

The RLS policy is the second of two enforcement layers. Repository tenant filters
are the first; neither is trusted alone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from infrastructure.database.base import (
    SCHEMA_ANALYTICS,
    SCHEMA_APP,
    SCHEMA_AUDIT,
    SCHEMA_PUBLIC,
)

SCHEMAS = (SCHEMA_PUBLIC, SCHEMA_APP, SCHEMA_AUDIT, SCHEMA_ANALYTICS)

# Partitioned parents and their partition granularity/retention.
PARTITIONED: dict[tuple[str, str], tuple[str, str]] = {
    (SCHEMA_AUDIT, "audit_logs"): ("created_at", "month"),
    (SCHEMA_AUDIT, "event_outbox"): ("occurred_at", "day"),
    (SCHEMA_APP, "messages"): ("created_at", "month"),
}

UPDATED_AT_FUNCTION = """
CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Append-only guard used by audit, consent, activity, message and payment history.
APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION public.reject_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'table %.% is append-only', TG_TABLE_SCHEMA, TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

APPEND_ONLY_TABLES: tuple[tuple[str, str], ...] = (
    (SCHEMA_AUDIT, "audit_logs"),
    (SCHEMA_AUDIT, "consent_records"),
    (SCHEMA_APP, "activities"),
    (SCHEMA_APP, "payment_transitions"),
    (SCHEMA_APP, "lead_source_events"),
)

RLS_POLICY_TEMPLATE = """
ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON {schema}.{table};
CREATE POLICY tenant_isolation ON {schema}.{table}
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
"""

# Tables whose tenant_id is nullable (platform-scoped rows) get a policy that
# additionally permits NULL tenant rows only when no tenant context is bound.
RLS_NULLABLE_TEMPLATE = """
ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON {schema}.{table};
CREATE POLICY tenant_isolation ON {schema}.{table}
  USING (
    tenant_id = current_setting('app.tenant_id', true)::uuid
    OR (tenant_id IS NULL AND coalesce(current_setting('app.tenant_id', true), '') = '')
  )
  WITH CHECK (
    tenant_id = current_setting('app.tenant_id', true)::uuid
    OR (tenant_id IS NULL AND coalesce(current_setting('app.tenant_id', true), '') = '')
  );
"""


def updated_at_trigger(schema: str, table: str) -> str:
    return (
        f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {schema}.{table};\n"
        f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {schema}.{table} "
        f"FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();"
    )


def append_only_trigger(schema: str, table: str) -> str:
    return (
        f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {schema}.{table};\n"
        f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {schema}.{table} "
        f"FOR EACH ROW EXECUTE FUNCTION public.reject_mutation();"
    )


def month_bounds(anchor: date) -> tuple[date, date]:
    start = anchor.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


# Partition children do NOT inherit row level security from their parent, so every
# child must enable it explicitly or a direct read of the child bypasses isolation.
PLATFORM_SCOPED_PARTITIONS = frozenset({"event_outbox"})
NULLABLE_TENANT_PARTITIONS = frozenset({"audit_logs"})


def partition_rls(schema: str, child: str, parent: str) -> list[str]:
    """RLS statements for a freshly created partition child."""
    if parent in PLATFORM_SCOPED_PARTITIONS:
        return []
    template = (
        RLS_NULLABLE_TEMPLATE if parent in NULLABLE_TENANT_PARTITIONS else RLS_POLICY_TEMPLATE
    )
    return [s + ";" for s in template.format(schema=schema, table=child).split(";") if s.strip()]


def partition_statements(
    schema: str, table: str, granularity: str, anchor: date, periods: int = 3
) -> list[str]:
    """Create the default partition plus `periods` future partitions ahead of time."""
    statements = [
        f"CREATE TABLE IF NOT EXISTS {schema}.{table}_default "
        f"PARTITION OF {schema}.{table} DEFAULT;"
    ]
    statements += partition_rls(schema, f"{table}_default", table)
    if granularity == "month":
        start, _ = month_bounds(anchor)
        for _ in range(periods):
            s, e = month_bounds(start)
            statements.append(
                f"CREATE TABLE IF NOT EXISTS {schema}.{table}_p{s:%Y%m} PARTITION OF "
                f"{schema}.{table} FOR VALUES FROM ('{s}') TO ('{e}');"
            )
            statements += partition_rls(schema, f"{table}_p{s:%Y%m}", table)
            start = e
    else:
        start = anchor
        for _ in range(periods * 10):
            e = start + timedelta(days=1)
            statements.append(
                f"CREATE TABLE IF NOT EXISTS {schema}.{table}_p{start:%Y%m%d} PARTITION OF "
                f"{schema}.{table} FOR VALUES FROM ('{start}') TO ('{e}');"
            )
            statements += partition_rls(schema, f"{table}_p{start:%Y%m%d}", table)
            start = e
    return statements


def ensure_partition_sql(schema: str, table: str, granularity: str, when: datetime) -> list[str]:
    return partition_statements(schema, table, granularity, when.date(), periods=1)
