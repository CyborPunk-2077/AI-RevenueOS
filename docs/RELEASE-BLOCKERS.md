# Release blockers — AI RevenueOS

**Status: NOT GA-ready.**
**Audit date:** 2026-08-02 · **P0-1 closed:** 2026-08-01 · **P0-2 closed:** 2026-08-01 · **P0-3 closed:** 2026-08-01
Full findings: `docs/IMPLEMENTATION-AUDIT.md` · P0-1 evidence: `docs/p0-1-gate-results.txt`

GA is blocked by **2 external P0** items plus 7 remaining P1 items.
No release gate may be waived without recorded evidence.

| P0 | Status |
|---|---|
| *(demo slice)* | one tenant-scoped CRM flow runs in a browser — see below |
| P0-1 worker tier | **RESOLVED** — 34 integration tests on real Postgres + Redis + Celery |
| P0-2 auth endpoints | **RESOLVED** — 21 operations, 37 e2e tests on real Postgres + Redis |
| P0-3 frontend build | **RESOLVED** — reproducible install, lint, strict typecheck, production build, 14 unit tests |
| P0-4 domain services | **RESOLVED** — CRM, inbox, appointments, documents and analytics are tenant-scoped and tested |
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

**Residual scope deliberately left open** (tracked under P0-4, not P0-1): workflow
trigger matching and durable approval decisions remain. Concrete actions now resolve
the current accountable publisher and current grants, enforce plan/feature/provider
gates, invoke landed module services, and recover duplicates from atomic audit
receipts after Redis or worker loss. Delays persist exact successor nodes and resume
without replaying the delay. Externally unapproved payment/signature actions refuse
truthfully. The signed outbound webhook delivery path is complete.

### Demo slice (2026-08-01) — narrow, between P0-1 and P0-2

A single vertical slice was delivered so the product is visible locally: sign in →
list → create → open → edit → refresh, plus proven tenant isolation. It added
`/v1/auth/{login,refresh,logout,me}`, a two-tenant demo seed, and 8 Next.js routes.
It did **not** start P0-2, P0-3 or P0-4 proper.

Five real defects were found and fixed:

| # | Severity | Defect |
|---|---|---|
| D1 | **P1 correctness** | The tenant RLS policy cast `''::uuid` when no tenant was bound. A transaction-local GUC resets to the empty string, not NULL, so the next pooled use raised 22P02 — a 500 instead of a clean denial. Migration 0005 wraps every clause in `NULLIF`, so it fails closed. |
| D2 | **P1 usability** | `Settings` crashed on boot with the comma-separated `TRUSTED_HOSTS` / `CORS_ALLOWED_ORIGINS` that `.env.example` documents: pydantic-settings JSON-decodes complex types before validators run. Fixed with `NoDecode`. |
| D3 | **P1 correctness** | The access token embedded all ~720 owner permissions, making the session cookie exceed the header limit (HTTP 431). Permissions are now derived from roles at the request boundary; an explicit claim still wins, so custom roles remain possible. |
| D4 | **P1 correctness** | The BFF refreshed on every server render, rotating the refresh token while the browser still held the previous one. The second request looked like replay and the server correctly revoked the whole family. The BFF now holds a short-lived HttpOnly access token and refreshes only inside route handlers. |
| D5 | P2 | Cookies were marked `Secure` based on `NODE_ENV`, so a local production build over http silently failed to sign in. The flag now follows the request scheme; HTTPS still gets the strict `__Host-` prefix. |

**Windows packaging follow-up (2026-08-01).** The slice above could not actually be
started on Windows: the `web` image failed to build with `cannot copy to
non-directory: .../apps/web/node_modules/@playwright/test`. The repository had no
root `.dockerignore`, so `COPY . .` merged the host's `node_modules` over the tree
installed in the image. Fixed by adding a root `.dockerignore` **and**
`backend/.dockerignore` (the api, worker and beat services build from `./backend`,
which the root file does not govern), rewriting `apps/web/Dockerfile` onto npm with
a committed lockfile, and pointing the api at the login-capable database roles.
`scripts/demo.ps1` starts the whole stack, migrates, seeds and prints the URL, so
GNU make is no longer required. See audit A14.

**Sign-in follow-up (2026-08-01).** The stack then started but the printed
credentials were rejected. Cause was neither the password nor the hash: the API
trusted only `localhost`/`127.0.0.1`, while the BFF calls it as `http://api:8000`,
so `TrustedHostMiddleware` answered `400 Invalid host header` before authentication
ran, and the BFF reported it as `Sign in failed.` The container looked healthy the
whole time because its probe uses `localhost` — which is why the launcher now
proves a real sign-in instead. See audit A16–A18.

**Not yet confirmed on hardware:** no Docker daemon exists in the environment this
was prepared in, so `docker compose build`, `docker compose up` and a live response
from `http://localhost:3000` remain unverified. The login path itself *was*
reproduced and fixed against a real API and the real Next.js BFF with the API
receiving `Host: api:8000`.

Authentication needs to read a user before a tenant is known, so migration 0004 adds
a **SELECT-only** policy on `app.users` and `app.refresh_tokens` gated on
`app.platform_context`. Writes stay governed by the tenant policy alone, so no
caller can write across tenants. Every auth write runs bound to the resolved tenant.

**Not delivered by the slice** (still P0-2): signup, MFA enrolment and verification,
Google OAuth, password reset, email verification, API keys, session listing and
revocation, and rate limiting on the auth routes. Step-up-protected operations
correctly remain refused because the slice never sets `mfa_verified`.

---

#### ~~P0-2 · No authentication endpoints~~ — **RESOLVED 2026-08-01**

The full `/v1/auth` surface from specification line 304 now exists: **21 operations**,
every one of them wiring the primitives that were already built and tested rather
than reimplementing them.

- `signup` creates a tenant and its owner and issues **no session** — the address is
  unconfirmed, so an unverified sign-up cannot sign in. `verify-email` activates it.
- `forgot-password` / `reset-password` are non-enumerating and single use, and a
  reset revokes every live refresh token for the account.
- `mfa/{setup,setup/confirm,verify,recovery,disable}` — the secret is committed only
  after a code generated from it is proved, recovery codes are shown exactly once,
  and disabling demands the password *and* a live code.
- Login now returns an **MFA challenge** rather than a session when the account is
  enrolled; the challenge is opaque, single use (`GETDEL`) and carries no permissions.
- `mfa_verified` became a property of the *session*, set only by a completed
  challenge, which is what finally makes the step-up dependency meaningful.
- `sessions` / `DELETE sessions/{id}` / `logout-all` operate on refresh-token
  families and blacklist the access-token jti, so revocation is immediate rather
  than "within 15 minutes".
- `google/{authorize,callback}` is gated (`FEATURE_NOT_AVAILABLE` without
  credentials), consumes its state atomically, and **never auto-provisions** a user.
- `api-keys` reveals the value once, masks it on every subsequent read, refuses to
  grant scopes the creator does not hold, and requires step-up to create.

**Defects found and fixed while building it**

| # | Severity | Defect |
|---|---|---|
| S1 | **P1 security** | `sessions_to_evict` had been unit-tested since M04 but was called from nowhere, so `MAX_SESSIONS_PER_USER` was documented and unenforced — a user could hold unlimited concurrent sessions. Now enforced in `issue_session` before each new family. |
| S2 | **P1 security** | Session revocation dropped refresh tokens but left the access token valid for its full TTL. Revocation now blacklists the jti, which `get_principal` already consulted. |
| S3 | P2 | The demo seed reset password, status and lockout on re-run but not MFA, so enrolling an authenticator against a throwaway demo account and losing the device made the demo permanently unusable. |

**Verified** — 37 e2e tests over HTTP against real PostgreSQL 16 (RLS forced) and
real Redis 6.2 via `redislite`; `fakeredis` was deliberately rejected because it
cannot run the limiter's Lua script, which would have made every rate-limit
assertion pass for the wrong reason. Covers login, refresh-token reuse revoking the
family, lockout, session-cap eviction, MFA step-up, API-key safety, cross-tenant
denial and single-use OAuth state. Live-checked against a running API with
`Host: api:8000`: signup 201, verify-email 200, step-up refusal 403, logout-all
revoking 10 sessions, and the subsequent refresh 401.

**Fail-closed, confirmed by execution:** `get_token_service` refuses to boot in
`dev`/`staging`/`sandbox`/`prod` without configured signing material; MFA refuses to
store a secret without an encryption master key; Google OAuth reports the capability
unavailable without credentials; and the local-only echo of emailed tokens is false
in every environment except `local`, and false even there once an email provider is
configured.

**Not included** (deliberately, and not P0-2): invitation acceptance, and
authenticating *with* an API key. The key management surface the specification names
is complete; using a key as a request credential is developer-platform work.

#### ~~P0-3 · Frontend toolchain unusable~~ — **RESOLVED 2026-08-01**

The original entry claimed "zero `page.tsx` — no route renders". That was true when
it was written; the demo slice added the route tree. What remained was that the
toolchain around it could not be trusted, in four ways that were all silent:

| Was | Now |
|---|---|
| No `pnpm-lock.yaml`, despite `packageManager: pnpm@9.7.0`. Nothing reproducible, and the web Dockerfile had been switched to npm as a workaround. | Committed. `pnpm install --frozen-lockfile` resolves 619 packages in ~16s and fails loudly on drift. Dockerfile back on pnpm with a cache-mounted store. |
| No ESLint config, so `next lint` asked an interactive question and **waited** — `turbo run lint` hung rather than failing. | `.eslintrc.js` committed; `next lint --max-warnings 0` is clean. |
| `pnpm-workspace.yaml` globbed `packages/*`: six empty directories, nothing tracked in Git, a warning on every install. | Glob narrowed to `apps/*`. They were never code. |
| `make verify` called itself "everything CI runs" while running no frontend test and no frontend build. | Runs both (`test-web`, `build-web`). |

`tsconfig.json` also gained `allowJs`, `esModuleInterop` and
`forceConsistentCasingInFileNames`, which Next silently rewrites into the file on
first lint or build — a clean checkout came back dirty. `strict` stays on.

**Verified:** frozen-lockfile install, lint clean, `tsc --noEmit` under strict,
`next build` emitting 8 routes, and **14 vitest tests** over the BFF session
helpers. Routes checked against a real API and a real production Next server:
signed out, `/` and `/leads` redirect to `/login` and an unknown path is 404;
signed in, every page is 200, the seeded lead is visible, and an unknown lead id
renders "Not found".

**Still open, and not P0-3:** the full route tree from the specification's
hierarchy (`(auth)`, `(onboarding)`, `(dashboard)/[tenantSlug]`, `(fullscreen)`),
the design system, and axe/a11y coverage. That is M05 product work — 15–25 days —
and none of it is a toolchain problem any more.

**Browser E2E:** Playwright config and the Acme-versus-Globex isolation spec are
ready and `make e2e` installs the browser and runs them. The browsers could not be
installed in the environment this was prepared in (`playwright install` needs root
for system libraries and the download was blocked), so the browser run itself is
**unverified here** and must be done on Windows.

---

### Local runtime hardening (2026-08-01)

**Naming:** this was requested as "P0-4" in a sprint prompt, but the P0-4 in this
document is *domain services*, which remains open and untouched. Recording it
separately rather than letting the two collide.

The launcher started four of the nine services. Postgres, Redis, the API and the
web app came up; the four worker pools and the Beat scheduler did not, so the
outbox relay never ran and anything queued simply sat there. The demo looked fine
because nothing in the visible flow needed a worker yet.

| Was | Now |
|---|---|
| Four services started; workers and Beat were never launched. | The full tier starts, and the launcher waits on Docker's own health state — workers expose no HTTP endpoint, so a URL probe could not have told you the tier was up. |
| Beat waited on `service_started`, which only proves a process was launched. | Waits for `service_healthy`. Beat fires the outbox relay every 500 ms; aimed at a pool that cannot reach PostgreSQL yet, that is a retry burst at every start. |
| `-Reset` sat one keystroke from the everyday command and dropped the volume. | Destruction moved to `RESET_DEMO.cmd` / `scripts/reset-demo.ps1`, which requires the word `reset` to be typed. Nothing on the ordinary path removes a volume. |
| No `ENCRYPTION_MASTER_KEY` anywhere in compose. | Set for the API and pools. MFA fails closed without one, so browser enrolment would have returned 422 the first time anyone tried it. |

**Verified end to end** against a real API, a real production Next server and the
real BFF, with the API receiving `Host: api:8000`: acme sign-in 200, create lead
201, appears in list, opens by id 200, edit 200, refresh shows the edit, globex's
list does not contain it, and globex opening acme's URL is 404 "Not found".

**Restart and idempotency:** re-running migrations, `seed.py` and `seed_demo.py` —
exactly what a second launch does — then signing in again showed the previously
created lead still present, its edit intact and the count unchanged. Nothing
wiped, nothing duplicated.

**Bounded waits, proved against a stub:** an unhealthy worker aborts in ~1s with
that service's logs; a container stuck in `starting` stops at the timeout instead
of spinning. `tests/e2e/test_local_stack_contract.py` pins all of this with 14
static assertions that need no Docker daemon.

**Still unverified here:** Docker itself is unavailable in the environment this was
prepared in, so `docker compose up` and the browser run must be done on Windows.

---

#### P0-4 · Domain services and endpoints — **contacts and accounts delivered 2026-08-01**

**Done:** `/v1/contacts` and `/v1/accounts` (list, search, create, read, update,
plus `GET /accounts/{id}/contacts`), built on the existing schema and domain
logic. Follows `application/leads/service.py`: `scoped_query`/`get_scoped` on
every read, `SqlAlchemyUnitOfWork` for state plus outbox, Pydantic boundary
schemas, ETag concurrency, and `AuditRecorder` writing inside the same
transaction — the first caller of the recorder, which had been dead code since
M04 (P1-2 is now partly discharged for these two resources).

Contacts link to accounts through `Contact.account_id`. The `account_contacts`
join table is left alone: it models a many-to-many with roles, which nothing in
this scope needs, and populating both would mean two sources of truth.

Contact and account outbox events reach **real handlers**, not `pending_handler`:
`sync_contact_company` stamps the account name onto a contact that has none, and
`propagate_account_rename` refreshes it when the account is renamed. Both are
idempotent, because the relay is at-least-once by construction.

**Verified:** 23 e2e tests on real PostgreSQL with RLS forced, covering the flow,
search, ETag conflict, cross-tenant denial for contacts *and* accounts, linking a
contact to another tenant's account (404), the outbox and audit rows committing
with the change, and handler idempotency. Live-checked through the real Next BFF
with the API receiving `Host: api:8000`: create account 201, create linked contact
201, list, open, edit, refresh persists, stale edit 412, search, and globex
getting 404 "Not found" for both of acme's records.

**Also done (2026-08-01): activities and notes.** Every contact and account now has
a timeline. Activities are append-only -- the model says so and no update or delete
route exists, because a logged call that can be rewritten later is not a record of
what happened. Notes are editable by their author only: `note:update` is not a
licence to rewrite a colleague's note under their name. `system` and
`status_change` cannot be logged by a client, so a system record cannot be forged.
A new handler stamps `last_contact_at` when a call, email, meeting or WhatsApp is
logged -- notes deliberately do not count, and the stamp only moves forward.
Verified by 16 further e2e tests and through the browser path.

**Also done (2026-08-02): deals, pipelines and tasks.** A tenant gets a default
pipeline lazily on first use. Stage moves go through the existing
`domain/deals/pipeline_policy.py` -- required fields, direction limits, loss
reasons, resulting status -- rather than a second copy of those rules; probability
and status come from the target stage, never from the client. The board reports
open, weighted and won totals using the domain's `weighted_pipeline_value`, which
excludes closed deals. Tasks hang off a contact, account or deal or stand alone;
overdueness is computed and filtered server-side against the database clock, and
`completed_at` is stamped by the server so "closed on time" stays answerable.
Completion emits `task.completed` rather than a generic update.

Fixed while building it: `DomainError` had no exception handler, so a broken
business rule became a 500 instead of a 422 -- it would have paged somebody for a
user error. See audit A30.

**Also done (2026-08-02): the shared inbox and appointments.**

*Inbox.* `app.messages` is partitioned by month with a composite key, so
`created_at` is supplied explicitly and the current month's partition is ensured
before any write — a test asserts the row landed in `app.messages_pYYYYMM`, not
just the parent. Outbound replies are persisted `queued` and stay there: nothing
marks them sent, nothing stamps a delivery time, and the response carries an
explicit note that the channel has no provider credential. `GET
/conversations/channels` reports readiness honestly. Inbound needs no credential
and lands on the same path real provider webhooks use after signature
verification.

*Appointments.* Double booking is refused by the `slot_locks` unique constraint
rather than a read-then-write check, and the appointment rolls back with its lock
so a refused booking leaves nothing behind. Cancelling deletes the lock (a
cancelled slot that stays locked can never be rebooked); rescheduling moves it.
Calendar sync stays gated on Google OAuth verification and `calendar_event_id`
stays null.

**P0-4 is complete:** documents/files and analytics now follow the same scoped
service, permission, RLS, audit/outbox and real-Postgres proof pattern. Storage-
backed upload and export transports remain external P0-5 activation gates; their
disabled paths never return placeholder files, keys or URLs.

---

#### (original entry) Domain services and endpoints missing for six modules
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
| ~~P1-1~~ | **RESOLVED 2026-08-02.** Every public repository read requires `EffectivePermissions`; unscoped builders are private and architecture-tested (`1c07f0b`). | criteria 2, 4 | Complete | — |
| P1-2 | **Complete for implemented mutation surfaces.** Auth, leads (including atomic bulk status/assignment), AI, CRM, consent, provider/config, file downloads, analytics exports, tenant governance, workflow controls/execution, public booking, authorization denials, verified payment transitions, and support access are durably audited. Bulk updates are role-scoped, bounded, durably idempotent after Redis loss, and commit state, audit, and outbox together. Provider secrets are tenant-envelope-encrypted and never returned or audited. Support access is tenant-approved, read-only, MFA-step-up protected, time-bound, RLS-isolated, and revoked fail-closed. | criterion 22 | Keep mutation-audit contract tests mandatory as new surfaces are added | regression gate |
| ~~P1-3~~ | **RESOLVED 2026-08-02.** Owned warning/critical Prometheus rules, AWS backup/WAF alarms, runbooks and deterministic validation are committed (`24676fe`). Live AWS firing remains correctly gated by P0-5. | M02, M21, criterion 27 | Complete | — |
| P1-4 | **Engineering complete; live evidence externally blocked.** The fail-closed PITR orchestrator verifies migration head, reconciles counts, re-runs the RLS suite using a temporary NOBYPASSRLS role, enforces RPO/RTO, uploads evidence and tag-verifies cleanup. The private DR runner/account is not activated, so no drill is claimed. | M22, criterion 24 | Activate the documented AWS DR environment and execute the drill | AWS gate |
| ~~P1-12~~ | **RESOLVED 2026-08-02.** Published definitions now match durable domain events into idempotent executions; approval requests and assignee-bound decisions persist atomically with audit/outbox evidence and resume only after the configured any/all/quorum policy resolves. Existing outbound delivery, action authorization, durable action receipts and delay continuation remain intact. | M18, criteria 16, 27 | Complete | — |
| ~~P1-5~~ | **RESOLVED 2026-08-02.** Eight concurrent public claims on one real-Postgres slot produce exactly one booking/lock/audit commit and seven domain conflicts; the audit is anonymous, PII-free and tenant-isolated (`2097ba2`). | criterion 12 | Complete | — |
| P1-6 | **Engineering complete; live evidence externally blocked.** Presign → verified HEAD completion → SHA/magic/active-content inspection → clamd INSTREAM → clean/quarantine/reject → audited five-minute signed download is wired with durable outbox dispatch and retry-safe state. Real-Postgres lifecycle tests and a TCP clamd protocol test pass; no AWS bucket or deployed clamd exists on this host, so activation is not claimed. | M13, criterion 13 | Execute the storage activation runbook against private staging S3 and real clamd, including EICAR evidence | AWS gate |
| ~~P1-7~~ | **RESOLVED 2026-08-02.** Runtime/dev Python graphs are fully pinned with hashes and used by CI/Docker; pnpm CI installs fail on lock drift (`784cbfc`). | M01, M21 | Complete | — |
| ~~P1-8~~ | **RESOLVED 2026-08-02.** Every AI task has immutable Git-backed `prompts/<task>/v<n>.yaml` content and a versioned gold set. Platform-only, durably idempotent sync/evaluate/promote/rollback endpoints commit audit/outbox evidence atomically; runtime calls fail closed until a passing version is promoted. The CI runner executes deterministic prompt/guard contracts without contacting or claiming quality from a provider. | M12, criterion 6 | Complete; approved sandbox model-quality evaluation remains an external activation activity | — |
| P1-9 | **Coverage below the stated bars** in `application/*` (0–92% against a 90/85 target); several modules at 0%. | M21 | Raise to bar or record a per-module exception with an owner | 3 days |
| P1-10 | **Provider credentials absent** — WhatsApp BSP + template approval, email provider + domain, Razorpay commercial model. Adapters are complete and mock-tested; none has touched a live endpoint. | M15–M17, criteria 8, 15 | Follow `docs/runbooks/provider-activation.md` per provider | external |
| P1-11 | **k6 and ZAP never executed**; `peak.js` missing. | M21, criterion 23 | Run against staging once P0-5 clears; add the peak and spike profiles | 2 days + AWS |

---

## P2 — before GA, not before pilot

| # | Item | Remediation |
|---|---|---|
| P2-1 | Python version deviation (spec 3.12, project `>=3.10` with a `StrEnum` shim) | Adopt 3.12 and delete `shared/compat.py`, or record the deviation |
| P2-2 | Onboarding state machine missing (`GET/PATCH /onboarding/state`, `POST complete`) | Implement over the existing `tenants.onboarding_state` column |
| ~~P2-3~~ | **RESOLVED 2026-08-02.** Kill switches persist on workflow definitions, survive Redis loss, and emit audit/outbox events (`9d2c8f2`). | Complete |
| ~~P2-4~~ | **RESOLVED 2026-08-02.** Verified Razorpay events are durably persisted, tenant-derived from stored order/payment mappings, atomically transitioned/audited/outboxed, and duplicate-safe without Redis (`a2e45df`). | Complete |
| P2-5 | Mutation testing absent despite a stated 75–85% target | Add `mutmut`/`cosmic-ray` for domain and auth |
| P2-6 | `mypy` excludes `tests/` | Extend strict checking to tests |
| P2-7 | No tracing despite X-Ray in the stack table | Instrument with OpenTelemetry |
| P2-8 | Storybook declared in the Makefile, absent | Add it or drop the claim |
| P2-9 | Only `envs/prod` exists | Add dev/staging/sandbox stacks |
| P2-10 | Missing referenced files: `generate_evidence.py`, `zap/rules.tsv`, `k6/peak.js` | Create them or remove the references from CI and the Makefile (`verify-restore.sh` and `run_ai_evals.py` are now implemented) |

---

## Summary

| Priority | Code gaps | External gates | Total |
|---|---:|---:|---:|
| P0 | 0 | 2 | 2 |
| P1 | 4 | 3 | 7 |
| P2 | 8 | 0 | 8 |

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
