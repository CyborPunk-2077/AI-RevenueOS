# GA activation checklist

Everything below is **external** to engineering. The corresponding code, tests,
flags, runbooks and infrastructure placeholders are complete; each item is a
decision, credential or sign-off that must be recorded before the feature can be
turned on in production.

Nothing in this list blocks the rest of the build, and none of it has been
fabricated, simulated or assumed.

## 1. Provider decisions and credentials

| # | Gate | Decision required | Blocks | Implemented and waiting |
|---|---|---|---|---|
| 1.1 | **WhatsApp** | BSP versus direct Cloud API, credential ownership, operational owner | M16 production enablement | `WhatsAppAdapter`, HMAC verification, replay window, template sync, delivery retry, opt-out stop, 26 contract tests |
| 1.2 | **WhatsApp templates** | Meta template approval for each message template | Out-of-window sends | `message_templates.status` gate, `TEMPLATE_NOT_APPROVED` block |
| 1.3 | **Email** | Provider (SES or SendGrid), commercial terms, ap-south-1 availability | M15 production enablement | `EmailAdapter`, bounce and complaint parsing, suppression |
| 1.4 | **Email domain** | Sender domain ownership plus SPF, DKIM and DMARC records | Deliverability | DNS placeholders in Terraform |
| 1.5 | **Payments** | Razorpay commercial model; collections versus SaaS billing; refund and reconciliation policy | M17 production enablement | `RazorpayAdapter`, server-side amount authority, HMAC verification, idempotent webhooks, reconciliation |
| 1.6 | **Voice** | Telecom provider (Exotel or Twilio), number ownership | M19 | `VoiceAdapter`, hard disabled |
| 1.7 | **n8n** | Hosting, licensing and named operational owner | M18 authoring UI | Ephemeral container, node allowlist, design-time APIs |
| 1.8 | **Signatures** | Signature provider agreement | Signature flows | `signature_requests` schema and status timeline |
| 1.9 | **Calendar** | Google OAuth verification for the requested Calendar scope | Optional calendar sync | `CalendarPort`, flag off |
| 1.10 | **Embeddings** | Approved OpenAI or Cohere multilingual model | RAG in production | pgvector schema, HNSW `m=16, ef_construction=200`, tenant-filtered retrieval |

## 2. Legal and compliance sign-offs

| # | Gate | Required before |
|---|---|---|
| 2.1 | DPDP privacy notice and consent copy per industry template | Any production customer contact |
| 2.2 | Retention schedule and legal-hold policy sign-off | Tenant deletion and purge |
| 2.3 | Voice recording and disclosure copy, legal approval | Voice enablement (also gated by `VoiceControls.legal_signoff`) |
| 2.4 | Industry prohibited-claim review (all eight templates) | Pilot in each industry |
| 2.5 | Minor-data handling policy for coaching institutes | Coaching pilot |
| 2.6 | Recruitment protected-trait and consent policy | Recruitment pilot |
| 2.7 | Clinic health-data (P3) processing policy and emergency escalation script | Clinic pilot |
| 2.8 | Breach notification process, 72-hour clock | GA |
| 2.9 | AI provider zero-retention or contractually approved retention | Any production AI call |

## 3. Commercial decisions

| # | Gate | Required before |
|---|---|---|
| 3.1 | Final pricing, quotas, overage and export limits | Billing enablement |
| 3.2 | Plan feature entitlement confirmation | Public plan catalogue |
| 3.3 | Razorpay subscription product configuration | SaaS billing |

## 4. AWS and production infrastructure

| # | Gate | Required before |
|---|---|---|
| 4.1 | Separate AWS accounts for dev, staging, sandbox and production | M02 real provisioning |
| 4.2 | Route 53 zone and ACM certificate for `*.airevenueos.io` | Public endpoints |
| 4.3 | Production KMS keys and Secrets Manager entries | Production boot (`assert_production_safe` refuses otherwise) |
| 4.4 | GitHub OIDC federation role ARNs | CI deployment |
| 4.5 | PagerDuty rotation and escalation policy | On-call |
| 4.6 | Sentry and Langfuse production projects | Production telemetry |

## 5. Pilot and release evidence (M23 and M24)

| # | Gate | Required before |
|---|---|---|
| 5.1 | One approved pilot tenant per enabled industry | GA |
| 5.2 | Measured SLO, usage and support evidence from each pilot | GA |
| 5.3 | Quarterly external penetration test report with no critical or high findings | GA |
| 5.4 | Timed backup restore drill meeting RPO 15 minutes and RTO 4 hours | GA |
| 5.5 | Manual screen-reader verification (JAWS, NVDA, VoiceOver, TalkBack) | GA |
| 5.6 | Soak test of at least 8 hours (24 preferred) against staging | GA |

## What GA does **not** require

These are complete and evidenced in-repo:

- Tenant isolation across API, workers, cache, storage and analytics (two enforcement
  layers, proven allow and deny paths).
- The eight mandatory industry templates as configuration only, with guardrails.
- Lead capture, dedupe, qualification with human review, and conversion.
- The restricted workflow DSL, immutable versions, idempotency, retry, approval
  gating, kill switch and replay provenance.
- The governed AI gateway with pinned models, guards, circuit breakers and safe
  degradation.
- Provider adapters with signature verification, replay windows and reconciliation.
- Migration safety, append-only enforcement and partitioning.
