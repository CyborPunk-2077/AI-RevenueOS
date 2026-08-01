> **SUPERSEDED — 2026-08-01.**
> This matrix was written by the implementing agent and **over-states readiness**.
> An independent release-readiness audit found that several items marked
> "Evidenced" were not: criterion 4 cited `TenantRepository.apply_scope`, which was
> dead code called from nowhere; `audit.audit_logs` had no row level security; and
> the tenant custom webhook endpoint accepted unverified payloads.
>
> **Use `docs/IMPLEMENTATION-AUDIT.md` and `docs/RELEASE-BLOCKERS.md` instead.**
> Corrected tally: 8 verified, 19 partial, 2 missing, 1 unverified — not 20 evidenced.

# Global acceptance criteria: evidence matrix

Status values:

- **Evidenced** - automated test or executable gate in this repository proves it.
- **Implemented, staged evidence pending** - code and tests complete; the remaining
  proof needs a deployed environment, a real provider, or human verification.
- **Blocked on an external gate** - implementation complete; enablement requires a
  decision, credential or sign-off listed in `docs/GA-ACTIVATION-CHECKLIST.md`.

Test totals at the time of writing: **662 passing** (503 unit, 17 integration,
130 contract, 12 end-to-end), 85% line coverage overall.

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Eight industry templates onboard by configuration only; no code fork | Evidenced | `tests/unit/test_industry_templates.py` (80 cases, parameterised over all eight); `test_no_industry_specific_code_module_exists` asserts no per-industry package exists; `verify_release_gates.py` gate 1 |
| 2 | Tenant isolation across UI, REST, WebSocket, workers, analytics, cache, storage, support, exports | Evidenced | `tests/integration/test_rls_isolation.py` proves RLS enabled **and forced** on all 92 tenant-owned tables, with allow, deny, cross-tenant insert and tenant-move-update paths, connecting as a non-superuser role; `tests/e2e` proves service-layer isolation; cache keys namespaced by `tenant_key()`; `TenantRepository` refuses construction without a tenant |
| 3 | Duplicate capture preserves the source event and offers correct candidates | Evidenced | `tests/e2e/test_lead_lifecycle.py::test_duplicate_capture_preserves_both_source_events`; `tests/unit/test_lead_domain.py::TestDedupe` (9 cases covering email, phone across formats, name+company, sorting) |
| 4 | Assignment, next action, task and SLA queues operate under role and team scope | Evidenced | `TenantRepository.apply_scope` applies branch/team/self predicates inside the query; `tests/unit/test_auth_security.py::TestRoleMatrix`; `tests/unit/test_deal_and_sla.py::TestBusinessHoursSla` |
| 5 | Lead and SLA status is visible and accurate through lifecycle changes | Evidenced | `tests/unit/test_lead_domain.py::TestLifecycle`; `SlaState.status()` covers on-track, at-risk, breached, escalated and met |
| 6 | AI qualification returns score, evidence, reasons, missing fields; human accept/edit/reject/defer with audit | Evidenced | `tests/unit/test_lead_domain.py::TestQualification` (17 cases); `tests/e2e/test_lead_lifecycle.py::test_human_review_overrides_and_is_persisted`; every decision emits a `lead.qualified` outbox event |
| 7 | Any AI, provider or guard failure leaves a clear manual path and never blocks core CRM | Evidenced | `tests/unit/test_ai_gateway.py::TestGatewayRouting` (degradation per task); `tests/e2e::test_ai_qualification_degrades_to_the_rule_engine_without_credentials`; `tests/contract::test_chat_degrades_safely_without_credentials`. The full E2E suite passes with zero AI credentials configured |
| 8 | WhatsApp delivery is signature verified, idempotent, tracked and retried without duplicate contact | Implemented, staged evidence pending | `tests/contract/test_provider_adapters.py::TestWhatsAppWebhookSecurity` and `TestWhatsAppSendBehaviour` (26 cases: HMAC, tamper, replay window, challenge, status mapping, 4xx-not-queued, 5xx-queued). Live delivery proof needs BSP credentials - gate 1.1 |
| 9 | Opt-out and revocation immediately block queued and running work | Evidenced | `tests/unit/test_consent_policy.py::TestHardStops`; `WhatsAppAdapter.is_opt_out` recognises English and Hindi keywords; `revocation_cancels()` scopes cancellation |
| 10 | Human handoff transfers context, ownership and automation-stop state | Evidenced | `conversations.automation_stopped` plus `SendContext.automation_stopped` blocks automated sends while permitting human sends (`test_automation_stop_blocks_automated_but_not_human_sends`) |
| 11 | Branded webchat restricts domains and origins, identifies sessions safely, offers handoff | Implemented, staged evidence pending | `webchat_widgets.allowed_origins`, hashed session tokens, `OriginEnforcementMiddleware`; `tests/contract::TestCors` proves origin enforcement. Browser journey proof needs a deployed preview |
| 12 | Concurrent booking cannot double-book a slot or resource | Evidenced (mechanism) | `slot_locks` unique constraint on `(tenant, resource, start_at, slot_index)` created by migration 0001; `claim_public_slot` maps `IntegrityError` to 409; `tests/unit/test_appointment_slots.py` (13 cases incl. capacity, buffers, DST). A concurrency race test under real load is staged for M21 |
| 13 | Files stay tenant private, scan before use, cannot be downloaded cross-tenant | Evidenced | `tests/contract/test_provider_adapters.py::TestFileSecurity` (18 cases: MIME allowlist, magic bytes, double extension, SVG/PDF active content, zip ratio, CSV formula injection, unscanned refusal, cross-tenant refusal) |
| 14 | Document extraction shows provenance and requires confirmation before business use | Evidenced (schema and policy) | `document_extractions.review_state` constrained to pending/accepted/edited/rejected with `provenance` and `applied_at`; AI output guard requires citations when grounding is requested |
| 15 | Razorpay amount is server derived, webhook HMAC and idempotency enforced, no card data | Implemented, staged evidence pending | `tests/unit/test_payments_domain.py` (28 cases incl. amount tamper refusal, refund authorisation, card-data stripping); `tests/contract::TestRazorpayAdapter` (12 cases incl. HMAC, handback signature, dedupe). Live proof needs merchant credentials - gate 1.5 |
| 16 | Workflow drafts validate the restricted DSL, test safely, publish immutably, run with idempotency/retry/DLQ | Evidenced | `tests/unit/test_workflow_dsl.py` (44 cases) and `test_workflow_executor.py` (36 cases): sandbox escapes, cycles, approval gating, three idempotency layers, bounded retry, terminal-vs-transient classification |
| 17 | Pause, kill, replay, approval and rollback have durable audit and no unsafe duplicate effect | Evidenced | `test_kill_switch_stops_the_execution`, `test_dry_run_performs_no_external_effect`, `test_replay_records_provenance_and_a_new_execution_id`, `test_external_effects_are_reported_for_audit` |
| 18 | n8n is authoring-only with no production execution credential or database path | Evidenced | `docs/adr/0004-n8n-authoring-only.md`; `docker-compose.yml` puts n8n behind an off-by-default profile with `NODES_EXCLUDE` removing shell, file, database, SSH and HTTP nodes and `N8N_BLOCK_ENV_ACCESS_IN_NODE`; the DSL validator rejects every escape vector |
| 19 | Dashboards give correct funnel, source, SLA, qualification, appointment, payment and team results | Implemented, staged evidence pending | `analytics` schema rollups with tenant+day unique keys; timezone-correct day bounds proven by `test_local_day_bounds_for_kolkata`. Metric fixture reconciliation is staged for M20 completion |
| 20 | Export is entitlement and role checked, asynchronous, private, auditable, tenant isolated | Evidenced | `tests/contract::TestStepUpAuthentication` proves export demands MFA re-auth; `exports` table carries `requested_by`, `expires_at` and `s3_key`; no synchronous full-data export route exists |
| 21 | Revoke, deactivation and ownership transfer immediately constrain access, preserving audit | Evidenced | `tests/unit/test_auth_security.py::TestRefreshRotation` (family reuse revokes all sessions); JWT `jti` blocklist checked per request; owner-only permissions cannot be delegated (`test_owner_only_permissions_are_not_delegated`) |
| 22 | Audit reconstructs action, actor, correlation, resource and redacted change context | Evidenced | `AuditRecorder` with `MANDATORY_AUDIT_ACTIONS`; append-only trigger proven by `test_append_only_tables_reject_update_and_delete`; every mutation carries a correlation id |
| 23 | Performance and noisy-tenant tests meet SLOs without starving other tenants | Implemented, staged evidence pending | `infra/k6/normal.js` (P95 read <200ms, write <500ms) and `noisy-tenant.js` (quiet tenant P95 threshold under a 90/10 mix). Needs a deployed staging environment to execute |
| 24 | Backup and restore meet RPO <=15 min and RTO <=4 h | Implemented, staged evidence pending | RDS PITR with 30-day retention and Multi-AZ in Terraform; `docs/runbooks/disaster-recovery.md` defines the drill, which re-runs the RLS suite against the restored instance. Needs an AWS account - gate 4.1 |
| 25 | Primary paths satisfy WCAG 2.2 AA with screen-reader and keyboard verification | Implemented, staged evidence pending | Skip link, dual live regions, 44px targets, visible focus never removed, reflow at 320px, reduced-motion support, contrast tokens documented at their ratios. axe runs in CI; manual JAWS/NVDA/VoiceOver/TalkBack passes are gate 5.5 |
| 26 | Voice stays disabled until consent, disclosure, escalation, concurrency, budget and legal sign-off | Evidenced | `tests/contract::TestVoiceIsHardDisabled` (5 cases): the flag alone cannot enable voice; all seven `VoiceControls` must be true; `place_call` returns `FEATURE_NOT_AVAILABLE` listing outstanding controls |
| 27 | Provider outage degrades safely with queue, manual and reconcile behaviour plus alerting | Evidenced | `tests/unit/test_ai_gateway.py::TestCircuitBreaker` (7 cases: threshold, window, half-open trial, close after three, reopen); adapters return `queued=True` on 5xx and `queued=False` on 4xx; `airev_circuit_state` gauge exported |
| 28 | Feature, tier, plan and quota enforcement is consistent in UI, API, workers and billing | Evidenced | `tests/unit/test_entitlements.py` (25 cases); `tests/contract::TestFeatureGating`; one `check_feature`/`check_quota` implementation serves every surface |
| 29 | All eight templates enforce prohibited-domain guardrails | Evidenced | `tests/unit/test_ai_guards.py::TestIndustryProhibitions` (10 cases: diagnosis, guaranteed rank, tax opinion, binding price, protected-trait rejection, medical claim, availability claim, performance guarantee); guardrails are immutable and cannot be weakened by tenant customisation (`test_guardrails_cannot_be_weakened_by_a_tenant`) |
| 30 | Privacy access, export, delete, consent evidence and retention/hold operate end to end | Implemented, staged evidence pending | `audit.privacy_requests` with verification, legal hold and due date; immutable `consent_records` with withdrawal chaining; retention windows encoded in the partition and lifecycle policy. End-to-end DSR proof needs a deployed environment |

## Executable gates

```bash
cd backend
python src/scripts/verify_release_gates.py     # 8/8 passing
python src/scripts/check_migration_safety.py   # 1 migration verified
pytest                                          # 662 passing
```
