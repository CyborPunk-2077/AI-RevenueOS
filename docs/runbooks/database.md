# Runbook: database operations

## The non-negotiable rule

**The application must connect as `airevenueos_app` (or a login role that inherits
it), never as a superuser and never as the table owner.**

`BYPASSRLS` and table ownership both silently defeat `FORCE ROW LEVEL SECURITY`. A
superuser connection makes every RLS policy a no-op while all the tests still appear
to pass. This was caught during implementation and is now asserted by
`tests/integration/test_rls_isolation.py`, which connects as a non-owner role.

Verify in any environment:

```sql
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
-- rolsuper and rolbypassrls must both be false
```

## Migrations

Expand/contract, always:

1. **Expand** - add nullable columns, add indexes `CONCURRENTLY`, add foreign keys
   `NOT VALID`. Deploy. This release is backward compatible with the running code.
2. **Migrate** - dual write, backfill in batches, then dual read.
3. **Cut over** - read from the new shape.
4. **Contract** - drop the old column in a *later* release, marked
   `# expand-contract: contract-phase`.

`src/scripts/check_migration_safety.py` runs in the deploy pipeline and fails any
pre-deploy migration containing a drop, a type change or a non-concurrent index.

**Never hold a production DDL lock for more than two seconds.** Set a
`lock_timeout` before DDL and retry rather than queueing behind a long transaction.

## Partitions

| Table | Key | Granularity | Retention |
|---|---|---|---|
| `audit.audit_logs` | `created_at` | Monthly | 24 months, then archive |
| `audit.event_outbox` | `occurred_at` | Daily | 7 days |
| `app.messages` | `created_at` | Monthly | 36 months |

Partitions are created ahead of time by the maintenance job at 03:00 UTC. A default
partition exists so a late write is never lost, but a row landing in the default
partition is an alert - it means the maintenance job fell behind.

## Append-only tables

`audit_logs`, `consent_records`, `activities`, `payment_transitions` and
`lead_source_events` have a `BEFORE UPDATE OR DELETE` trigger that raises. Do not
work around it. A correction is a new row.

## Routine checks

- Slow queries: `pg_stat_statements` ordered by total time.
- Bloat and vacuum: watch `n_dead_tup` on `leads`, `contacts` and `activities`.
- Index health: unused indexes on hot write tables are a write-throughput tax.
- Connection pressure: PgBouncer in transaction mode sits in front of RDS.
