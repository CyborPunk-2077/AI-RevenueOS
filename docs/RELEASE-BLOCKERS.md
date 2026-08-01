# Release blockers — AI RevenueOS

**Status: NOT GA-ready.**
**Audit date:** 2026-08-01 · Full findings: `docs/IMPLEMENTATION-AUDIT.md`

GA is blocked by **6 P0** items — 4 code gaps and 2 external gates — plus 11 P1.
No release gate may be waived without recorded evidence.

Effort is engineering-days for one experienced engineer, excluding external
turnaround.

---

## P0 — GA blocked

### Code gaps

#### P0-1 · No worker tier exists
`src/infrastructure/celery/` is absent, yet `docker-compose.yml` and the Makefile run
`celery -A infrastructure.celery.app`. Three compose services and the deployment
would fail immediately.

Everything asynchronous is therefore unimplemented: SLA escalation, appointment
reminders, payment reconciliation (spec: every 30 min), export generation, template
sync, retention/purge, partition maintenance, workflow scheduling and DLQ handling.

**Blocks:** M09, M14, M17, M18, M20, M22 · criteria 4, 5, 9, 15, 16, 17, 20, 27

**Remediation**
1. Create `src/infrastructure/celery/app.py` with the 8 queues already declared in
   `application/workflows/executor.py::QUEUES`, `acks_late`, `prefetch_multiplier=1`,
   JSON serialisation, `soft 480s / hard 600s`.
2. Bind tenant context at task entry from the task header — never from payload data
   alone — and reject a task with no tenant for tenant-scoped work.
3. Add Beat schedules: scheduler 10s, webhook sweep 60s, maintenance 03:00 UTC,
   metrics rollup 15m, reconciliation 30m.
4. Implement the DLQ writer against the existing `dead_letters` table with 14-day
   retention.
5. Integration test: enqueue → execute → fail → retry → dead-letter, asserting
   tenant context at every hop.

**Effort:** 5–8 days

---

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
| P0 | 4 | 2 | 6 |
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
