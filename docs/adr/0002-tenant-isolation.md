# ADR 0002: Two independent layers of tenant isolation

- Status: Accepted
- Date: 2026-08-01

## Context

Cross-tenant data exposure is a release-blocking defect. A single enforcement point
is a single point of failure, and application-level filtering is easy to forget in a
new query.

## Decision

Enforce tenant isolation twice, independently:

1. **Repository filter.** `TenantRepository.base_query()` applies
   `WHERE tenant_id = :tenant` before any query executes. Constructing a repository
   without a tenant id raises.
2. **PostgreSQL row level security.** Every tenant-owned table has RLS `ENABLED` and
   `FORCED` with the policy template from the specification, keyed on the
   transaction-local `app.tenant_id`.

The critical corollary: **the application must never connect as a superuser or as
the table owner.** `BYPASSRLS` and table ownership both silently defeat
`FORCE ROW LEVEL SECURITY`. Migration `0001` creates a dedicated `airevenueos_app`
role with `NOBYPASSRLS`, grants it DML only, and revokes write access to the
reference tables. This was found during implementation: the first RLS test suite
passed vacuously against a superuser connection.

`app.tenant_id` is set transaction-locally (`set_config(..., true)`) in the API,
workers, scheduler, migration tests and support paths, so it cannot leak across a
pooled connection.

## Consequences

- Forgetting a `WHERE tenant_id` clause produces zero rows rather than a breach.
- Every tenant-owned repository has a proven allow path and deny path
  (`tests/integration/test_rls_isolation.py`).
- A cross-tenant `INSERT` or an `UPDATE` that moves a row between tenants raises a
  database error, not a silent write.
- Operational cost: the production database user must be provisioned as a
  non-owner. This is documented in `docs/runbooks/database.md` and asserted by the
  RLS test suite.
