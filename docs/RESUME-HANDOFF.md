# Resume handoff

Read this first when picking the project back up. Do not re-plan the project.

## Where things stand

**Commit:** `4f6b953` — "P0-4: activity and note timeline on contacts and accounts"
**Branch:** `master`
**Working tree:** clean

**Verified working** (by test or recorded execution, not assertion):

- P0-1 worker tier — 34 integration tests, real Postgres + Redis + Celery.
- P0-2 auth — 21 `/v1/auth` operations, 37 e2e tests.
- P0-3 frontend toolchain — frozen-lockfile install, lint, strict typecheck,
  production build, 14 vitest tests.
- Local runtime — full nine-service stack through `RUN_DEMO.cmd`, bounded health
  waits, idempotent migrate/seed, data preserved across restarts, destructive
  reset behind `RESET_DEMO.cmd`.
- CRM contacts, accounts, and the activity/note timeline — 39 e2e tests, plus the
  browser path checked live with the API receiving `Host: api:8000`.

**Gates at that commit:** ruff, ruff-format, mypy (173 files), import-linter 6/6,
unit + contract + integration + CRM e2e green, web lint/typecheck/build clean.

## Exact next task

Deals and pipelines (`P0-4`, module three of six).

Copy `application/crm/service.py` and `application/crm/timeline.py` — the pattern
is now established three times and should not be re-derived:

- `scoped_query` / `get_scoped` for every read; never a bare tenant filter.
- `SqlAlchemyUnitOfWork` for state + outbox + audit in one transaction.
- Pydantic boundary schemas in `api/v1/schemas.py`, routes in `api/v1/`.
- ETag concurrency on anything editable.
- Real outbox handlers, registered in `application/crm/handlers.py` and wired in
  `infrastructure/celery/tasks/scheduled.py`. No `pending_handler` stubs.
- Tests in `tests/e2e/`, including a cross-tenant 404 case.

`Pipeline`, `Stage` and `Deal` already exist in
`infrastructure/database/models/crm.py` with `DEAL_STATUSES`. The event catalog
already carries `OPPORTUNITY_*` constants.

After deals: conversations/messages, documents/files, appointments (admin side),
analytics. Then P1-2 (audit wiring for the remaining modules — contacts,
accounts and notes are already done).

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

All of the above are built, gated off, and return "not configured" rather than
faking success. See `docs/GA-ACTIVATION-CHECKLIST.md`.

## Environment limitations of the machine this was built on

Two things could never be verified here and must be checked on Windows:

1. **No Docker daemon.** `docker compose build` and `up` are unrun. Everything
   was verified against a real API, real PostgreSQL, real Redis and the real
   Next.js BFF as separate processes instead.
2. **Playwright browsers cannot be installed** (needs root; download blocked).
   The specs exist and `make e2e` runs them.

Also: the mounted filesystem refuses `unlink` on directories and on files inside
`.git`. If git reports "Another git process seems to be running", move the stale
lock aside rather than deleting it:

```bash
mv .git/index.lock .git/discarded-index-$(date +%s)
```

and drive git with `GIT_INDEX_FILE=/tmp/airev-index` so a stale default index
cannot silently commit the wrong tree. That mistake happened once and reverted a
commit; it was caught and fixed.
