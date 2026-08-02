# Resume handoff

Read this first when picking the project back up. Do not re-plan the project.

## Where things stand

**Commit:** `2364605` — "P0-4: tenant-scoped analytics and gated exports"
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

## Exact next task

P1-2 audit wiring, starting with the leads module. Repository evidence shows
`application/leads/service.py` commits lead state and outbox events but does not
write `AuditRecorder` rows. Add compact, redacted audit entries inside the same
`SqlAlchemyUnitOfWork` for capture, update, qualification, human review,
conversion, assignment and merge paths that actually exist. Preserve existing
event semantics and scoped reads. Add real-Postgres assertions proving the audit
row commits with the mutation and that tenant isolation/append-only guarantees
remain intact. Commit leads audit wiring independently before inspecting the next
pre-recorder module.

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
3. The reusable PostgreSQL 16 harness is the scheduled task
   `AIRevenueOS-Codex-Postgres` on port 55432. The borrowed Python environment is
   under the duplicate repository at `D:\passionn\PAISA HAI TO\...\backend\.venv`;
   always set `PYTHONPATH` to this repository's `backend/src`.

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
