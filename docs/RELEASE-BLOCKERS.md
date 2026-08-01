# Release blockers — AI RevenueOS

**Status: NOT GA-ready.**
**Audit date:** 2026-08-01 · **P0-1 closed:** 2026-08-01
Full findings: `docs/IMPLEMENTATION-AUDIT.md` · P0-1 evidence: `docs/p0-1-gate-results.txt`

GA is blocked by **5 P0** items — 3 code gaps and 2 external gates — plus 11 P1.
No release gate may be waived without recorded evidence.

| P0 | Status |
|---|---|
| P0-1 worker tier | **RESOLVED** — 34 integration tests on real Postgres + Redis + Celery |
| P0-2 auth endpoints | open |
| P0-3 frontend build | open |
| P0-4 domain services | open |
| P0-5 AWS account | open (external) |
| P0-6 legal sign-off | open (external) |

Effort is engineering-days for one experienced engineer, excluding external
turnaround.

---

## P0 — GA blocked

### Code gaps

#### ~~P0-1 · No worker tier exists~~ — **RESOLVED 2026-08-01**

`src/infrastructure/celery/` now exists and is the deployment contract compose and
the Makefile already referenced.

**Delivered**

- `app.py` — Celery app with the specification's exact settings: JSON only (never
  pickle), `acks_late`, `reject_on_worker_lost`, prefetch 1, hard 600s / soft 480s
  narrowed per queue.
- `queues.py` — all 8 queues with their concurrency, priority and timeout, plus the
  spec→broker priority inversion (spec 10 = most urgent, Redis 0 = delivered first)
  and 4 isolated worker pools.
- `context.py` — tenant, correlation and actor identity travel in message
  **headers**, not the payload, so task code cannot rewrite provenance and a replay
  keeps its original attribution. A tenant-scoped task **refuses to run** without a
  tenant header.
- `reliability.py` — retry classification (validation, permission, domain-rule and
  terminal business failures are never retried), exponential backoff with jitter,
  three idempotency layers with atomic `SET NX` claims, and durable dead lettering
  to `app.dead_letters` with 14-day retention and single-use replay.
- `tasks/` — outbox relay, workflow execute/resume, webhook sweep and deliver,
  metrics rollup, payment reconciliation, nightly maintenance, DLQ reaper.
- `health.py` + `src/scripts/worker_health.py` — liveness (broker) and readiness
  (broker + database), wired as the compose healthcheck for every pool.
- `src/scripts/run_worker.py`, `queue_status.py` — pool entrypoint with concurrency
  derived from the queue table, and an operator CLI for depths, live workers, dead
  letters and replay.
- Beat schedules at the specified cadences: outbox relay 500 ms, scheduler 10 s,
  webhook sweep 60 s, metrics rollup 15 m, reconciliation 30 m, maintenance
  03:00 UTC.
- `docker-compose.yml` now runs 4 real worker pools plus Beat, each with a health
  check. The placeholder services that invoked a non-existent package are gone.

**Verified** — 34 integration tests against real PostgreSQL 16, real Redis 6.2 and a
real in-process Celery worker (not eager mode, not mocks). Full suite 692 → **726
passing**. Raw output in `docs/p0-1-gate-results.txt`.

**Defects found and fixed while building it**

| # | Severity | Defect |
|---|---|---|
| W1 | **P1 concurrency** | The cached asyncio loop was a class attribute shared across worker threads, producing "Future attached to a different loop" under a threaded pool. Now thread-local. |
| W2 | **P1 security** | `write_dead_letter` wrote a tenant-owned row from an unscoped session. RLS correctly rejected it; the write now binds the tenant. |
| W3 | **P1 security** | Partition creation and RLS enablement need CREATE and ownership. The runtime role deliberately has neither, so a separate `airevenueos_maintenance` role was introduced (migration 0003) — the API role still cannot create or drop a table. |
| W4 | **P2** | Seeding reference data used the runtime role, which migration 0001 correctly revokes write access from. It now uses an administrative session. |

**Residual scope deliberately left open** (tracked under P0-4, not P0-1): concrete
workflow action handlers and the outbound webhook HTTP transport are stubs that
report `pending_handler` / `pending_transport` rather than claiming success. The
queues, retry, idempotency, DLQ and scheduling around them are complete.

#### P0-2 · No authentication endpoints
Every auth primitive is built and tested (Argon2id, RS256/JWKS, refresh rotation with
family-reuse revocation, TOTP, step-up MFA) but `/v1/auth/*` does not exist. Nothing
can log in. The BFF exchanges its session cookie at `/v1/auth/refresh`, which 404s.

**Blocks:** M04, M05 · criteria 21, and every criterion needing an authenticated UI

**Remediation**
1. Implement `POST /auth/{signup,login,logout,logout-all,refresh,forgot-password,
   reset-password,verify-email}`; `POST /auth/mfa/{setup,verify,disable,recovery}`;
   `GET /auth/{me,sessions}`; `DELETE /auth/sessions/{id}`;
   `GET /auth/google/{authorize,callback}`; `POST|GET|DELETE /auth/api-keys`.
2. Wire the existing `TokenService`, `RefreshToken` model and rate-limit policies
   (`login_ip` 5/15m, `login_account` 20/h, `refresh_user` 10/min, `mfa_user` 5/5m).
3. Make `get_token_service` fail closed outside `local` rather than generating an
   ephemeral keypair.
4. Contract tests for lockout, family-reuse revocation, session cap eviction and
   step-up enforcement.

**Effort:** 4–6 days

---

#### P0-3 · Frontend cannot be built
No `pnpm-lock.yaml`, no `next.config.*`, `tailwind.config.*`, `postcss.config.*` or
`next-env.d.ts`, and **zero `page.tsx`** — no route renders. 9 TS/TSX files
(~560 lines) exist; only 3 dependency-free modules were type-checkable.
`pnpm install --frozen-lockfile`, `pnpm build`, `pnpm typecheck`, `pnpm test` and
`pnpm a11y` all fail, so 4 of 6 CI jobs fail.

**Blocks:** M05 · criteria 19, 25, 28 (UI half), 2 (UI surface)

**Remediation**
1. Add the missing configs; run `pnpm install` and commit the lockfile.
2. Build the route tree from the spec's hierarchy: `(auth)`, `(onboarding)`,
   `(dashboard)/[tenantSlug]`, `(fullscreen)`.
3. Configure Vitest + React Testing Library and Playwright + axe.
4. Get `pnpm build && pnpm typecheck && pnpm test && pnpm a11y` green in CI.

**Effort:** 15–25 days for the full route tree; **2 days** to make the toolchain
build and CI honest.

---

#### P0-4 · Domain services and endpoints missing for six modules
Schema and pure domain logic exist and are well tested, but there is no service or
endpoint layer for CRM (contacts, accounts, activities, tasks, notes), deals and
pipelines, conversations and messages, documents and files, appointments (admin
side), or analytics. Only leads has a service.

**Blocks:** M07, M09, M10, M11, M13, M20 · criteria 3–5, 10–14, 19, 20, 22, 30

**Remediation** — per module: application service using
`TenantRepository.scoped_query`/`get_scoped`, `SqlAlchemyUnitOfWork` for
state+outbox, Pydantic boundary schemas, routes with permission and ETag handling,
audit via `AuditRecorder`, contract + E2E tests including a scope-denial case.
Follow `application/leads/service.py` as the reference.

**Effort:** 6–10 days per module (~40–55 days total)

---

### External gates

#### P0-5 · No AWS account — nothing has ever been deployed
Terraform has never been `init`/`validate`/`plan`ed. Only `envs/prod` exists though
`deploy.yml` targets dev/staging/prod. The compute tier is entirely undefined: no
ECS cluster, service or task definitions, no ALB target groups, no Route 53, no ECR,
no Secrets Manager entries, no IAM task roles.

**Blocks:** M02, M22, M23, M24 · criteria 23, 24
**Owner:** platform + finance
**Needs:** 4 AWS accounts, Route 53 zone, ACM certificate, GitHub OIDC role ARNs
**Then:** `terraform init && terraform validate && terraform plan` must pass before
any deployment claim; complete the compute module; run one restore drill.

---

#### P0-6 · No legal or compliance sign-off
DPDP privacy notices and consent copy, retention and legal-hold policy, voice
recording disclosure, and the prohibited-claim review for all eight industry
templates are unrecorded.

**Blocks:** M19, M23, M24 · criteria 26, 29 (operational half), 30
**Owner:** legal + compliance
**Note:** guardrails are enforced in code and tested; what is missing is the
signed-off copy and policy that the code enforces against.

---

## P1 — must clear before a pilot

| # | Item | Blocks | Remediation | Effort |
|---|---|---|---|---|
| P1-1 | **Scope enforcement is per-service, easy to forget.** Fixed for leads; every future service must remember `scoped_query`/`get_scoped`. | criteria 2, 4 | Make unscoped variants private; require an explicit `EffectivePermissions` argument. Add an architecture test asserting no service calls `base_query` directly | 1 day |
| P1-2 | **`AuditRecorder` is never called** and has 0% coverage. The audit trail is empty. | criterion 22 | Wire into every `MANDATORY_AUDIT_ACTIONS` path; assert an audit row per mutation in E2E | 3 days |
| P1-3 | **No alert rules exist.** Spec requires warning/critical alerts with owner and runbook per signal. | M02, M21, criterion 27 | Define alerts for API P95, queue depth/age, DLQ size, circuit opening, AI error >2%, budget 80%, RPO backup failure, WAF events | 2 days |
| P1-4 | **No restore drill.** `infra/scripts/verify-restore.sh` is referenced by the nightly workflow and does not exist. | M22, criterion 24 | Write the script (restore → `alembic current` → row-count reconciliation → **re-run the RLS suite against the restored instance**) and run it | 2 days + AWS |
| P1-12 | **Worker action handlers are stubs.** The workflow action dispatch and outbound webhook HTTP transport report `pending_handler`/`pending_transport`. Queues, retry, idempotency and DLQ around them are complete. | M18, criteria 16, 27 | Implement handlers per module as each service lands under P0-4 | folded into P0-4 |
| P1-5 | **Booking concurrency unproven.** `claim_public_slot` has 0% coverage; the unique constraint is the only defence and no concurrency test exists. | criterion 12 | Integration test firing N concurrent claims on one slot, asserting exactly one 201 and N-1 409s | 1 day |
| P1-6 | **Storage lifecycle not wired**; `ClamAvScanner.scan` raises `NotImplementedError`. Policy helpers are tested but no file can complete the flow. | M13, criterion 13 | Implement presign → complete → scan → clean/quarantine → signed download; integration test with a real clamd | 4 days |
| P1-7 | **No reproducible builds.** No lockfile on either side. | M01, M21 | Commit `pnpm-lock.yaml` and a Python lock (`uv.lock`/`requirements.lock`); pin in CI | 1 day |
| P1-8 | **Prompt governance absent.** `prompts/` is empty though the spec mandates Git-backed `prompts/<task>/v<n>.yaml` with promote/rollback and evaluation. `run_ai_evals.py` is referenced by CI and missing. | M12, criterion 6 | Author prompt files, implement the registry endpoints and the eval runner with gold sets | 5 days |
| P1-9 | **Coverage below the stated bars** in `application/*` (0–92% against a 90/85 target); several modules at 0%. | M21 | Raise to bar or record a per-module exception with an owner | 3 days |
| P1-10 | **Provider credentials absent** — WhatsApp BSP + template approval, email provider + domain, Razorpay commercial model. Adapters are complete and mock-tested; none has touched a live endpoint. | M15–M17, criteria 8, 15 | Follow `docs/runbooks/provider-activation.md` per provider | external |
| P1-11 | **k6 and ZAP never executed**; `peak.js` missing. | M21, criterion 23 | Run against staging once P0-5 clears; add the peak and spike profiles | 2 days + AWS |

---

## P2 — before GA, not before pilot

| # | Item | Remediation |
|---|---|---|
| P2-1 | Python version deviation (spec 3.12, project `>=3.10` with a `StrEnum` shim) | Adopt 3.12 and delete `shared/compat.py`, or record the deviation |
| P2-2 | Onboarding state machine missing (`GET/PATCH /onboarding/state`, `POST complete`) | Implement over the existing `tenants.onboarding_state` column |
| P2-3 | Kill switches live only in Redis — a flush disengages them and the action is unaudited | Persist to `workflow_definitions.kill_switch` and emit an audit event |
| P2-4 | `provider_webhook_events` table exists but is never written; inbound dedupe is Redis-only | Write verified events durably so a Redis outage cannot cause reprocessing |
| P2-5 | Mutation testing absent despite a stated 75–85% target | Add `mutmut`/`cosmic-ray` for domain and auth |
| P2-6 | `mypy` excludes `tests/` | Extend strict checking to tests |
| P2-7 | No tracing despite X-Ray in the stack table | Instrument with OpenTelemetry |
| P2-8 | Storybook declared in the Makefile, absent | Add it or drop the claim |
| P2-9 | Only `envs/prod` exists | Add dev/staging/sandbox stacks |
| P2-10 | Missing referenced files: `run_ai_evals.py`, `generate_evidence.py`, `verify-restore.sh`, `zap/rules.tsv`, `k6/peak.js` | Create them or remove the references from CI and the Makefile |

---

## Summary

| Priority | Code gaps | External gates | Total |
|---|---:|---:|---:|
| P0 | 3 (was 4) | 2 | 5 |
| P1 | 9 | 2 | 11 |
| P2 | 10 | 0 | 10 |

**Critical path to a pilot:** P0-1 (workers) → P0-2 (auth) → P0-3 (frontend
toolchain) → P0-4 (services, at least CRM + inbox) → P1-2 (audit wiring) →
P0-5 (AWS) → P1-4 (restore drill) → P0-6 (legal).

Rough order of magnitude: **60–90 engineering-days** of code work, in parallel with
external gate turnaround, before a controlled pilot is defensible.

### GA declaration

GA **must not** be declared. Of the 30 global acceptance criteria, 8 are verified,
19 are partial, 2 are missing and 1 is unverified. The specification requires every
P0 capability, all 30 criteria, no known cross-tenant issue, staging evidence,
backups/rollback/on-call/monitoring/quotas, provider and legal approvals, and a
pilot in each enabled industry. None of the last five conditions is met.
