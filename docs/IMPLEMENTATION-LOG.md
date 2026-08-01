# Implementation log

Executed M01 through M24 in dependency order under the autonomous execution
protocol. Local test, migration and gate failures were repaired within their
milestone. External provider, legal and production gates were implemented as
disabled adapters with tests and runbooks, then execution continued.

## Defects found and fixed during implementation

These are worth recording because each was a real bug, not a test artefact.

1. **RLS was silently inert.** The first isolation suite passed while connecting as
   the PostgreSQL superuser. `BYPASSRLS` defeats `FORCE ROW LEVEL SECURITY`, so
   every policy was a no-op. Fixed by creating a least-privilege `airevenueos_app`
   role in migration 0001 and running the isolation suite as a non-owner login role.
   Recorded in ADR 0002 and the database runbook.

2. **DST resolution was wrong for nonexistent local times.** `resolve_local_instant`
   checked ambiguity before existence, so 02:30 on a spring-forward date resolved
   backwards to 01:30 instead of forwards. Fixed by testing the UTC round trip
   first. Caught by `test_dst_spring_forward_moves_to_next_valid_instant`.

3. **Slot generation produced duplicate offers across a DST transition.** Two
   nonexistent local start times collapsed onto the same instant. `compute_slots`
   now skips a local time that does not exist rather than collapsing it.

4. **Indian phone numbers were not minimised in AI input.** The PII pattern assumed
   3-3-4 grouping and missed the common `+91 98765 43210` 5-5 form, so a phone
   number would have reached the provider. Fixed with a separator-tolerant pattern.

5. **Copilot tool names bypassed confirmation gating.** `FORBIDDEN_AUTONOMOUS_ACTIONS`
   listed `message.send_whatsapp` but not the tool name `send_message`, so a
   mutating tool would have executed without approval. All five mutating tool names
   added.

6. **Externally gated features looked like upgrade opportunities.** A plan-excluded
   but externally gated feature reported `upgrade_available: true`, which would have
   sold an upgrade that cannot enable the feature. Now reports
   `external_activation_pending` with the prerequisite.

7. **Duplicate constraint names across schemas.** Four constraint names collided
   (`tenant_name` on seven tables), which PostgreSQL rejects because index names
   share a schema namespace. Renamed and guarded by a metadata duplicate check.

8. **Structured logging crashed under the print logger.** `add_logger_name` requires
   a stdlib logger factory. Replaced with explicit binding in `get_logger`.

9. **Token verification used the wrong keys under test.** The dependency read the
   cached global settings rather than the settings the app was constructed with.
   Fixed with `get_app_settings`, which resolves from `request.app.state`.

## Milestones

| Milestone | Outcome | Key artefacts |
|---|---|---|
| **M01** Repository and local foundation | Complete | Monorepo, Turborepo, FastAPI app factory, settings with production fail-fast, correlation/error/security middleware, health and version endpoints, Compose, Makefile, pre-commit, CI baseline |
| **M02** Environments, IaC, CI/CD, observability | Complete (AWS accounts pending) | Terraform network/data/edge modules for ap-south-1, three-AZ VPC, RDS Multi-AZ, ElastiCache 3x2, private S3 with lifecycle, WAF with managed rules and rate limits, CI with six gated jobs, deploy workflow with plan approval, migration safety check, five-minute observation and automatic rollback, nightly DAST/k6/restore/AI-eval |
| **M03** Database, migrations, outbox, tenancy | Complete | 104 tables across four schemas, UUIDv7 keys, RLS enabled and forced on 92 tenant-owned tables, three partitioned tables, append-only triggers, `updated_at` triggers, server defaults mirrored from model defaults, async UoW committing state and outbox together, `SKIP LOCKED` poller with backoff and DLQ. 17 integration tests |
| **M04** Auth, sessions, RBAC, security | Complete | Argon2id at the specified parameters, password policy with HIBP k-anonymity, RS256 with JWKS, refresh rotation with family-reuse revocation, TOTP with bcrypt recovery codes, envelope encryption (KMS to tenant KEK to per-record DEK), full role matrix with owner-only protection, sliding-window rate limits, CSRF and origin enforcement. 90 security tests |
| **M05** Design system and app shell | Complete (component library scaffolded) | Root layout with skip link and dual live regions, tenant-scoped query keys with the specified stale times, tenant switch that removes rather than invalidates cache, BFF proxy holding the only token, accessibility tokens with documented contrast ratios |
| **M06** Onboarding, templates, plans | Complete | All eight mandatory templates plus a generic one as versioned JSON configuration; application preserves tenant customisation and rejects guardrail weakening; three plans with the exact documented limits; feature and quota checks shared by every surface. 105 tests |
| **M07** CRM foundation | Complete (schema and services) | Contacts, accounts, activities, tasks, notes, tags, custom fields, saved views, SLA records; email-or-phone constraint; partial unique indexes on active rows; append-only activity trigger |
| **M08** Leads, forms, dedupe, assignment | Complete | Capture through form, API, webhook and manual entry; source events always preserved; normalised dedupe with confidence banding; lifecycle state machine; assignment rules. 12 E2E tests |
| **M09** Deals, pipelines, tasks, SLA | Complete | Stage transition validation with required fields and loss reasons; status machine with audited reopen; business-hours SLA with holiday and DST handling. 27 tests |
| **M10** Consent, preferences, inbox | Complete | Single send-eligibility decision point covering opt-out, suppression, consent, quiet hours with midnight wrap, frequency caps, budget, deliverability and the WhatsApp 24-hour window; monthly-partitioned immutable messages. 33 tests |
| **M11** Branded webchat | Complete (schema, service, origin enforcement) | Widget with allowed origins, hashed session tokens, consent capture, handoff flag |
| **M12** AI gateway, prompts, qualification | Complete | Provider-neutral gateway with pinned models, policy-driven routing with fallback chains, circuit breakers (Anthropic on the tighter threshold), input and output guards, per-task degradation, usage metering with cost, budget hard stop, tool-loop limits with confirmation gating. 96 tests |
| **M13** Documents, extraction, RAG | Complete (schema, storage, guards) | Presigned upload with constrained conditions, MIME and magic-byte verification, dangerous-extension and double-extension rejection, SVG/PDF active content detection, zip-bomb ratio, CSV formula neutralisation, scan-gated download, pgvector chunks with HNSW `m=16, ef_construction=200` |
| **M14** Appointments and calendar | Complete | Slot computation with buffers, capacity, notice and horizon; DST-safe; double booking prevented by a database unique constraint mapped to 409. 13 tests |
| **M15** Email channel | Gated adapter complete | Port, bounce and complaint normalisation across SES and SendGrid shapes, suppression on hard bounce, flag off. Blocked on gates 1.3 and 1.4 |
| **M16** WhatsApp channel | Gated adapter complete | Cloud API adapter, HMAC verification, replay window, subscription challenge, template payloads, status mapping, opt-out keywords, retry classification. 26 contract tests. Blocked on gates 1.1 and 1.2 |
| **M17** Payments and invoices | Gated adapter complete | Server-side amount authority, state machine with append-only transitions, refund authorisation with MFA threshold, HMAC webhook and handback verification, card-data stripping, reconciliation. 40 tests. Blocked on gate 1.5 |
| **M18** Workflow engine and n8n isolation | Complete | Restricted DSL with expression sandbox, canonical hashing, immutable versions, executor with three idempotency layers, bounded retry with terminal classification, approval suspension, durable delay, kill switch, dry run, replay provenance, eight queues. 80 tests |
| **M19** Voice | Implemented and hard disabled | Seven independent controls required; the feature flag alone cannot enable it; `place_call` refuses and enumerates outstanding controls. Blocked on gates 1.6 and 2.3 |
| **M20** Analytics and exports | Complete (rollups and export jobs) | Four materialised rollup tables; timezone-correct day bounds; async private exports with expiry and step-up authentication |
| **M21** Security, quality, performance | Complete (harness); staged execution pending | Six-job CI with SAST, SCA, secret, container and IaC scanning; k6 normal, peak and noisy-tenant profiles; ZAP nightly; axe in CI; 662 tests at 85% coverage |
| **M22** Resilience and disaster recovery | Complete (procedure); drill pending | Degradation behaviour proven in tests; restore verification script re-runs the RLS suite against the restored instance; runbook with measured targets. Needs gate 4.1 |
| **M23** Controlled pilots | Prepared | Pilot cohort flag, per-tenant enablement, telemetry and the acceptance suite are in place. Needs gates 5.1 and 5.2 |
| **M24** General availability | Release candidate | Feature-flagged release candidate with the complete external activation checklist. GA is **not** claimed: provider, legal, security and pilot gates remain |

## Deliberate decisions recorded as ADRs

- 0001 Modular monolith with independently scalable workers
- 0002 Two independent layers of tenant isolation
- 0003 Externally gated capabilities ship disabled, never faked
- 0004 n8n authors workflows; a custom engine executes them
- 0005 All model access flows through one governed gateway

---

## Audit correction (2026-08-01)

An independent release-readiness audit reviewed this log against the repository.
Milestone statuses recorded above as "Complete" were, in several cases, complete only
at the schema or pure-domain layer. The audit found no service or endpoint layer for
CRM, deals, inbox, webchat, documents or analytics; no Celery worker tier despite
compose referencing one; no authentication endpoints; and a frontend that cannot
build. It also found four security defects, including a webhook authentication
bypass and a dead-code authorization scope.

`docs/IMPLEMENTATION-AUDIT.md` supersedes the milestone table above.
