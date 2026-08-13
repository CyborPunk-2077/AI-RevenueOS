# AI RevenueOS

## 🎬 Product Demo

See RevenueOS in action through a short product walkthrough covering the core workspace and revenue-operations workflow.

**[▶ Watch the RevenueOS Demo](https://abhishek-project-demos1.vercel.app/revenueos.html)**

> For the full implementation, architecture, setup instructions, and technical documentation, continue below.

Multi-tenant B2B RevenueOS for Indian SMEs: canonical customer records, leads,
opportunities, activities, communications, appointments, documents, payments,
automation, analytics and compliance.

India defaults are `Asia/Kolkata`, INR, Indian phone validation, Razorpay and
WhatsApp. Internationalisation does not require a redesign.

## Status

**This is not GA.** Provider, cloud, legal, staging, performance, DAST, restore and
production claims stay unproven until real evidence exists; every externally gated
capability ships disabled. `docs/RELEASE-BLOCKERS.md` is the authoritative list of
what is open, and repository evidence overrides any summary - including this one.

Current post-audit hardening track:

| Item | State |
|---|---|
| P2-5 mutation testing gate | Configured, pinned, nightly, fail-closed at 75%. No score claimed; the runner is Linux-only |
| P2-6 strict mypy over the test tree | **Done.** 178 errors in 23 files fixed to zero; `tests` is in the mypy `packages` list, so bare `mypy` covers 264 source files |
| P2-7 OpenTelemetry tracing | **Implemented, externally gated.** Spans at five boundaries with allow-listed attributes; off until a collector exists. See `docs/runbooks/tracing.md` |
| P2-8 Storybook and a11y | **Done.** Storybook 8 over the component surface; `pnpm a11y` scans every story with axe in Chromium against WCAG 2.1 AA |
| P2-9 dev/staging/sandbox Terraform | **Done, unapplied.** Four environments, isolated state and address space, contract-tested differences; no AWS account exists yet |
| M05/M06 app shell and invitations | **Done.** Route groups, invitation flow end to end |
| M08 forms, import, dedupe, assignment | **Done.** Builder with publish snapshot, CSV import, rules, merge/disqualify/restore |
| M11 webchat | **Done.** Origin-authenticated widget, visitor sessions, hosted UI |

`docs/RESUME-HANDOFF.md` states the exact next task and the toolchain to run it.

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

Frontend components have a Storybook surface, and accessibility is a gate rather
than a review step:

```bash
pnpm storybook          # component workshop on :6006, with the a11y panel
pnpm a11y               # build it statically, scan every story with axe, fail on violations
```

`pnpm a11y` runs in CI. It checks WCAG 2.1 A and AA including colour contrast,
which needs real layout - a jsdom assertion cannot see it.

Integration tests run against a real PostgreSQL 16 with pgvector and connect as a
non-superuser role, so RLS is genuinely exercised rather than bypassed.

## Observability

Structured JSON logs carry `correlation_id`, `tenant_id`, `user_id` and, inside a
span, `trace_id`; the redactor strips secrets and P3 PII before anything is
written. Prometheus metrics are exposed on an allow-listed CIDR. Tracing is
OpenTelemetry over OTLP/HTTP and is **off** until both `OTEL_ENABLED` and an
exporter endpoint are set - see `docs/runbooks/tracing.md`, which also lists the
attributes a span may carry and the three categories that are deliberately never
recorded.

## Documentation

| Document | Purpose |
|---|---|
| `docs/RELEASE-BLOCKERS.md` | Authoritative open-blocker list; overrides summaries |
| `docs/RESUME-HANDOFF.md` | The exact next task, and how to run the gates here |
| `docs/adr/` | Architecture decisions and their trade-offs |
| `docs/runbooks/provider-activation.md` | Turning on a gated provider |
| `docs/runbooks/incident-response.md` | Severity, mitigation order, cross-tenant procedure |
| `docs/runbooks/disaster-recovery.md` | Backup, restore, regional recovery |
| `docs/runbooks/database.md` | Migrations, partitions, append-only tables |
| `docs/runbooks/workers.md` | Queues, pools, retries, dead letters, the three DB roles |
| `docs/runbooks/tracing.md` | OpenTelemetry: switches, span inventory, what may never be recorded |
| `docs/runbooks/frontend-quality.md` | Storybook, the accessibility gate, and how to fix a violation |
| `infra/terraform/README.md` | Environment layout, what differs between them and why |
| `docs/GA-ACTIVATION-CHECKLIST.md` | Every remaining external gate |
| `docs/ACCEPTANCE-EVIDENCE.md` | The 30 global criteria mapped to evidence |
| `docs/IMPLEMENTATION-LOG.md` | Milestone-by-milestone record |
