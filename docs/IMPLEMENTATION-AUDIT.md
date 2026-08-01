# Implementation audit — AI RevenueOS

**Audit date:** 2026-08-01
**Source of truth:** `AI-REVENUEOS-IMPLEMENTATION-SPECIFICATION.md`
**Verdict: NOT GA-ready.** The backend domain, security, persistence and **worker**
core is substantially real and independently verified. The frontend cannot be built,
there are no authentication endpoints, six modules have no service layer, and every
provider integration is unactivated. GA is blocked by 5 P0 items, of which 3 are
code gaps and 2 are external gates.

> **Update 2026-08-01 — demo vertical slice.** One tenant-scoped CRM flow now runs
> end to end in a browser: sign in (Argon2id + RS256, no bypass) → list → create →
> open → edit → refresh, with a second tenant provably unable to reach the first
> tenant's record. This is a narrow slice between P0-1 and P0-2, not P0-2 itself:
> only `/v1/auth/{login,refresh,logout,me}` exist; signup, MFA, Google OAuth,
> password reset, API keys and session management remain open.
> Evidence: `docs/demo-slice-evidence.txt`. Suite 726 → **739 passing**.
>
> Five real defects were found and fixed while making it work, listed in
> `docs/RELEASE-BLOCKERS.md` under "Demo slice".
>
> **Update 2026-08-01 — P0-1 (worker tier) is RESOLVED.** `infrastructure/celery/`
> now exists with all 8 queues, tenant-safe header context, retry classification,
> three idempotency layers, durable dead lettering with replay, Beat schedules at
> the specified cadences, and worker health checks. Verified by 34 integration
> tests against real PostgreSQL 16, real Redis 6.2 and a real Celery worker.
> Suite 692 → **726 passing**. Evidence: `docs/p0-1-gate-results.txt`.

This audit deliberately contradicts several claims in the previously delivered
`docs/ACCEPTANCE-EVIDENCE.md`. Where an earlier claim could not be substantiated it
is marked **OVER-CLAIMED** with the correction.

---

## 1. Gate results (raw)

Commands were run from `backend/` unless stated. Verbatim output:

```
AI RevenueOS - release-readiness gate run
date:   2026-08-01T11:22:27Z
python: Python 3.10.12 | ruff 0.16.1 | mypy 1.20.2

ruff check                   All checks passed!
ruff format --check          174 files already formatted
mypy (strict)                Success: no issues found in 139 source files
import-linter                Contracts: 6 kept, 0 broken.
bandit (SAST)                No issues identified (High 0 / Medium 0 / Low 0), 12425 LOC
pip-audit (project)          No known vulnerabilities found
migration safety             migration safety: 2 migration(s) verified
release gates                8/8 release gates passed
migration up/down/up         OK (0001..0002 reversible, verified on PostgreSQL 16)
tests: unit                  503 passed
tests: integration           19 passed
tests: contract              146 passed
tests: e2e                   24 passed
tests: TOTAL                 692 passed, 0 failed (2 consecutive clean runs)
coverage                     TOTAL   6949 stmts   938 miss   1248 branch   170 partial   84%

FRONTEND
pnpm install                 BLOCKED - no pnpm-lock.yaml
next build                   BLOCKED - no next.config, tailwind.config, postcss.config, next-env.d.ts
pnpm typecheck               NOT RUN - no node_modules; 3 dependency-free modules pass tsc --strict
pnpm test / a11y             NOT RUN - no vitest/playwright config, zero test files
```

Reproduce:

```bash
cd backend
ruff check src tests && ruff format --check src tests
mypy --cache-dir=/tmp/mypycache
PYTHONPATH=src lint-imports --config .importlinter
bandit -r src -f txt
pip-audit -r <(python -c "import tomli,pathlib;d=tomli.loads(pathlib.Path('pyproject.toml').read_text());print(chr(10).join(d['project']['dependencies']+[x for v in d['project']['optional-dependencies'].values() for x in v]))")
PYTHONPATH=src python src/scripts/check_migration_safety.py
PYTHONPATH=src python src/scripts/verify_release_gates.py
pytest
```

### 1.1 State before this audit

The delivered tree did **not** pass its own declared gates:

| Gate | Before | After | Note |
|---|---|---|---|
| `ruff check` | **336 errors** | 0 | 213 autofixed; 15 fixed by hand; 2 rules documented as deliberate |
| `ruff format --check` | **127 files unformatted** | 0 | `make lint` would have failed on a clean clone |
| `mypy` strict | **crashed**, then **35 errors** | 0 | crash was a sqlite cache on a mounted FS; the 35 were real |
| `import-linter` | **never ran** | 6/6 kept | config used comma-separated INI lists; the tool exited before evaluating anything |
| Architecture layering | **3 real violations** | 0 | see §3 |

The architecture gate is the most significant: `docs/adr/0001` claimed layering was
"enforced mechanically by import-linter". It was not — the contract file was
malformed, so CI would have reported a tool error, and genuine violations had
accumulated behind it.

---

## 2. Defects found and fixed during this audit

All are fixed, tested and included in this commit.

| # | Severity | Defect | Evidence it is fixed |
|---|---|---|---|
| A1 | **P0 security** | `accept_custom_webhook` checked only that a signature header was *present*, never verified it. `verify_signature` was dead code and `webhook_id` was unused, so any caller could inject workflow triggers into any tenant. | `tests/contract/test_custom_webhook_ingress.py` — 16 tests incl. wrong secret, tampered body, expired/future timestamp, malformed header, unknown id indistinguishable from bad signature |
| A2 | **P1 security** | `TenantRepository.apply_scope` was **dead code** — called from nowhere. Branch/team/self scope was not enforced on any list query, so a self-scoped Member saw every lead in the tenant. | `tests/e2e/test_role_scope_enforcement.py::TestSelfScope`, `TestTeamAndBranchScope` |
| A3 | **P1 security** | Even if wired, `apply_scope` was wrong: `self` scope filtered `assignee_id` against **team** ids, and `EffectivePermissions` carried no user id. `stmt.where(False)` passed a Python bool rather than `sqlalchemy.false()`. | `EffectivePermissions.user_id` added; `TestScopeFailsClosed` proves empty scope returns nothing |
| A4 | **P1 security** | In-tenant IDOR: `get()`/`get_or_404()` filtered by tenant only, so a self-scoped principal could read or update any record by id. | `get_scoped()`/`get_scoped_or_404()` added and wired; `TestObjectLevelScope` — 4 tests incl. out-of-scope and absent being indistinguishable |
| A5 | **P1 security** | `audit.audit_logs` carries `tenant_id` but was never registered for RLS — the audit trail was cross-tenant readable by any query missing an explicit predicate. | migration `0002`; `test_every_table_carrying_a_tenant_id_enforces_rls` |
| A6 | **P1 security** | Partition children do not inherit RLS. `app.messages_p*` and `audit.audit_logs_p*` were unprotected; a direct read of a partition bypassed the parent policy. | migration `0002` + `ddl.partition_rls()` so future partitions are created protected; `test_partition_children_are_individually_protected` |
| A7 | **P1 correctness** | `POST /v1/leads` with `assignee_id` crashed: Pydantic hands the service real `UUID` objects and they were written straight into a JSONB column. | `_json_safe()` in `application/leads/service.py`; exercised by every scope test |
| A8 | P2 | The RLS assertion was partly vacuous: `if t in state` silently skipped any registered table absent from the database. | test now asserts `absent == []` first |
| A9 | P2 | `LeadService.list` shadowed the builtin `list` inside the class body, so every `list[...]` annotation in that scope resolved to the method (2 mypy errors). Renamed `list_leads`. | mypy clean |
| A10 | P2 | `evaluate_condition` `between` unpacked a non-sequence; only the surrounding `except TypeError` prevented a crash. | explicit length/type guard |
| A11 | P2 | Order-dependent test: a type-filtered outbox handler asserted it received *every* dispatched event. Passed alone, failed in the full suite. | assertion made order-independent |
| A12 | P2 tooling | `ruff target-version = py312` contradicted `requires-python = ">=3.10"`; autofix rewrote the `UTC` shim into 3.11+-only syntax and broke the tree. | aligned to `py310`; see §7 deviation D1 |
| A13 | P2 tooling | `mypy` and `coverage` crash on the mounted filesystem (sqlite cache). | documented; `--cache-dir` / `COVERAGE_FILE` workaround in §8 |
| A14 | **P1 packaging** | The `web` image could not build on a host that had ever run `npm install`: with no root `.dockerignore`, `COPY . .` merged the host's `apps/web/node_modules` over the tree installed in the image, and the daemon aborted with `cannot copy to non-directory: .../node_modules/@playwright/test`. The Dockerfile also ran `pnpm install --frozen-lockfile` against a lockfile that does not exist. | root `.dockerignore` and `backend/.dockerignore` added; Dockerfile moved to npm with a committed `apps/web/package-lock.json`; exclusion rules verified by replaying moby's pattern matcher over the real tree (`node_modules`, `.next`, `__pycache__`, `.venv`, caches, coverage, `.dev-keys` excluded; all source and lockfiles kept) |
| A16 | **P0 usability** | The launcher printed credentials that could not sign in. `TrustedHostMiddleware` defaults to `localhost,127.0.0.1,testserver`, but the BFF reaches the API as `http://api:8000`, so every request arrived with `Host: api` and was answered `400 Invalid host header` **before authentication ran**. The BFF could not parse that plain-text body, so `payload` was null and the browser showed the generic `Sign in failed.` The container reported healthy throughout, because its own probe calls `localhost`. Argon2, the seed and the credential were never at fault. | `TRUSTED_HOSTS` set in compose; `tests/e2e/test_launcher_demo_login.py` — 8 tests that read the hostname out of `docker-compose.yml`, seed with a launcher-generated password and sign both demo users in over `Host: api`. Removing the fix fails 6 of them. Reproduced and re-verified through the real Next.js BFF with the API receiving `Host: api:8000` |
| A17 | P1 diagnosability | Any non-401 upstream response collapsed into `Sign in failed.` with nothing logged, which is why A16 was invisible from outside the container. | the BFF now reads the body once as text and logs unexpected upstream statuses; `docker compose logs web` shows `[auth] upstream ... returned 400: Invalid host header`. The credential is never logged |
| A18 | P1 process | `scripts/demo.ps1` announced success on container health alone — exactly the evidence A16 proved worthless. | the launcher now signs both demo users in through the web app before printing anything, and exits non-zero without the ready banner if either fails |
| A15 | P2 | Order-dependent test, same class as A11: the worker isolation test asserted tenant B owned *zero* leads. `migrated_database` is session-scoped and `tests/e2e/test_lead_lifecycle.py` legitimately gives tenant B a lead, so the assertion passed alone and failed in a full-suite run — while saying nothing about isolation. | rewritten as a delta: tenant A's count rises by exactly one and tenant B's is unchanged. RLS itself was never at fault; the previously failing order now passes |

---

## 3. Architecture conformance

The spec mandates `API -> application -> domain <- infrastructure` with
infrastructure implementing domain/application ports.

**Violations found once the gate was made to run:**

1. `application.{ai,communications,payments}.registry -> api.app.settings` — the
   application layer imported the HTTP layer.
2. `infrastructure.{database.session,caching.redis} -> api.app.settings` — same.
3. `api.app.factory -> sqlalchemy` — the HTTP layer imported the ORM directly for a
   readiness probe.

**Remediation applied:**

- `Settings` moved to `shared/settings.py`. Configuration is not an HTTP concern and
  is needed by application services, infrastructure adapters, workers and the
  scheduler. `api/app/settings.py` remains as a thin re-export for the HTTP layer.
- The database and cache readiness probes moved into
  `infrastructure/database/session.py::ping` and
  `infrastructure/caching/redis.py::ping`.
- The `layers` contract was corrected. The original contract placed infrastructure
  *below* application, which forbade `infrastructure -> application.ports` — a
  dependency the specification explicitly requires ("implements domain/application
  ports"). It is now `api > application > domain > shared`, with two `forbidden`
  contracts asserting that neither infrastructure nor application may import `api`.

Result: `Contracts: 6 kept, 0 broken` over 184 files and 690 dependencies.

---

## 4. Milestone traceability M01–M24

Status: **IV** implemented and verified · **IU** implemented but unverified ·
**P** partial · **M** missing · **XB** externally blocked.

| M | Title | Status | Evidence | Gap |
|---|---|---|---|---|
| M01 | Repository and local foundation | **P** | `backend/src/api/app/factory.py`, `settings.py`, middleware trio, `/health*`, `Makefile`, `docker-compose.yml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`; app boots with 36 OpenAPI paths | "clean clone runs locally and CI gates pass" is **unmet**: no `pnpm-lock.yaml`, so `pnpm install --frozen-lockfile` fails; Storybook is declared but absent |
| M02 | Environments, IaC, CI/CD, observability | **P / XB** | `infra/terraform/modules/{network,data,edge}` (598 lines HCL), `envs/prod`, 3 workflows | Terraform **never `init`/`validate`d** (no AWS account, no provider download). Only `envs/prod` exists — dev/staging/sandbox are referenced by `deploy.yml` but absent. `infra/scripts/verify-restore.sh`, `infra/zap/rules.tsv`, `infra/k6/peak.js` referenced by CI but **missing** |
| M03 | Database, migrations, outbox, tenancy | **IV** | 104 tables / 4 schemas; migrations `0001`+`0002` verified up→down→up on PostgreSQL 16; RLS enforced+forced on 95 tables incl. partitions; `SqlAlchemyUnitOfWork` commits state+outbox in one transaction; `OutboxDispatcher` with `SKIP LOCKED`, backoff, DLQ. 19 integration tests | — |
| M04 | Auth, sessions, RBAC, security | **P** | Argon2id `m=65536,t=3,p=4`; RS256+JWKS with `alg=none`/HS-confusion rejection; refresh rotation with family-reuse revocation; TOTP + bcrypt recovery codes; envelope encryption KMS→KEK→DEK; role matrix; sliding-window limiter. 90 tests | **No auth endpoints exist.** `/v1/auth/*` (signup, login, refresh, logout, MFA, Google OAuth, sessions, API keys) is entirely absent — the primitives are built and tested, the surface is not. The BFF proxy calls `/v1/auth/refresh`, which 404s |
| M05 | Design system and app shell | **P** (was M) | Now builds and runs: `next build` succeeds, 8 routes, login + leads list + lead detail/edit render against the live API. Still missing the full route tree, component library, Storybook and a11y automation | see P0-3 |
| ~~M05 (old row)~~ | Design system and app shell | ~~M~~ | 9 TS/TSX files (~560 lines): layout, BFF proxy, query-key scoping, tenant switch, 2 feature components | **Zero `page.tsx`** — no route renders. No Next/Tailwind/PostCSS config, no `next-env.d.ts`, no lockfile, no Storybook, no component tests. `next build` cannot run |
| M06 | Onboarding, templates, plans | **IV** | 8 mandatory + 1 generic template as versioned JSON; `apply_template` preserves customisation and rejects guardrail weakening; 3 plans with documented limits. 105 tests | Onboarding **state machine** (`GET/PATCH /onboarding/state`, `POST complete`) not implemented; only `POST /onboarding/apply-template` exists |
| M07 | CRM foundation | **P** | Schema complete: contacts, accounts, activities, tasks, notes, tags, custom fields, saved views, SLA. Constraints and partial unique indexes verified | **No CRM service or endpoints.** No contact/account CRUD, merge, timeline, import/export. Schema only |
| M08 | Leads, forms, dedupe, assignment | **P** | `LeadService` (capture, get, update, duplicates, qualify, review, convert) now role-scoped; dedupe with confidence banding; source events always preserved. 24 E2E tests | Form builder/publish, CSV import, webhook capture, assignment-rule execution not implemented. `POST /leads/bulk`, `/deduplicate`, `/merge`, `/assign`, `/disqualify`, `/restore` absent |
| M09 | Deals, pipelines, tasks, SLA | **P** | `pipeline_policy` and `sla_policy` domain logic verified incl. business hours, holidays, DST. 27 tests | **No deal/pipeline/task service or endpoints.** No SLA escalation worker (no worker tier at all) |
| M10 | Consent, preferences, inbox | **P** | `evaluate_send` — single decision point over opt-out, suppression, consent, quiet hours (midnight-wrapping), frequency caps, budget, deliverability, WhatsApp 24h window. 33 tests | **No inbox service or endpoints.** No conversation/message CRUD, assignment, handoff, realtime. Schema only |
| M11 | Branded webchat | **P** | Schema + origin enforcement middleware; `TestCors` proves enforcement | No widget service, no public chat endpoints, no embeddable widget asset |
| M12 | AI gateway, prompts, qualification | **P** | Provider-neutral gateway, pinned models, policy routing with fallback chains, circuit breakers (Anthropic 3/15s), input+output guards, per-task degradation, usage metering, budget stop, tool-loop limits. 96 tests | **Prompt governance is absent**: `prompts/` is empty though the spec mandates Git-backed `prompts/<task>/v<n>.yaml`; no promote/rollback endpoints; no evaluation runner (`run_ai_evals.py` referenced by CI, missing) |
| M13 | Documents, extraction, RAG | **P** | File-security suite verified (MIME allowlist, magic bytes, double extension, SVG/PDF active content, zip ratio, CSV injection, scan-gated download, cross-tenant refusal). pgvector schema with HNSW `m=16, ef_construction=200` | No document service or endpoints; no presign/complete flow wired; **ClamAV scanner raises `NotImplementedError`**; no chunking/embedding/retrieval implementation |
| M14 | Appointments and calendar | **P** | Slot computation verified incl. buffers, capacity, notice, horizon, DST skip. `claim_public_slot` maps `IntegrityError`→409. 13 tests | `claim_public_slot` has **0% test coverage** and no concurrency test; no reminder worker; calendar port unimplemented |
| M15 | Email channel | **P / XB** | Port + bounce/complaint normalisation across SES and SendGrid shapes; flag off | `send()` raises `NotImplementedError`. Blocked on provider decision + domain ownership |
| M16 | WhatsApp channel | **P / XB** | Cloud API adapter, HMAC verification, replay window, challenge, template payloads, status mapping, opt-out keywords. 26 contract tests against `httpx.MockTransport` | No template sync job, no delivery reconciliation job (no worker tier). Blocked on BSP + template approval |
| M17 | Payments and invoices | **P / XB** | Server-side amount authority, state machine, refund authorisation with MFA threshold, HMAC webhook + handback verification, card-data stripping. 40 tests | No invoice/payment-link service or endpoints; **no reconciliation job** (spec: every 30 min). Blocked on Razorpay commercial model |
| M18 | Workflow engine and n8n isolation | **P** (was P, materially advanced) | DSL + executor (80 tests). **Worker tier now real**: `infrastructure/celery/` with 8 queues, tenant-header context, retry classification, idempotency, DLQ + replay, Beat scheduler, health checks — 34 integration tests on real Postgres/Redis/Celery | Concrete workflow **action handlers** and the outbound webhook **HTTP transport** are still stubs reporting `pending_handler`/`pending_transport`. Version/execution persistence service still absent |
| M19 | Voice | **IV (as disabled)** | 7 independent `VoiceControls`; flag alone cannot enable; `place_call` refuses and enumerates outstanding controls. 5 tests | Correctly disabled. Blocked on provider + legal |
| M20 | Analytics and exports | **P** | 4 rollup tables; timezone-correct day bounds verified | **No analytics service, no endpoints, no rollup jobs, no export worker.** Schema only |
| M21 | Security, quality, performance | **P** | 692 tests, 84% coverage, bandit clean, pip-audit clean, 6/6 architecture contracts, migration-safety gate | k6 profiles **never executed** (no environment); ZAP never run; no mutation testing despite a stated 75–85% target; `peak.js` missing |
| M22 | Resilience and DR | **P** | Degradation paths tested (circuit breaker, provider outage, Redis-down cache bypass); runbook written | **No drill performed.** `verify-restore.sh` referenced by the nightly workflow does not exist. No measured RPO/RTO |
| M23 | Controlled pilots | **M** | Pilot cohort flag exists | No pilot tenants, no telemetry, no acceptance suite, no feedback process |
| M24 | General availability | **M** | — | Cannot be assessed: prerequisites unmet |

**Summary:** 3 verified (M03, M06, M19), 17 partial, 3 missing, 1 not assessable.

---

## 5. Global acceptance criteria (30)

| # | Criterion | Status | Evidence / gap |
|---|---|---|---|
| 1 | Eight templates onboard by configuration only | **IV** | `tests/unit/test_industry_templates.py` 80 cases; `test_no_industry_specific_code_module_exists`; release gate 1 |
| 2 | Tenant isolation across all surfaces | **P** | **Verified** for REST, service layer, DB (RLS enforced+forced on 95 tables incl. partitions after `0002`), cache (`tenant_key` namespacing). **Unverified**: WebSocket/SSE (not implemented), workers (do not exist), analytics (no queries), object storage (no wired flow), support access (no endpoints), exports (no worker) |
| 3 | Duplicate capture preserves source event | **IV** | `test_duplicate_capture_preserves_both_source_events`; `TestDedupe` 9 cases |
| 4 | Assignment/next-action/task/SLA queues under role and team scope | **P** | **Previously OVER-CLAIMED as evidenced.** `apply_scope` was dead code. Scope is now enforced and tested for leads (12 tests). Tasks, next actions and SLA queues have no service, so remain unverified |
| 5 | Lead/SLA status visible and accurate | **P** | Lead lifecycle verified. SLA state machine verified as pure logic; no persistence or escalation worker |
| 6 | AI qualification returns score/evidence/reasons/missing fields with human accept/edit/reject/defer | **IV** | `TestQualification` 17 cases; `test_human_review_overrides_and_is_persisted`; emits `lead.qualified` |
| 7 | AI/provider/guard failure leaves a manual path, never blocks CRM | **IV** | Full E2E suite passes with zero AI credentials; `test_ai_qualification_degrades_to_the_rule_engine_without_credentials` |
| 8 | WhatsApp signature-verified, idempotent, tracked, retried, no duplicate contact | **P / XB** | Adapter verified against mock transport (26 tests). No delivery-tracking persistence, no retry worker. Live proof blocked on BSP |
| 9 | Opt-out/revocation blocks queued and running work | **P** | Policy verified (`TestHardStops`). "Queued and running work" cannot be verified: no queue exists |
| 10 | Handoff transfers context, ownership, automation-stop | **P** | `automation_stopped` blocks automated but not human sends (tested). No handoff endpoint or service |
| 11 | Webchat restricts domains/origins, safe sessions, handoff | **P** | Origin enforcement tested. No webchat service or public endpoints |
| 12 | Concurrent booking cannot double-book | **P** | Unique constraint exists in `0001`; `claim_public_slot` maps `IntegrityError`→409 but is **0% covered** and no concurrency test exists. Mechanism present, behaviour unproven |
| 13 | Files tenant-private, scanned before use, no cross-tenant download | **P** | 18 file-security unit tests pass. **No storage flow is wired**; `ClamAvScanner.scan` raises `NotImplementedError`. Policy verified, pipeline absent |
| 14 | Extraction shows provenance and requires confirmation | **P** | Schema constrains `review_state`; no extraction implementation |
| 15 | Razorpay server-derived amount, HMAC + idempotency, no card data | **P / XB** | 40 tests incl. amount-tamper refusal and card stripping. No reconciliation job. Blocked on merchant credentials |
| 16 | Workflow DSL validate/test/publish/run with idempotency, retry, DLQ | **P** | DSL + executor verified (80 tests). **No persistence, no queues, no DLQ writer, no scheduler** |
| 17 | Pause/kill/replay/approval/rollback audited, no duplicate external effect | **P** | In-process semantics verified. Kill switch writes to Redis only; no durable audit of the action |
| 18 | n8n authoring-only, no production execution path | **IV** | ADR 0004; compose profile off by default with `NODES_EXCLUDE` removing shell/file/db/ssh/http nodes; DSL rejects every escape vector (`TestExpressionSandbox`) |
| 19 | Dashboards correct with definitions and drilldown | **M** | Rollup tables only. No queries, no endpoints, no UI |
| 20 | Export entitlement/role checked, async, private, auditable, isolated | **P** | Step-up MFA enforced on `POST /tenant/export` (tested). Endpoint returns a stub; no export worker, no S3 write, no audit record |
| 21 | Revoke/deactivation/ownership transfer constrain access immediately | **P** | Refresh-family revocation and `jti` blocklist verified. No user-management or ownership-transfer endpoints |
| 22 | Audit reconstructs actor/action/correlation/resource | **P** | `AuditRecorder` exists with append-only DB trigger and is now RLS protected. **0% test coverage; not called from any code path** |
| 23 | Performance and noisy-tenant SLOs | **IU** | `infra/k6/normal.js`, `noisy-tenant.js` written; never executed |
| 24 | Backup/restore RPO ≤15m, RTO ≤4h | **IU** | Terraform sets PITR + 30-day retention. No drill; `verify-restore.sh` missing |
| 25 | WCAG 2.2 AA with screen-reader/keyboard verification | **M** | Primitives present in `layout.tsx`/`globals.css` (skip link, dual live regions, 44px targets, contrast tokens, reflow, reduced motion). **No page renders**, axe never run, no manual verification |
| 26 | Voice disabled until all controls signed off | **IV** | `TestVoiceIsHardDisabled` 5 cases |
| 27 | Provider outage degrades safely with queue/manual/reconcile + alerting | **P** | Circuit breaker and degradation verified (7 tests). "Queue" and "reconcile" unverifiable without workers. Alert rules not defined anywhere |
| 28 | Feature/tier/plan/quota consistent across UI, API, workers, billing | **P** | One implementation serves API (25 unit + contract tests). No UI, no workers, no billing to be consistent with |
| 29 | All eight templates enforce prohibited-domain guardrails | **IV** | `TestIndustryProhibitions` 10 cases; guardrails immutable under tenant customisation |
| 30 | Privacy access/export/delete, consent evidence, retention/hold | **P** | Schema complete (`privacy_requests`, immutable `consent_records` with withdrawal chaining, retention encoded in partitions/lifecycle). No DSR service, no endpoints, no retention job |

**Tally: 8 verified · 19 partial · 2 missing · 1 unverified.**
The prior evidence matrix claimed 20 evidenced. That count was inflated: it credited
schema and pure-domain logic as end-to-end evidence, and in criterion 4 it cited a
method that was never called.

---

## 6. Integration inventory — mocked, flagged, sandbox-only, credential-dependent

| Integration | State | Flag default | Behaviour without credentials | Test method |
|---|---|---|---|---|
| WhatsApp Cloud API | Adapter complete, unactivated | `FEATURE_WHATSAPP_ENABLED=false` | `send()` returns `ok=False, queued=True, PROVIDER_NOT_CONFIGURED` | `httpx.MockTransport`, 26 tests |
| Email (SES/SendGrid) | **Port only — `send()` raises `NotImplementedError`** | `FEATURE_EMAIL_ENABLED=false` | queued with activation prerequisite | webhook parsing tested; send path untested |
| Razorpay | Adapter complete, unactivated | `FEATURE_PAYMENTS_ENABLED=false` | order queued for reconciliation | `httpx.MockTransport`, 12 tests |
| Voice (Exotel/Twilio) | **Hard disabled by 7 controls** | `FEATURE_VOICE_ENABLED=false` | `FEATURE_NOT_AVAILABLE` + outstanding controls | 5 tests |
| Anthropic / OpenAI / Google | **Client raises `NotImplementedError`** | `FEATURE_AI_ENABLED=true` (safe) | gateway degrades per task; never fabricates | in-memory fake client, 96 tests |
| S3 storage | `boto3` calls written, **never executed** | n/a | n/a | validation helpers tested; no S3 interaction test |
| ClamAV | **Raises `NotImplementedError`** | `CLAMAV_HOST` unset | file stays `pending`, download refused | refusal tested |
| Google OAuth / Calendar | **Not implemented** | `FEATURE_CALENDAR_SYNC_ENABLED=false` | n/a | none |
| Signatures | **Schema only** | `FEATURE_SIGNATURES_ENABLED=false` | n/a | none |
| n8n | Compose profile, off by default | `FEATURE_N8N_AUTHORING_ENABLED=false` | not started | isolation asserted by config + DSL tests |
| Redis | Real client; `fakeredis` in tests | n/a | cache fails open, correctness unaffected | 146 contract tests |
| PostgreSQL | **Real**, via `pgserver` in tests | n/a | n/a | 43 integration + E2E tests against PostgreSQL 16 |

**No integration has been exercised against a live third-party endpoint.**

---

## 7. Security review

### 7.1 Tenant isolation and RLS — **strong, now that gaps are closed**

Two independent layers, both verified against a live PostgreSQL 16:

- Repository filter (`base_query`) applies `tenant_id` before execution;
  constructing a repository without a tenant raises.
- RLS `ENABLED` **and `FORCED`** on 95 tables. Verified allow path, deny path,
  cross-tenant `INSERT` rejection, and `UPDATE` that attempts to move a row between
  tenants.

The load-bearing detail: the application must **not** connect as superuser or table
owner — `BYPASSRLS` and ownership both silently defeat `FORCE ROW LEVEL SECURITY`.
Migration `0001` creates `airevenueos_app` (`NOBYPASSRLS`, non-owner) and the test
suite connects as a role inheriting it, so the policies are genuinely exercised.

Gaps closed by this audit: `audit.audit_logs` had no RLS at all (A5); partition
children were unprotected because PostgreSQL does not propagate RLS to partitions
(A6). `ddl.partition_rls()` now protects partitions at creation time so the gap
cannot reopen when the maintenance job adds next month's partition.

Remaining platform-scoped tables are enumerated in an explicit allowlist inside the
test, each with a stated reason: `app.tenants`, `app.prompts`,
`app.ai_evaluation_{sets,runs}`, `app.feature_overrides`, `audit.event_outbox`,
`audit.idempotency_records`.

### 7.2 IDOR — **was present, now fixed for leads; unproven elsewhere**

`get()`/`get_or_404()` filtered by tenant only. A self-scoped Member could read or
update any lead by id (A4). `get_scoped()`/`get_scoped_or_404()` now apply the role
predicate, and out-of-scope reads are indistinguishable from absent records.

**This is only fixed where a service exists — leads.** Every other module has no
service layer, so when contacts, deals, conversations, documents and appointments
are implemented they must use `scoped_query`/`get_scoped`. Recommendation: make the
unscoped variants private and require an explicit `EffectivePermissions` argument so
the safe path is the only path.

### 7.3 Worker and cache scoping — **now verified** (was: workers did not exist)

`src/infrastructure/celery/` exists and is exercised by 34 integration tests against
a real broker and a real worker.

Tenant safety in the worker rests on three properties, each with a test:

1. **Context travels in message headers, not the payload.** Task code cannot rewrite
   its own provenance, and a dead-letter replay keeps the original tenant.
2. **A tenant-scoped task refuses to run without a tenant header.** Platform work
   must opt out explicitly with `tenant_scoped=False`, so an unscoped worker is
   always a deliberate, reviewable decision
   (`test_tenant_scoped_task_refuses_to_run_without_a_tenant`).
3. **The bound tenant drives RLS inside the worker exactly as in the API** —
   proven by running the same query under two tenants and asserting tenant B sees
   zero of tenant A's rows (`test_a_worker_sees_only_its_bound_tenants_rows`).

The outbox poller remains deliberately unscoped: it must observe every tenant. It
now runs as a Beat-driven task every 500 ms rather than a bespoke process.

Three privilege tiers are now distinct, and the database enforces the separation:

| Role | May | May not |
|---|---|---|
| `airevenueos_app` | DML on tenant tables | create/drop tables; write reference data |
| `airevenueos_maintenance` | partition DDL, retention sweeps | bypass RLS (`NOBYPASSRLS`) |
| migration/admin | schema and reference data | — (deploy-time only) |

Cross-tenant reads of the dead letter queue require `app.platform_context` to be
bound, which `platform_session()` does while logging the reason — a narrow,
attributable escape rather than a `BYPASSRLS` role that would silently disable
policies everywhere.

Cache keys remain correctly namespaced (`tenant_key()` → `t:<tenant>:...`). Kill
switches still live in Redis only, so a flush disengages them and the action is
unaudited (P2-3).

Cache keys are correctly namespaced (`tenant_key()` → `t:<tenant>:...`) and
`invalidate_tenant` scans by prefix. Kill switches live in Redis only, so a Redis
flush silently disengages them — acceptable for a stop signal, but it means the
kill state is not durable and is not audited.

### 7.4 Storage isolation — **policy verified, pipeline absent**

`assert_download_allowed` refuses cross-tenant and unscanned reads; object keys are
UUID-based and tenant-prefixed; upload validation covers MIME allowlist, magic
bytes, dangerous and double extensions, SVG/PDF active content, zip expansion ratio
and CSV formula injection. None of it is wired into an endpoint, and the scanner
raises `NotImplementedError`, so no file can complete the lifecycle.

### 7.5 Webhooks — **one bypass found and fixed**

| Route | Verification | Status |
|---|---|---|
| `/webhooks/inbound/whatsapp/{provider}` | HMAC-SHA256 over raw body, constant-time; 5-minute replay window; challenge requires verify token | verified, 8 tests |
| `/webhooks/inbound/razorpay` | HMAC-SHA256; separate checkout-handback signature; dedupe by `external_event_id` | verified, 5 tests |
| `/webhooks/inbound/email/{provider}` | HMAC; returns `False` when no secret configured | verified |
| `/webhooks/inbound/custom/{webhook_id}` | **Was a bypass (A1)** — presence-only check | fixed and verified, 16 tests |

All routes acknowledge asynchronously and perform no business work inline. Inbound
dedupe uses Redis with 24h TTL; a Redis outage would allow duplicate processing —
the durable `provider_webhook_events` table exists but is not written to.

### 7.6 Auth and session handling — **primitives strong, surface missing**

Verified: Argon2id at spec parameters; breached-password k-anonymity (only a 5-char
SHA-1 prefix leaves the system); history of 5; lockout after 5 failures; admin
90-day expiry; RS256 with `alg=none` and HS-confusion both rejected; JWKS exposes
public material only; opaque hashed refresh tokens with rotation and family-reuse
revocation; 10-session cap; idle 2h / hard 8h re-auth; TOTP with drift window;
8 bcrypt recovery codes, single-use; step-up MFA on billing, export, deletion,
ownership transfer, API keys and high-value refunds.

**But `/v1/auth/*` does not exist.** None of this is reachable. The BFF exchanges
its session cookie at `/v1/auth/refresh`, which returns 404 — so the frontend cannot
authenticate even if it built.

CSRF double-submit and strict Origin enforcement are implemented in the BFF and
middleware and are tested at the API edge.

### 7.7 Secrets — **clean**

No hardcoded credential in `src/` (grep + bandit + gitleaks config). `.env.example`
carries empty placeholders. `Settings.assert_production_safe()` refuses to boot
production without signing material, encryption key, or with wildcard CORS or debug
on — asserted by release gate 8. RDS uses `manage_master_user_password` so the
credential never reaches Terraform state. Provider payloads are stripped of card
fields before persistence; the log redactor masks P3/P4.

One residual: `get_token_service` generates an ephemeral RSA keypair when none is
configured. Safe in local/dev and blocked in production by `assert_production_safe`,
but it means a misconfigured **staging** environment would silently issue tokens
signed by a key that changes on every restart. Recommend failing closed outside
`local`.

---

## 8. Production readiness

| Area | State | Gap |
|---|---|---|
| **Backups / restore** | Terraform: RDS Multi-AZ, PITR, 30-day snapshots, S3 versioning + lifecycle to IA/Glacier | Never provisioned. **No restore drill.** `infra/scripts/verify-restore.sh` is referenced by the nightly workflow and does not exist. RPO/RTO unmeasured |
| **Observability** | `structlog` JSON with correlation/tenant/user; **24** Prometheus metrics (worker task counts, durations, retries by class, heartbeat); `/health`, `/health/liveness`, `/health/readiness` (dependency-aware), IP-restricted `/health/metrics` | **No alert rules anywhere** — the spec requires warning/critical alerts with owner and runbook per signal. No dashboards. Sentry/Langfuse are config keys only. No tracing despite X-Ray in the stack table |
| **CI/CD** | 6-job PR pipeline; deploy workflow with plan approval, migration-safety gate, 5-min observation, rollback; nightly DAST/k6/restore/AI-eval | **Pipeline would fail today**: `pnpm install --frozen-lockfile` (no lockfile), `pnpm lint`/`typecheck`/`a11y` (no config, no tests), and three referenced scripts are missing. Never executed |
| **IaC** | 598 lines across network/data/edge + prod env | Never `terraform init`/`validate`/`plan`ed. Only `envs/prod`; `deploy.yml` targets dev/staging/prod. No ECS service/task definitions, no ALB target groups, no Route 53, no ECR, no Secrets Manager entries, no IAM task roles — the compute tier is undefined |
| **Monitoring** | Metric definitions exist | Nothing scrapes them; no Grafana; no PagerDuty; no SLO burn alerts |
| **Performance** | k6 `normal.js` and `noisy-tenant.js` with SLO thresholds | Never run. `peak.js` and `spike` profile missing. No soak, no chaos |
| **Accessibility** | Skip link, dual live regions, 44px targets, documented contrast ratios, 320px reflow, reduced motion | **No page renders.** axe never run; Lighthouse ≥95 unverified; zero manual screen-reader passes |
| **Dependencies** | `pip-audit`: no known vulnerabilities across the 33 declared Python dependencies | **No lockfile on either side.** Python has no `requirements.lock`/`uv.lock`; JS has no `pnpm-lock.yaml`. Builds are not reproducible and the audit result is not pinned |
| **Runbooks** | 4 written: provider activation, incident response, DR, database | Good quality but **none rehearsed**. DR runbook references a script that does not exist |

---

## 9. Deviations from the specification

| # | Spec requirement | Actual | Recommendation |
|---|---|---|---|
| D1 | Python 3.12 | `requires-python = ">=3.10"`; `shared/compat.py` shims `StrEnum`; ruff realigned to `py310` during this audit | Decide: adopt 3.12, delete the shim and set `target-version = "py312"`; or record the 3.10 floor as an accepted deviation |
| D2 | pnpm 9 + Turborepo workspaces | Declared; no lockfile, no installed workspace | Generate and commit `pnpm-lock.yaml` |
| D3 | Custom engine executes workflows on Celery | Executor is pure async Python; no Celery app exists | Implement `infrastructure/celery/app.py` with the 8 declared queues |
| D4 | Prompts Git-backed at `prompts/<task>/v<n>.yaml` | `prompts/` is empty | Author prompt files or remove the claim |
| D5 | `mypy` strict over the whole tree | Passes, but `tests/` is excluded from the mypy `packages` list | Extend to tests or document |
| D6 | Coverage bars per module (90/85 services, 95/90 AI+utilities) | 84% overall; AI guards 97%, utilities 87–98%, but `application/*` ranges 0–92% | Meet the bar or record an exception per module |
| D7 | Exception names | `Unauthenticated`, `NotFound` etc. lack an `Error` suffix (ruff N818) | Kept deliberately: names mirror the public error codes one-to-one. Documented in `pyproject.toml` |

---

## 10. What was verified end to end

Genuinely proven by executable evidence against real infrastructure:

1. Two-layer tenant isolation, including the non-obvious superuser/`BYPASSRLS` trap
   and partition inheritance.
1a. Worker-tier tenant safety: header-borne context, fail-closed tenant-scoped
   tasks, and RLS holding inside a real Celery worker across two tenants.
1b. Retry classification, three idempotency layers, durable dead lettering with
   single-use replay and 14-day retention, all against a real broker.
2. Migration `0001`+`0002` reversibility on PostgreSQL 16, with append-only triggers
   and constraint enforcement.
3. Transactional outbox: state and event commit together, roll back together,
   at-least-once dispatch with retry and dead-lettering.
4. The complete lead journey: capture → source-event preservation → dedupe →
   qualification → human review → conversion, under role scope.
5. Role scope and object-level authorization for leads, including fail-closed
   behaviour and out-of-scope/absent indistinguishability.
6. AI governance: pinned models, routing with fallback, circuit breakers, input and
   output guards, per-task degradation with a manual path, tool confirmation gating.
7. Industry template guardrails across all eight mandatory templates.
8. Webhook signature verification, replay windows and idempotency for all four
   inbound routes.
9. Payment state machine, server-side amount authority and card-data exclusion.
10. Workflow DSL sandbox: every attempted expression escape is rejected.
