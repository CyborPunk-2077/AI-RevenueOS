# Resume handoff

Read this first when picking the project back up. Do not re-plan the project.

## Where things stand

**Commit:** `c648207` — "P0-4: appointments (admin side)"
**Branch:** `master` · **Working tree:** clean

**Verified working** (by test or recorded execution, not assertion):

- P0-1 worker tier — 34 integration tests, real Postgres + Redis + Celery.
- P0-2 auth — 21 `/v1/auth` operations, 37 e2e tests.
- P0-3 frontend toolchain — frozen-lockfile install, lint, strict typecheck,
  production build (16 routes), 14 vitest tests.
- Local runtime — nine-service stack through `RUN_DEMO.cmd`, bounded health
  waits, idempotent migrate/seed, data preserved across restarts, destructive
  reset behind `RESET_DEMO.cmd`.
- CRM: contacts, accounts, activity/note timeline, deals and pipelines, tasks,
  **conversations and messages (shared inbox)**, **appointments**. 125 CRM e2e
  tests in total.

**Gates at that commit:** ruff, ruff-format, mypy (177 files), import-linter 6/6,
unit + contract + integration + CRM e2e green, web lint/typecheck/build clean.

**Browser path re-verified** through the real Next BFF with the API receiving
`Host: api:8000`: inbox renders with the gated-channel warning, conversation
opened, inbound recorded (partitioned write), reply shown as QUEUED with the
"no provider credential" note, automation-paused notice, conversation resolved,
appointment booked, double booking refused 409, cancel freeing the slot for
rebooking, and globex getting 404 on acme's thread and appointment.

## Exact next task

Documents and files (`P0-4`, the last unbuilt CRM module).

Copy `application/crm/appointments.py` — the pattern is established six times and
should not be re-derived:

- `scoped_query` / `get_scoped` for every read; never a bare tenant filter.
- `SqlAlchemyUnitOfWork` for state + outbox + audit in one transaction.
- Pydantic boundary schemas in `api/v1/schemas.py`, routes in `api/v1/crm.py`.
- ETag concurrency on anything editable.
- Tests in `tests/e2e/`, including a cross-tenant 404 case. Reuse the fixtures
  imported from `tests/e2e/test_crm_contacts_accounts.py` and add the module to
  the `F811` per-file-ignore list in `pyproject.toml`.

`Document` and related models are in
`infrastructure/database/models/documents.py`, and
`infrastructure/integrations/storage.py` already has an S3 adapter with
`is_configured()`. **Object storage is gated** (no AWS account), so build metadata
management — upload intent, listing, linking to a CRM record, soft delete — and
have the upload path return a clearly-unavailable response rather than a fake
presigned URL. Same discipline as the inbox: never claim a capability that has no
credential behind it.

After that, P0-4's six modules are done and the remaining code work is analytics
and reporting (M20), plus P1-2 (audit wiring for the modules that predate the
recorder — leads still writes no audit row).

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
2. **Playwright browsers cannot be installed** (needs root; download blocked).
   The specs exist and `make e2e` runs them.
3. `/tmp` is wiped between sessions. Rebuild the pnpm workspace with
   `corepack pnpm install --frozen-lockfile` in a scratch dir, and the live
   PostgreSQL harness from scratch, before browser-path checks.

The mounted filesystem refuses `unlink` on directories and on files inside
`.git`. If git reports "Another git process seems to be running", move the stale
lock aside rather than deleting it:

```bash
mv .git/index.lock .git/discarded-index-$(date +%s)
```

and drive git with `GIT_INDEX_FILE=/tmp/airev-index` so a stale default index
cannot silently commit the wrong tree. That mistake happened once and reverted a
commit; it was caught and fixed.
