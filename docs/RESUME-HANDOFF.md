# Resume handoff

Read this first when picking the project back up. Do not re-plan the project.

## Where things stand

**Commit:** `0caa2e8` — "P1-2: audit AI usage tasks"
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

## Exact next task

P1-5 public-booking concurrency, coupled with its missing audit row.
`application/appointments/booking.py::claim_public_slot` creates the `SlotLock`
and `Appointment` in one `SqlAlchemyUnitOfWork`, but has no focused test and no
audit entry. Add a compact anonymous `appointment.create` record inside that UoW
(no intake/customer PII). Fire N concurrent claims at one slot on real Postgres;
prove exactly one succeeds, N-1 raise `Conflict`, and exactly one appointment,
slot lock and audit row commit. Also prove the audit row is tenant-isolated.
Commit this module independently. Do not touch the already-audited admin
appointment service.

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
