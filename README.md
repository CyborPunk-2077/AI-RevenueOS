# AI RevenueOS

Multi-tenant B2B RevenueOS for Indian SMEs: canonical customer records, leads,
opportunities, activities, communications, appointments, documents, payments,
automation, analytics and compliance.

India defaults are `Asia/Kolkata`, INR, Indian phone validation, Razorpay and
WhatsApp. Internationalisation does not require a redesign.

## Run the demo (Windows)

Docker Desktop running, then double-click **`RUN_DEMO.cmd`** — or from a terminal:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
```

It builds the images and starts the whole stack — Postgres, Redis, the API, four
worker pools, the Beat scheduler and the web app — waits for each to report
healthy, applies migrations, seeds demo data, verifies both demo sign-ins through
the browser path, and prints the URL and credentials.

Stopping and restarting keeps your data: the database lives in a named volume and
nothing on this path removes it. To start from an empty schema, run
**`RESET_DEMO.cmd`**, which asks you to type `reset` before it deletes anything.

## Quick start (Linux, macOS, WSL)

```bash
make bootstrap     # install every toolchain from a clean clone
make up            # Postgres, Redis, API, web, 4 worker pools, Beat
make migrate seed  # schema plus reference data
make verify        # lint, typecheck, module boundaries, full test suite
make test-workers  # worker tier: real Postgres + real Redis + real Celery worker
```

- API: <http://localhost:8000/v1/docs>
- Web: <http://localhost:3000>

## Layout

```
backend/src/
  api/            HTTP boundary: parsing, auth dependencies, response mapping
  application/    commands, queries, orchestration, transactions, ports
  domain/         pure entities, value objects, policy, events - no I/O
  infrastructure/ repositories, provider clients, cache, transport, telemetry
  shared/         types, results, pagination, exceptions, utilities
apps/web/         Next.js 14 App Router; the BFF is the only token holder
infra/terraform/  modules and per-environment stacks, ap-south-1
prompts/          Git-backed versioned prompts
docs/             ADRs, runbooks, evidence
```

`API -> application -> domain <- infrastructure` is enforced by `import-linter`, not
by convention. `make arch` fails the build on a violation.

## Two rules worth knowing before you change anything

**1. Tenant isolation is enforced twice.** The repository filters by `tenant_id`
before any query runs, and PostgreSQL RLS is `ENABLED` and `FORCED` on every
tenant-owned table. Neither layer is trusted alone.

The corollary that bites people: **the application must not connect as a superuser
or as the table owner.** `BYPASSRLS` and ownership both silently defeat
`FORCE ROW LEVEL SECURITY`, making every policy a no-op while tests still pass. See
`docs/adr/0002-tenant-isolation.md`.

**2. Externally gated capabilities ship disabled and are never faked.** WhatsApp,
email, voice, payments, signatures and n8n authoring all have complete adapters,
signature verification, retry and reconciliation - and `is_configured()` returns
`False` without both the flag and the credential. A send with no credential returns
`queued`, not a fabricated success. See `docs/adr/0003-external-gates.md` and
`docs/GA-ACTIVATION-CHECKLIST.md`.

## Testing

```bash
make test-unit         # pure domain, application and client logic
make test-integration  # real PostgreSQL: migrations, RLS, outbox, E2E journeys
make coverage          # against the per-module coverage bars
make security          # SAST, dependency audit, secret scan
```

Integration tests run against a real PostgreSQL 16 with pgvector and connect as a
non-superuser role, so RLS is genuinely exercised rather than bypassed.

## Documentation

| Document | Purpose |
|---|---|
| `docs/adr/` | Architecture decisions and their trade-offs |
| `docs/runbooks/provider-activation.md` | Turning on a gated provider |
| `docs/runbooks/incident-response.md` | Severity, mitigation order, cross-tenant procedure |
| `docs/runbooks/disaster-recovery.md` | Backup, restore, regional recovery |
| `docs/runbooks/database.md` | Migrations, partitions, append-only tables |
| `docs/runbooks/workers.md` | Queues, pools, retries, dead letters, the three DB roles |
| `docs/GA-ACTIVATION-CHECKLIST.md` | Every remaining external gate |
| `docs/ACCEPTANCE-EVIDENCE.md` | The 30 global criteria mapped to evidence |
| `docs/IMPLEMENTATION-LOG.md` | Milestone-by-milestone record |
