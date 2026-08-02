# Resume handoff

Read this first when picking the project back up. Do not re-plan the project.

## Where things stand

**Latest implementation commit:** `784cbfc` — "P1-7: lock Python dependency graph"
**Branch:** `master` · **Working tree:** clean except the preserved pre-existing
untracked empty file `_tmp_5_43bb29c7ce5ddd61b5e99cfa69f4daf1`

**Verified working** (by test or recorded execution, not assertion):

- P0-1 worker tier — 34 integration tests, real Postgres + Redis + Celery.
- P0-2 auth — 21 `/v1/auth` operations, 37 e2e tests.
- P0-3 frontend toolchain — frozen-lockfile install, lint, strict typecheck,
  production build (17 routes), 14 vitest tests.
- Local runtime — nine-service stack through `RUN_DEMO.cmd`, bounded health
  waits, idempotent migrate/seed, data preserved across restarts, destructive
  reset behind `RESET_DEMO.cmd`.
- CRM: contacts, accounts, activity/note timeline, deals and pipelines, tasks,
  conversations/messages, appointments, and tenant-safe document/file metadata.
- Analytics: scoped funnel/source/qualification/revenue/payment/appointment/
  conversation/SLA/assignee dashboard, date-range API/UI, and tenant-bound daily
  rollups. Private exports are step-up/RBAC checked and durably recorded as
  blocked while AWS storage is unavailable; no file, key, or URL is fabricated.

**Verification for `2364605`:** ruff + format (226 files), focused strict mypy,
import-linter 6/6, unit+contract green, 159 CRM+analytics E2E tests on real
PostgreSQL with forced RLS, web lint/typecheck, 14 Vitest tests, and a clean
production build. The in-app browser verified Acme's populated analytics,
Globex's zero/isolated view, date trend, tenant badge, and the disabled export UI.

**Documents commit `981b27b`:** 24 focused and 150 CRM real-Postgres tests,
full backend/frontend gates, and Acme/Globex browser isolation. AWS storage is
still disabled by configuration and the activation work is documented in
`docs/runbooks/storage-activation.md`.

**P1-2 audit commits (do not redo):** `09f38a2` leads, `d6c272d` auth session
issuance/rotation/logout, `5bb870c` session revocations, `70dd416` registration
and password recovery, `3488fa2` MFA, `7c2f414` API keys, and `0caa2e8` AI usage.
Every entry is compact/redacted and is written in the same tenant transaction as
its mutation. Focused real-Postgres coverage proves 15 lead lifecycle cases, 5
auth audit scenarios, AI usage/audit atomicity, tenant isolation and audit
immutability. Ruff/format now cover 228 files; focused mypy, import-linter 6/6,
and the complete unit+contract suite are green.

**P1-5 is complete (do not redo):** `2097ba2` adds the anonymous, PII-free
`appointment.create` audit row to the public slot-claim transaction and races eight
claims against one slot on real PostgreSQL. Exactly one succeeds, seven raise the
domain conflict, and exactly one appointment, slot lock and tenant-isolated audit
row commit. The existing appointment E2E suite plus the new race test are 24/24;
ruff/format cover 229 files, focused strict mypy is green, import-linter remains
6/6, and the complete unit+contract suite is green.

**Recovery continuation (do not redo):** `24676fe` defines owned, executable
warning/critical Prometheus and AWS alert rules plus runbooks; `1c07f0b` makes
every public repository read require `EffectivePermissions`; `b1f9e08` persists
tenant export/deletion requests with audit and outbox; `9d2c8f2` durably publishes
versioned workflows and makes audited kill switches survive Redis loss; `040aed2`
records authenticated authorization denials; and `784cbfc` installs the runtime
and development Python graphs exclusively from committed, hash-locked files in
CI and Docker while keeping pnpm frozen. Focused real-Postgres tests prove tenant
isolation, atomic audit/outbox writes, workflow publication idempotency, and kill-
switch recovery. The complete unit+contract suite, Ruff/format over 239 files,
strict mypy over 176 source files, import-linter 6/6, and a fresh hash-locked pip
resolution are green. Docker and Terraform CLIs remain unavailable on this host;
alert YAML and all Terraform HCL were validated statically.

## Exact next task

P1-2 payments plus P2-4 durable inbound idempotency. Replace the Redis-only
Razorpay receipt path in `application/payments/inbound.py` with an atomic verified
`provider_webhook_events` insert, resolve the tenant from an existing provider
order/payment mapping (never trust tenant identity in webhook metadata), apply the
payment state machine, append `payment_transitions`, write compact
`payment.captured`/`payment.refunded` audit and outbox rows in the same transaction,
and mark the event processed only after business state commits. A duplicate event
must be a durable no-op even after Redis loss; an unknown mapping must remain
pending with a truthful error. Prove signature-before-persistence, duplicate and
out-of-order behavior, tenant isolation, and atomic rollback on real PostgreSQL.
Keep Razorpay disabled unless its external credentials and commercial approval
are actually present.

## Blockers that engineering cannot clear

| Blocker | Needs |
|---|---|
| P0-5 AWS | An account. Terraform is written and unapplied. |
| P0-6 legal | Sign-off on call recording consent, DPA, retention. |
| WhatsApp | Business API account + template approval. |
| Email | Provider + verified sending domain (DNS). |
| Payments | Razorpay commercial agreement. |
| Google sign-in | OAuth app verification. |
| SMS | DLT registration (India). |

All built, gated off, returning "not configured" rather than faking success. See
`docs/GA-ACTIVATION-CHECKLIST.md`.

## Environment limitations of the machine this was built on

1. **No Docker daemon.** `docker compose build` and `up` are unrun. Everything is
   verified against a real API, real PostgreSQL, real Redis and the real Next.js
   BFF as separate processes instead.
2. Standalone Playwright browser installation remains unavailable, but the Codex
   in-app browser works and was used for the document and analytics checks.
3. The old `AIRevenueOS-Codex-Postgres` task and borrowed duplicate-repository
   venv are stale/missing. The recovered PostgreSQL 16 harness is currently the
   `LOCAL SERVICE` scheduled task `AIRevenueOS-Codex-Postgres-Recovery`, port
   55432, data at `C:\airevpg-recovery-20260802-1`. Its isolated Python 3.12
   runtime is `C:\Users\Administrator\AppData\Local\Temp\airevenueos-recovery-venv`.
   Always set `PYTHONPATH` to this repository's `backend/src`. The persistent test
   database already has runtime roles and migrations: set `TEST_DATABASE_URL` to
   `postgresql+asyncpg://airev_app_runtime@127.0.0.1:55432/airevenueos_test` and
   `ALEMBIC_DATABASE_URL` to the matching `postgresql+psycopg://postgres@...`
   URL; leave `ADMIN_DATABASE_URL` unset or the fixture will try to recreate roles.
4. `tests/e2e/test_auth_surface.py` uses Unix-only `redislite`, so it was not
   rerun on this Windows recovery. The new auth audit coverage runs the same
   application services against real Postgres with the shared fakeredis fixture.
5. Terraform CLI is not installed. Terraform syntax is covered by `python-hcl2`,
   but format, validate, plan, apply, live AWS alert firing, and restore evidence
   remain unclaimed until the CLI and P0-5 account access exist.

`.git/config` contains a stale Linux `core.worktree`. Drive Git with the current
directory as `GIT_WORK_TREE` and the preserved alternate index at
`$env:TEMP\airevenueos-codex-index`; normal Git commands otherwise report an
invalid `/sessions/...` path. If Git reports a stale lock, move it aside rather
than deleting it. The earlier `HEAD.lock` is preserved as
`.git/discarded-HEAD-lock-1785642136`.

```powershell
$env:GIT_WORK_TREE = (Get-Location).Path
$env:GIT_INDEX_FILE = Join-Path $env:TEMP 'airevenueos-codex-index'
```
