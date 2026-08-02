# Global Rules

## Purpose and precedence

This is the implementation source of truth for **AI RevenueOS**: a multi-tenant B2B RevenueOS for Indian SMEs. Build only the stated product: canonical customer records, leads, opportunities, activities, communications, appointments, documents, payments, automation, analytics, and compliance. It is not an ERP or a vertical-specific codebase.

Apply the most specific and later architecture rule where supplied specifications conflict: Security controls in this document govern generic backend/DevOps defaults; the Workflow Engine governs n8n execution; public API contracts govern external routes. Record any remaining product/vendor decision as an ADR before implementation; do not silently choose it.

## Autonomous execution protocol

The implementing agent executes M01 through M24 in dependency order without requesting milestone-by-milestone approval, confirmation, status acknowledgement, or permission to proceed. It must complete the current milestone's code, migrations, documentation and automated acceptance evidence; repair failures; then begin the next eligible milestone automatically. Do not skip a failed criterion, weaken a test, broaden scope, or silently redesign a specified decision.

- Work autonomously in the repository: create/edit code and tests, run local services and quality gates, create migration/rollback evidence, and maintain an implementation log/ADRs. Produce progress only as concise non-blocking updates; issue one consolidated handoff at the end or after a genuine external release blocker.
- Use the specified framework, contracts and module boundaries. Make ordinary local implementation choices directly. Record an ADR only for a remaining decision that the specification explicitly leaves open; do not wait for approval to continue unaffected work.
- An unresolved external gate (provider account/credential/template approval, commercial agreement, legal/compliance sign-off, DNS/AWS account or production secret) is **not** a reason to pause the build. Implement the provider port, configuration validation, feature flag defaulting off, sandbox/mock contract tests, failure/reconciliation behavior, runbook and deployment/IaC placeholders; record the exact activation prerequisite and continue.
- Never fabricate provider credentials, legal approval, payment/WhatsApp template approval, production deployment, or successful live transaction. These are external GA-release gates, not implementation approvals. Re-run sandbox/integration checks automatically when credentials become available; until then, leave the feature safely disabled in production.
- If a local test, migration or service fails, inspect, fix and retry within the milestone. Stop only when no safe local action can resolve an external dependency; continue with independent milestones and list the blocked release gate in the final consolidated report rather than asking for per-step direction.
- At M24, deliver either a production-ready release with recorded external sign-offs or a complete, feature-flagged release candidate plus the minimal external activation checklist. Do not claim GA until the stated provider, legal, security and pilot gates are evidenced.

### Non-negotiable product rules

- Multi-tenancy is mandatory from the first migration. Every user-visible request, job, realtime subscription, analytics query, object access, cache key, provider action, support action, and export is tenant isolated.
- The canonical customer model is `contact` with optional `account`, `lead`, `opportunity`, activities, conversations, appointments, documents, payments, consent, and automation history. Do not create per-industry entity forks.
- Industry variation is versioned configuration/templates only: fields, qualification rubric, pipeline, messages, workflow packs, business hours, consent copy, and dashboards.
- India defaults: `Asia/Kolkata`, INR, Indian phone validation, Razorpay, and WhatsApp. Internationalization must not require redesign.
- Automated activity is attributable, auditable, stoppable, idempotent, policy checked, and subject to consent, opt-out, quiet hours, frequency caps, tenant/channel preferences, budget, and feature entitlement.
- AI can automate only low-risk work. Sensitive, irreversible, financial, legal, medical, employment/high-impact, external-send, destructive, or customer-state-changing actions require deterministic guardrails and explicit human approval.
- PostgreSQL is the durable source of truth. Redis is cache, coordination, rate-limit, and Celery transport/result infrastructure only; it is never the sole durable state.
- All external effects use a server-side provider abstraction; browsers never call AI, payments, WhatsApp, email, storage, or credentials directly.
- All external APIs/webhooks are versioned. No tenant-specific deployments or source-code branches.

### Explicit decision gates (do not invent)

| Gate | Required decision before dependent production work |
|---|---|
| Email and voice | Provider, commercial terms, regional availability, sender/number ownership |
| WhatsApp | BSP/Cloud API mode, credential ownership, template approval and operational owner |
| Payments | Razorpay commercial model, collections versus SaaS billing, refund/reconciliation policy |
| n8n | Hosting/licensing and operational owner; runtime remains custom engine regardless |
| Legal | DPDP/privacy notices, retention/legal hold, recording/voice disclosures, industry-specific prohibited claims |
| Plans | Pricing, quotas, overage, feature entitlements, export limits |
| Optional integrations | Calendar provider scope and any industry-sensitive data policy |

### System-wide definition of done

Each deliverable has correct happy/edge behavior; tenant/object authorization at the server boundary; strict trusted-input validation and stable errors; audit/correlation data; idempotent/time-bounded/retried/reconcilable external effects; loading/empty/error/offline UI states; accessible primary paths; structured logs, metrics, traces, health checks and alerts; unit/integration/contract/auth/isolation/E2E tests; meter/feature enforcement; rollback/kill switch; PII/retention/provider review; runbook and staging evidence.

# Technology Stack

| Layer | Standard |
|---|---|
| Web | Next.js 14.2 App Router, React 18.3, TypeScript 5.5 strict, pnpm 9, Turborepo |
| UI | Tailwind 3.4, shadcn/ui + Radix, Lucide, TanStack Table 8, React Hook Form 7.51 + Zod 3.23, Tiptap 2, dnd-kit, Uppy 3, Recharts 2, date-fns 3, next-intl 3 |
| Client state | TanStack Query 5 for server state; Zustand 4.5 for ephemeral UI state only |
| API | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic, uvicorn/gunicorn |
| Data | PostgreSQL 16 (+ pgvector), PgBouncer, UUIDv7 primary keys, Redis 7 |
| Async | Celery 5, Celery Beat, transactional outbox, JSON task serialization |
| Workflow | Custom Python/Celery persistent state machine; self-hosted n8n is design-time visual authoring only |
| Storage | Private Amazon S3, presigned upload/download, ClamAV scanning |
| AI | Provider-neutral gateway; Anthropic Claude, OpenAI, Google Gemini, OpenAI/Cohere embeddings, Whisper; exact model versions in AI System |
| External | WhatsApp Cloud API, Razorpay, SES/SendGrid (decision gate), Exotel/Twilio (decision gate), Google OAuth/Calendar, n8n |
| Hosting | AWS ap-south-1 (Mumbai): ECS Fargate, ALB, CloudFront, WAF, RDS Multi-AZ, ElastiCache, S3, ECR, KMS, Secrets Manager, Route 53, CloudWatch/X-Ray/Sentry |
| IaC/CI | Terraform, GitHub Actions, Docker/Compose locally, ECR image promotion |
| Quality | Ruff, mypy strict, pytest, Vitest, React Testing Library, Playwright, axe, Storybook 8, k6, OWASP ZAP, SAST/SCA/container/IaC scans |

# Architecture Decisions

## Shape and module boundaries

Use a **modular monolith with independently scalable workers**, not microservices. The API and workers share a deployable codebase and PostgreSQL but communicate cross-module state changes through domain events/outbox rather than direct cyclic calls.

Core modules: Tenancy, Identity, CRM, Leads, Communications, AI Engine, Appointments, Documents, Payments, Workflows, Analytics, Audit/Consent, and Subscription/Feature Control. Tenancy has no internal dependency. Identity depends on Tenancy. Analytics is read-only across module data. Audit and Workflow cross-cut but consume events. AI and Appointments integrate through events. Enforce non-cyclic imports with import-linter.

`API -> application -> domain <- infrastructure` is mandatory:

- API: HTTP/WebSocket parsing, authentication dependencies, response mapping; no business logic, ORM querying, or provider calls.
- Application: commands/queries, DTOs, orchestration, transactions, permissions, ports.
- Domain: pure entities, value objects, policy and events; no FastAPI, SQLAlchemy, Redis, network, or I/O.
- Infrastructure: SQL repositories, provider clients, cache, event transport, file storage, telemetry; implements domain/application ports.

## Durability, transactions, and events

- Every tenant-owned row has `tenant_id NOT NULL`; UUIDv7 PKs; timestamps; soft delete where applicable.
- Set PostgreSQL transaction-local `app.tenant_id` per request/job. Enforce PostgreSQL RLS tenant policy plus repository tenant filters. Branch/team/self scope is an application/query policy on top of tenant RLS.
- Commit state change and `event_outbox` row in one database transaction. Poll with `FOR UPDATE SKIP LOCKED`, batch 100, target cadence 500 ms. At-least-once delivery is expected; consumers must be idempotent.
- Use optimistic `version` fields for editable records, locks for payment transitions, unique/natural keys or advisory locking for concurrent lead dedupe, and idempotency keys for public/external mutations.
- Migrations are Alembic, idempotent and reversible. Use expand/contract: add nullable columns, dual write/backfill/read, cut over, then remove later. Create indexes concurrently; add foreign keys `NOT VALID` then validate; never hold production DDL locks for more than 2 seconds.

## Scale, availability, and degradation

Year-one target: 5,000 tenants; normal concurrency 50 and P95 200 users; up to 1M leads per tenant. API target P95: reads <200 ms, writes <500 ms. Qualification <8 s async/<3 s pre-warmed sync; WhatsApp delivery median <2 s; availability 99.9%.

Autoscale API when CPU >70% or P95 >500 ms; production range 4–12 tasks. Keep worker pools isolated by workload. On PostgreSQL failure return controlled 503/fail over; Redis cache loss bypasses cache while workers pause safely; provider outages queue/retry with circuit breakers and visible manual fallback; payment order creation queues and reconciles every 30 minutes; S3 unavailability blocks file availability safely; noisy tenants throttle before shared exhaustion.

## Caching

Namespace every key by tenant. Defaults: tenant configuration 300 s, effective permissions 600 s, dashboard 60 s, feature flags 120 s. Cache only reproducible reads; invalidate after writes/events. Redis outage must not affect correctness.

## Protocol seams

Define explicit ports for repositories, unit of work, event bus, cache, storage, AI, WhatsApp, email, payment, calendar, and voice. These are extraction seams, not authorization to split services.

# Coding Standards

## Backend

- Python 3.12; fully typed public/internal interfaces; mypy strict; no unreviewed `Any`; Ruff enforced; 100-character lines; Google-style docstrings for public contracts.
- Async for all I/O; never block the event loop; no `print`; use `pathlib`, f-strings, and structured logging.
- Services are stateless. Application services orchestrate commands; domain services enforce rules; repositories expose interfaces in domain/application and implementations in infrastructure.
- FastAPI dependency injection supplies cached singletons (settings, engines, clients) and request-scoped correlation ID, authenticated principal, tenant context, and unit of work.
- Validate at Pydantic boundary (strict/forbid unknown), command/use-case boundary, domain value-object boundary, and database constraints. Normalize email lowercase; accept Indian phone as `+91` or 10 digits beginning `[6-9]`; qualification score 0–100, Hot >=80, Warm >=40.
- Use `structlog`: `timestamp`, level, logger, event, request/correlation ID, tenant ID, user ID, duration, module. Never log secrets or prohibited PII.
- Stable error shape internally: `{error:{code,message,request_id,details}}`; map to the public API envelope below. Use typed exceptions only.

## Frontend

- TypeScript strict; named exports; no default exports; server components by default; add `'use client'` only for browser state/interactivity. Do not use `useEffect` for server fetching; use RSC/TanStack Query.
- No direct DOM manipulation outside vetted Radix integration. Use shared UI, validators, API client and query keys. No browser-held access/refresh tokens or authoritative server data in Zustand.
- Route and feature imports must respect monorepo boundaries. Tenant ID is present in every query key; switch tenant invalidates/removes tenant-scoped cache and opens a new realtime subscription.
- React Query stale defaults: profile/tenant 5m; lead/deal 30s; contact 1m; conversation 15s; message 30s; appointment 1m; document 2m; analytics 5m; settings 10m; audit 2m; workflow 5m. Use cursor infinite queries, prefetch, mutation invalidation, and explicit optimistic rollback for drag/drop and send actions.
- Use Zustand only for sidebar/theme, selected inbox/filter UI, workflow-canvas draft (session persistence), and browser-event coordination. Do not persist tokens or server entities.
- Form pattern: RHF + shared Zod schemas + typed mutation; wizard state is one form with session recovery; warn before navigation when dirty.
- Accessibility is WCAG 2.2 AA: semantic labels, keyboard operation/no traps, visible focus, skip links/page titles, live status/error announcements, 4.5:1 normal contrast, 3:1 large contrast, 44px targets, reflow at 320px, keyboard drag/drop alternative, and accessible time warnings.

## Shared conventions

- REST JSON uses `snake_case`; ISO-8601 UTC timestamps; money represented as integer minor units plus currency. PATCH follows merge-patch semantics: omission=no change, `null`=clear where nullable.
- All state changes carry correlation ID, actor (user/service/support), tenant, and resource identity. External operations have provider request/reference IDs.
- Realtime events never expose cross-tenant or unauthorized resource data. User-visible times display in the user timezone; stored instants are UTC.

# Folder Structure

```text
AI-RevenueOS/
  apps/
    web/
      src/app/(auth|onboarding|dashboard|fullscreen)/
      src/app/api/{auth,webhooks,health}/
      src/features/{auth,tenants,leads,crm,inbox,appointments,documents,payments,workflows,analytics,settings,ai}/
      src/components/{ui,shared}/  src/hooks/  src/lib/  src/providers/
    marketing/  docs/
  packages/
    ui/  api-client/  shared/  stores/  ai-widgets/  config-eslint/
  backend/
    src/
      api/{app,router,deps,middleware,v1,health}/
      application/{auth,tenants,users,leads,contacts,deals,communications,ai,appointments,documents,payments,workflows,analytics,audit}/
      domain/{base,events,exceptions,auth,tenants,users,leads,contacts,deals,communications,ai,appointments,documents,payments,workflows,analytics,audit}/
      infrastructure/{database/{models,repositories,session,base},uow,caching,messaging,celery,integrations,auth,monitoring,logging}/
      shared/{types,results,pagination,exceptions,utils}/
    alembic/  tests/{unit,integration,e2e,contract}/  scripts/
    pyproject.toml  Dockerfile
  prompts/<task>/v<n>.yaml
  infra/terraform/{modules,envs/{dev,staging,prod,sandbox}}/
  docker-compose.yml  Makefile  .github/workflows/
```

Frontend route hierarchy:

```text
(auth): login, signup, forgot-password, reset-password/[token], invite/[token]
(onboarding): welcome, tenant, industry, channels, team, billing
(dashboard)/[tenantSlug]:
  home; leads/{board,table,new,[id]}; contacts/{import,[id]}; deals/{pipeline,[id]};
  inbox/{compose,[conversationId]}; calendar/[id]; documents/{templates,[id]};
  payments/{invoices,[id],payment-links,razorpay}; workflows/{builder,[id],[id]/history};
  analytics/{reports,custom}; campaigns; settings/{general,channels,team,roles,billing,
  integrations,ai,api,compliance,developer}
(fullscreen): workflow editor, document editor
```

Root layout provides fonts/theme/providers; dashboard layout provides tenant guard, sidebar, topbar, tenant switcher, global search, notifications, user menu, and AI copilot. Use parallel route slots for lead detail overlays. Mobile supports essential operations; workflow canvas is desktop-only with an explicit mobile limitation.

# Module Specifications

## Tenancy, subscription, and feature control

Create tenant with company identity, slug, timezone, currency, locale, branches, business hours, holidays, branding, plan/trial/status, industry-template application, team invitations, channel health tests, metering, entitlement checks, exports and deletion workflow. Tenant resolution comes from validated host/slug plus authenticated tenant membership; never trust a client-provided tenant ID alone.

Plan/feature middleware evaluates active subscription, quota, and feature flag before expensive/provider actions. Feature/tier failure is explicit and non-destructive. Tenant deletion is owner-only, delayed by retention policy, and auditable.

## Industry template catalog

Templates are versioned configuration only: terminology, lead/custom-field schemas with classification/access metadata, qualification rubric, pipeline/stages/reasons, message/document templates, workflow recipes, business hours/holidays, dashboard presets and prohibited-AI rules. Selecting or upgrading a template must record template version and tenant divergence; it must never overwrite tenant customization or add hidden behavior. Admins may edit permitted configuration within plan limits.

| Code | Terminology/default pipeline | Qualification and automation focus | Non-negotiable AI guardrail |
|---|---|---|---|
| `real_estate` | buyer/tenant/investor; New → Contacted → Qualified → Site Visit → Negotiation → Booked/Won/Lost | location, budget, property/timeline/finance; brochure, routing, site-visit | no binding price, availability, title or return claims |
| `clinics` | patient/prospect; Inquiry → Contacted → Appointment Booked → Attended → Follow-up/Converted | requested service/location/practitioner/time; booking, reminders, intake | no diagnosis, medical advice or emergency triage; emergency language routes to approved human instructions |
| `coaching_institutes` | student/guardian; Inquiry → Counselled → Demo/Assessment → Enrolled/Won/Lost | course, education, mode/location, timeline, fee; counselling/demo/reminders | no guaranteed results, ranks or placements; configured minor-data handling |
| `recruitment` | candidate/client/role; Sourced → Screened → Submitted → Interview → Offered → Placed/Lost | skills, experience, location, notice/compensation, consent; CV review, scheduling | no protected-trait inference or autonomous rejection; advisory evidence only |
| `marketing_agencies` | prospect/company/service; Inquiry → Discovery → Qualified → Proposal → Negotiation → Won/Lost | objectives, channels, budget, timeline; discovery, brief, proposal/deposit | no guaranteed performance or unsupported benchmarks |
| `ca_firms` | client/service/filing; Inquiry → Document Collection → Consultation → Proposal → Engaged/Won/Lost | entity/service/period/deadline/readiness; secure documents, consultation, reminders | administrative assistance only; no tax/legal opinion; restrict sensitive documents |
| `gyms` | member/prospect/branch/plan; Inquiry → Contacted → Trial Booked → Trial Attended → Membership/Won/Lost | goal category, branch/time, plan/start; trial/renewal/payment follow-up | no medical or guaranteed body-transformation claims |
| `automobile_dealerships` | buyer/vehicle/branch; Inquiry → Contacted → Qualified → Test Drive → Quote → Booking/Won/Lost | model/variant, budget, timeline, exchange/finance; test drive, brochure, quote | price, inventory, delivery and finance require verified data or human confirmation |

A generic `other_sme` template is permitted; the eight named templates are mandatory onboarding and acceptance-test fixtures.

## Identity and access

Roles: Owner, Admin, Manager, Member, Viewer/Auditor; support operational personas may receive scoped permissions but never bypass tenant isolation. Owner is singular and immutable until audited ownership transfer. Server permission checks resolve role permissions plus branch/team/assignment scope on every protected action.

## CRM, leads, and opportunities

Capture leads by embedded/popup/landing forms, API, webhook, manual entry, CSV import, source/UTM attribution, and normalized duplicate detection. Preserve source events. Lead lifecycle: `new -> qualified -> contacted -> nurturing -> converted|disqualified|archived`; qualification supports evidence, score, reasons, missing data and human accept/edit/reject/defer. Conversion preserves links/history.

Manage contacts/accounts, tags, configurable profiles, notes, attachments, activities, next actions, priority, assignments, lists/search/saved views/bulk actions, merge and custom fields. Pipelines use ordered configurable stages; opportunity statuses are open/won/lost/abandoned; loss reasons/required stage fields enforced. Tasks/SLA exceptions have assignee, due/next-action state and queueable follow-up.

## Communications

One conversation timeline covers WhatsApp, email, web chat, SMS/voice where enabled. Inbound/outbound messages are immutable. Approved templates and approved freeform policies are enforced. Immediate opt-out/human handoff stops queued/running customer-contact actions. Apply consent, suppression, quiet hours, frequency caps and deliverability status before every send.

WhatsApp is the MVP channel: connection/health, template status, delivery webhooks, dedupe, retries and visible failure. Branded webchat is public but constrained to safe anonymous/identified flows. Email and voice are feature-gated pending provider/legal decisions; voice remains disabled unless disclosure, recording/consent, escalation, concurrency and budget controls pass.

## Appointments

Support appointment types, duration, buffers, capacity, resources/branches, business hours/holidays, public and assisted booking/reschedule/cancel, reminders, outcomes, and concurrency-safe slot reservation. External calendar integration is optional and provider-scoped. Slot claims must prevent double booking under concurrent requests.

## Documents and payments

Documents include templates, request/upload, malware/type/size validation, private storage, generation, sending/viewing, signatures, expiration/voiding, extraction/review, knowledge lifecycle, and status timeline. P1 extraction never silently becomes fact: display provenance and require confirmation before business use.

Payments are INR/Razorpay hosted flows; no raw card data. Create a server-validated order, verify webhook signature, maintain immutable payment/refund history, reconcile, and drive event-based actions. Card, UPI, netbanking, wallet, EMI and UPI-intent are recorded as methods—not processed in browser code.

## Analytics, audit, support

Provide tenant/timezone-correct funnels, source attribution, SLA, qualification, appointment, payment, team and usage dashboards, definitions, denominator, date ranges, and drilldown to authorized records. Exports are asynchronous, auditable, entitled and private. Audit must reconstruct actor/action/context for material events. Consent/privacy requests, data export/deletion, support access, usage/metering, and feature control are first-class.

## Notifications and integrations

Create durable, idempotent per-user in-app notifications for assignment, mention/handoff, SLA breach, approval, appointment, workflow failure, export completion, integration health and budget thresholds. Store type/title/body/entity reference/read/actionability/action URL; dedupe by tenant/user/underlying-event key and re-authorize the linked resource at display/navigation time. Users may configure non-critical channel/digest/quiet-hour preferences; security and ownership notifications cannot be disabled.

Integration connections, encrypted credentials, sync cursors/status and provider health are tenant-scoped. OAuth connect/callback state is single-use and provider-scoped; list credentials masked only, display a new secret once, and prevent deletion while an active workflow references it.

# Database Specification

## Physical rules

Database: `airevenueos`; extensions UUIDv7/pgvector. Schemas: `public` (plans, flags, templates, permissions, Alembic), `app` (tenant/business data), `audit` (immutable events, consent, outbox), `analytics` (materialized rollups). All tenant-owned tables have `id uuid`, `tenant_id uuid not null`, `created_at`, `updated_at` via trigger, and `deleted_at` where soft deletion applies. Index tenant first; use partial indexes for active/non-deleted rows, GIN only for queried JSONB, BRIN for append-only time series, and covering indexes for hot lists.

RLS policy template:

```sql
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
```

Set it transaction-locally in API, worker, scheduler, migration test and support paths. Test an allow and deny path for every tenant-owned repository/query.

## Canonical data catalog

| Area/tables | Required data and constraints |
|---|---|
| Reference | `plans(code unique,features,max_users,max_leads,price_inr>0,sort,is_active)`; `feature_flags(code unique)`; `industry_templates(code unique, lead_schema,qualification_rubric,pipeline_stages,message_templates,active)`; `permissions(code unique,resource,action)` |
| Tenancy | `tenants(name,slug unique,plan,status trial/active/suspended/deleted,settings,timezone,currency,locale,branding,logo,color,billing GSTIN/address)`; `subscriptions(tenant unique,plan,razorpay_subscription_id,status,billing_period,period_start/end)`; `tenant_industry_templates(tenant,template,template_version,customizations,divergence,applied_at; unique tenant/template)`; `usage_counters(tenant,meter,period,quantity,source_event unique)`; audited feature overrides (environment/tenant/plan/cohort/emergency). Commercial subscription records are separate from customer-collection payments. |
| Users/RBAC | `users(tenant,email,full_name,phone,avatar,password_hash,status invited/active/suspended/deactivated,timezone,branch,deleted_at; unique tenant+email active)`; `roles(tenant,name,is_system; unique tenant+name)`; `role_permissions(role,permission)`; `user_roles(user,role)`; `refresh_tokens(user,jti unique,token_hash,family_id,expires_at,revoked_at,metadata)`; Google identities/tokens (user,google_sub unique,encrypted access/refresh/ID token,scope,expiry); TOTP/recovery-code and invite/reset records. `branches(name/code unique per tenant,address,timezone,headquarters)`; `teams(branch,name unique per branch,lead)` with membership tables. |
| CRM | `contacts(first/last name,email,phone,company/title,status,source,address,custom_fields jsonb,tags jsonb,assignee,last_contact_at; active email unique per tenant when present)`; `accounts(name,industry,website,phone,address,owner,annual_revenue,employee_count,custom_fields; active name unique per tenant)` plus account-contact link; `pipelines(entity_type,name unique per tenant,default/active)`; `stages(pipeline,name,position,probability,color,required_fields,transition rules)`; `deals(contact/account,pipeline,stage,title,amount_minor INR,probability,status open/won/lost/abandoned,loss_reason,version)`; immutable `activities(type note/call/email/meeting/task/status_change/whatsapp/system,subject,entity reference,metadata)`; tasks, notes, tags, custom-field definitions, saved views, attachments and SLA records |
| Leads | `forms(type embedded/popup/landing/click,schema,source)`; `leads(source,source_channel,capture jsonb,qualification_score 0..100,category hot/warm/cold,reasoning,qualified_by,status,assignee,conversion refs,version)`; `lead_enrichments(provider,raw,extracted,status)`; dedupe/source-event table with source idempotency uniqueness |
| Channels/inbox | `channels(type whatsapp/email/web_chat/voice/sms,encrypted_credentials,settings,is_active; unique tenant+type/channel)`; `message_templates(channel,name,content,status draft/pending/approved/rejected)`; `conversations(contact/lead,primary_channel,status active/resolved/archived/spam,assignee,subject,last_message_at)`; monthly-partitioned immutable `messages(conversation,sender,channel,direction inbound/outbound,content,content_type text/image/video/audio/document/location/template/interactive,media,status pending/sent/delivered/read/failed/bounced,external_id unique,metadata)` |
| Appointments | `appointments(contact,deal,organizer,title,location type virtual/physical/phone,start_at,end_at check end>start,status scheduled/confirmed/completed/cancelled/no_show,calendar_event_id)`; availability/slot/resource/reminder/booking lock tables |
| Documents | `files(tenant,owner,object_key,name,size,mime,sha256,scan_status pending/clean/quarantined/rejected,classification,expires_at)`; `document_templates(type proposal/invoice/contract/nda/quotation/receipt/agreement/other)`; `documents(template,contact/deal,status draft/generated/sent/viewed/signed/expired/void,s3_key,content metadata,expires_at)`; `document_requests`, `signature_requests`, extraction/review and knowledge-chunk tables |
| Payments | Immutable append-only `payments(external_payment_id unique,amount_minor>0,currency INR,status created/attempted/captured/failed/refunded,method upi/card/netbanking/wallet/emi/upi_intent,razorpay payload,reconciliation_status)`; enforce transition `created -> attempted -> captured|failed`, separately record refunds; `invoices`, payment links and reconciliation records |
| Workflows | `workflow_definitions`, immutable `workflow_versions(content canonical JSON,content_hash,parent_version,status)`, triggers/nodes/edges, executions, node executions, approvals, schedules, webhooks, outbound webhook deliveries, dead letters, run logs and kill switches. Executions pin a version. |
| AI | `prompts(task/version/status/template/model config/schema/fewshots/audit)`, `ai_usage_records(tenant,user,task,provider,model,input/output/cache tokens,cost,request,date)`, evaluation sets/runs, embedding/chunk tables and safe conversation summaries |
| Audit/outbox | Monthly-partitioned immutable `audit_logs(actor,actor_type,action,resource,resource_id,old/new redacted metadata,IP,user_agent,correlation_id,created_at)`; immutable `consent_records(subject,type marketing/communication/data_processing/whatsapp_optin,channel,status,evidence,policy_version,withdraws)`; daily-partitioned `event_outbox(event_id,type,payload,occurred_at,processed_at,attempts)` |
| Operational | `notifications(user,type,title,body,entity reference,is_read,is_actionable,action_url,underlying_event unique per user)`; `notification_preferences`; `integration_connections(provider,name,encrypted config,scopes,status,connected_at,last_sync_at)`; encrypted credential records; `imports(entity,mapping,mode,status,rows/errors,source file,created_by)`; `exports(type,filters,status,s3_key,expires_at,requested_by)`; `dashboards(user,name,is_default,layout)` and `dashboard_widgets(dashboard,type,title,config,grid position)`. |
| Analytics | Materialized daily lead/revenue, pipeline, conversation and tenant-health rollups. Refresh without blocking, then drill into source records under permission checks. |

`updated_at` is trigger-managed. Business entities use soft deletion; activity, message, payment, consent, audit, outbox and event history are append-only. Messages retain 36 months by partition; outbox seven days; AI qualification input/history 12 months then anonymized aggregate; tenant deletion purges after 90 days unless legal hold; consent/payment retain seven years (archive to Glacier); audit retains at least 24 months then archive per legal policy.

## Database operational targets

Use RDS Multi-AZ, PITR/backups, daily restore verification and `pg_dump` logical export tests. Design target RPO is 5 minutes; product acceptance permits no worse than 15 minutes. Target regional recovery is <4 hours; database failover service target is 15 minutes. Partition ahead, monitor bloat/query plans, and run `ANALYZE`/vacuum operationally.

# API Contracts

## Universal contract

Production: `https://api.{tenant_slug}.airevenueos.io/v1`; sandbox uses the sandbox tenant host; local is `http://localhost:8000/v1`. The Next.js BFF uses `/api/*` only as a browser-facing proxy/broker; it does not redefine the public API.

Use `Authorization: Bearer <access-token>` for protected calls, `Idempotency-Key` for externally repeatable creates, `If-Match` for optimistic PATCH, `X-Request-ID` when supplied, and a signed webhook header for webhook endpoints. JSON body limit is 10 MB. Protected file uploads default to 50 MB, public uploads 25 MB; an explicitly approved endpoint/plan exception may allow 100 MB. Multipart is file-only; metadata is validated separately.

Success:

```json
{"success":true,"data":{},"meta":{"request_id":"uuid","timestamp":"ISO-8601","version":"v1","pagination":{}}}
```

Failure:

```json
{"success":false,"error":{"code":"VALIDATION_ERROR","message":"Human-safe message","details":{}},"meta":{"request_id":"uuid","timestamp":"ISO-8601","version":"v1"}}
```

Standard list filters support `page`/cursor, `page_size` 1–200 (default 50), sort, sparse `fields`, `include`, and documented filter operators. DELETE is soft unless documented otherwise. Create idempotency is retained 24 hours. PATCH uses ETag/version and returns `412 PRECONDITION_FAILED` on conflict. Common errors: `VALIDATION_ERROR`, `UNAUTHENTICATED`, `TOKEN_EXPIRED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `RATE_LIMITED`, `FEATURE_NOT_AVAILABLE`, `QUOTA_EXCEEDED`, `PROVIDER_UNAVAILABLE`, `IDEMPOTENCY_CONFLICT`, `PRECONDITION_FAILED`, `INTERNAL_ERROR`.

## Resource shapes and endpoint manifest

Notation: `L`=list, `C`=create, `R`=read, `U`=update, `D`=soft-delete. A resource declaration `X: L/C/R/U/D` means `GET/POST /x`, `GET/PATCH/DELETE /x/{id}` with its canonical database/resource shape, tenant/scope filter, permission check, audit, validation, and standard response. Every non-CRUD operation below specifies its input/output effect. `[]` denotes the permission family.

| Area | Contract |
|---|---|
| Health/meta | `GET /health`, `/health/liveness`, `/health/readiness`, `/health/metrics` (internal/IP-restricted), `/version`; public health exposes no secret/provider detail. |
| Auth | `POST /auth/signup`, `/login`, `/logout`, `/logout-all`, `/refresh`, `/forgot-password`, `/reset-password`, `/verify-email`, `/mfa/setup`, `/mfa/verify`, `/mfa/disable`, `/mfa/recovery`; `GET /auth/google/authorize`, `/auth/google/callback`, `/auth/me`, `/auth/sessions`; `DELETE /auth/sessions/{id}`. API keys are `POST/GET/DELETE /auth/api-keys[/{id}]`; list values are masked and create reveals the key once. Inputs are credential/OAuth/MFA payloads; browser-facing BFF outputs are user/session and cookie operations, never token secrets in JSON. |
| Tenant/onboarding | `GET/PATCH /tenant`; `POST /tenant/transfer-ownership`, `/tenant/verify-domain`, `/tenant/export`, `/tenant/delete-request`; `GET /tenant/usage`, `/tenant/feature-flags`; `onboarding: GET state, PATCH state, POST complete`. Owner-only destructive/billing/export actions require re-auth/MFA. |
| Plans/billing | `GET /plans`, `/subscriptions`; `POST /subscriptions/checkout`, `/subscriptions/cancel`, `/subscriptions/resume`; Razorpay webhook is separate. Checkout returns hosted-session/order reference only. |
| Users/RBAC | `users: L/C/R/U/D`; `POST /users/{id}/resend-invite`, `/deactivate`, `/reactivate`; `roles: L/C/R/U/D`; `POST /roles/{id}/permissions`; `GET /permissions`; team/branch membership endpoints. Role/permission mutation invalidates sessions/permission cache. |
| Branches/teams | `branches: L/C/R/U/D`; deletion fails while users are assigned. `teams: L/C/R/U/D`; filter teams by branch, maintain member/lead assignment, and require name uniqueness within a branch. All updates require ETag. |
| Templates/config | `custom-fields: L/C/R/U/D` (field key unique per entity, type immutable after creation; select/multi-select require options); `templates/email: L/C/R/U/D`; `GET/PATCH /config/tenant`; workflow templates are read-only catalog entries until cloned. |
| CRM contacts/accounts | `contacts: L/C/R/U/D`; `POST /contacts/bulk` (maximum 1,000, per-record result; create/upsert matched by email/phone), `/contacts/{id}/merge`, `/contacts/{id}/assign`, `/contacts/{id}/tags`; `accounts: L/C/R/U/D`; account-contact link/unlink. Contact create/update requires email or phone; merges return survivor and audit map. |
| Activities/tasks/notes | `activities: L/C/R`; `tasks: L/C/R/U/D`; `POST /tasks/{id}/complete`, `/reopen`, `/assign`; `notes: L/C/R/U/D`; entity timeline `GET /{entity}/{id}/timeline`. Immutable activity events are generated by mutations and may not be edited. |
| Leads | `leads: L/C/R/U/D`; `POST /leads/bulk` (maximum 5,000, per-record result), `/deduplicate`, `/{id}/merge`, `/{id}/assign`, `/{id}/convert`, `/{id}/qualify`, `/{id}/disqualify`, `/{id}/restore`; `GET /leads/{id}/duplicates`, `/qualification`, `/history`. Qualification input can request AI/manual mode; output includes score/category/evidence/reasons/missing fields/provenance/reviewer state. |
| Imports/exports | `POST /imports` accepts CSV/XLSX <50 MB with entity, mapping, defaults, create/upsert and match key; return `202` job. `GET /imports`, `/{id}`, `/{id}/errors`, `POST /{id}/cancel`; `POST /exports` returns `202` private async job, then list/read/download authorized expiry-limited results. No synchronous full-data export. |
| Lead forms/webhooks | `forms: L/C/R/U/D`; `POST /forms/{id}/publish`, `/unpublish`, `/preview`; form submissions are defined by the public contract below. `POST /webhooks/leads/{source}` validates source signature and returns accepted event ID. |
| Public forms/files/knowledge | `GET /public/forms/{form_id}/config`; `POST /public/forms/{form_id}/submit` validates published schema and anti-abuse token. `POST /public/upload` requires constrained public token, allowed MIME and <25 MB. `GET /public/knowledge/articles` and `/{slug}` expose only published articles and obey tenant knowledge privacy policy. |
| Pipelines/deals | `pipelines: L/C/R/U/D`; `stages: L/C/R/U/D`; `deals: L/C/R/U/D`; `POST /deals/{id}/move-stage`, `/assign`, `/mark-won`, `/mark-lost`, `/reopen`; `GET /deals/board`. Stage action requires mandatory fields/loss reason and returns updated version/ETag. |
| Tags/custom fields/saved views | `tags: L/C/R/U/D`; `custom-fields: L/C/R/U/D`; `saved-views: L/C/R/U/D`; `POST /bulk/{resource}` accepts bounded IDs + permitted operation and returns async result/job where expensive. |
| Conversations/messages | `conversations: L/R/U`; `POST /conversations`, `/{id}/assign`, `/{id}/resolve`, `/{id}/reopen`, `/{id}/handoff`, `/{id}/spam`; `GET /conversations/{id}/messages`; `POST /conversations/{id}/messages`, `/messages/{id}/retry`, `/messages/{id}/redact`. Send validates channel/template, consent, quiet hours, frequency, opt-out, scope, idempotency and returns queued provider-safe message state. |
| Channels/templates | `channels: L/C/R/U/D`; `POST /channels/{id}/connect`, `/test`, `/disconnect`, `/sync`; `GET /channels/{id}/health`; `message-templates: L/C/R/U/D`; `POST /message-templates/{id}/submit`, `/sync-status`, `/preview`. Credentials are write-only/redacted. |
| Webchat | `GET/PATCH /chat-widget/config`; `POST /chat-widget/sessions`, `/chat-widget/sessions/{session_id}/messages`; `GET` the latter with message cursor. A public session token is constrained to widget/origin/conversation. Tenant endpoints manage domains, branding, transcript and handoff. |
| Voice (conditional) | `GET /voice/calls`, `/voice/calls/{id}`, `/voice/recordings/{id}`; `POST /voice/calls`, `/voice/transcribe`; `PATCH /voice/calls/{id}` for note/outcome only. Outbound calls return 202 and remain feature-disabled until provider/legal/consent gates pass. |
| Appointments | `appointment-types`, `availability`, `resources`, `appointments`: L/C/R/U/D; `POST /public/booking/resources/{resource_id}/slots`; `POST /public/booking/appointments`; `GET /public/booking/appointments/{id}` with booking token; `POST /appointments/{id}/confirm`, `/cancel`, `/complete`, `/no-show`; calendar sync endpoints. Public booking returns 409 for taken slot and uses idempotency + optimistic slot lock. |
| Documents/files/signatures | `document-templates: L/C/R/U/D`; `documents: L/C/R/U/D`; `POST /documents/{id}/generate`, `/send`, `/void`, `/duplicate`, `/extract`, `/review-extraction`; signature-request create/send/remind/cancel/status. Files: `POST /files/initiate`, `/complete`, `GET /files/{id}`, `DELETE /files/{id}`; initiation returns constrained presigned URL, completion returns `pending_scan`; download only after clean/authorized. |
| Payments/invoices | `payments: L/R`; `POST /payments/orders`, `/payments/{id}/retry`, `/payments/{id}/refund`; `invoices: L/C/R/U/D`; payment links create/list/deactivate; `POST /webhooks/inbound/razorpay`. Order response includes server-computed amount/currency/order ID; refund requires elevated approval/MFA per threshold; webhook only acknowledges verified/deduped events. |
| Workflows | `workflows: L/C/R/U/D`; `POST /workflows/{id}/validate`, `/test`, `/publish`, `/pause`, `/resume`, `/clone`, `/rollback`, `/execute`, `/kill`; `GET /workflows/{id}/versions`, `/executions`, `/executions/{execution_id}`, `/logs`; approvals list/read/approve/reject/escalate; schedules and inbound webhook configuration. Requests use the restricted JSON DSL defined below; executions return pinned version and state. |
| AI | `POST /ai/chat` (SSE), `/ai/generate`, `/ai/qualify-lead`, `/ai/extract`, `/ai/summarize`, `/ai/search`, `/ai/analyze`, `/ai/transcribe`, `/ai/translate`; `GET /ai/usage`, `/ai/health`, `/ai/prompts`; prompt draft/test/promote/rollback endpoints are privileged. Every response provides provider/model/request/cost-safe metadata; mutations/external sends remain confirmation-gated. |
| Analytics | `GET /analytics/dashboard`, `/funnel`, `/sources`, `/sla`, `/qualification`, `/appointments`, `/payments`, `/team`, `/usage`; `POST /analytics/exports`; `GET /analytics/exports/{id}`. Every report accepts date range/timezone/filter and returns definition/denominator/drilldown-safe identifiers. |
| Audit/compliance | `GET /audit-logs`, `/consent`, `/privacy/requests`, `/support-access`; `POST /consent`, `/consent/revoke`, `/privacy/export`, `/privacy/delete`, `/support-access/request`, `/support-access/revoke`; access and export receipts are auditable. |
| Notifications | `GET /notifications`, `/notifications/unread-count`; `POST /notifications/{id}/read`, `/notifications/read-all`; `PATCH /users/me/notification-preferences` with channel/digest/quiet-hour settings. Notifications always belong to the requesting user. |
| Integrations/developer | `GET /integrations`; `POST /integrations/{provider}/connect`, `/callback`; `DELETE /integrations/{id}`; list/create/delete `/integrations/credentials` (masked list, value write-only, deletion denied when active workflow references it). API keys use `/auth/api-keys`. Outbound webhook configs use `GET/POST /webhooks/outbound/configs`, `GET/PATCH/DELETE /webhooks/outbound/configs/{id}`, `POST /webhooks/outbound/configs/{id}/test`, `GET /webhooks/outbound/deliveries`, `POST /webhooks/outbound/deliveries/{id}/retry`; config creation returns the signing secret once. Add IP allow-list and API-usage endpoints. |
| Admin/platform | Platform-only tenant lookup, suspension, plan/feature management, incident/support approval, audit and operational health endpoints. They require separate platform authorization and cannot use ordinary tenant routes. |

### Realtime and webhooks

WebSocket/SSE authorization is established before subscription; channels are tenant/user/resource scoped and rechecked on token/role/tenant change. Events include correlation ID, resource version and permitted payload only. Reconnect uses cursor/last event ID and reconciles with REST.

Outbound webhook payload:

```json
{"event_id":"evt_uuid","event_type":"lead.created","tenant_id":"uuid","timestamp":"ISO-8601","version":"1.0","data":{},"links":{"self":"resource URL","related":"related resource URL"}}
```

Event types: contact create/update/delete/merge; account create/update/delete; lead create/update/converted/assigned; opportunity create/update/stage-changed/won/lost; task create/update/completed; appointment booked/cancelled/rescheduled/completed; payment succeeded/failed/refunded; conversation create/message-received/closed; document uploaded/signed/shared; workflow execution started/completed/failed; approval requested/approved/rejected; system quota-warning/integration-disconnected.

Send HTTPS only with `X-AIRev-Signature: t=<timestamp>,v1=<HMAC-SHA256(body,secret)>` and `X-Idempotency-Key: <execution_id>:<action_index>`; at-least-once delivery, five retry attempts over 24 hours, delivery log and DLQ. Inbound provider routes are `/webhooks/inbound/{razorpay|email/{provider}|sms/{provider}|whatsapp/{provider}|voice/{provider}|signature/{provider}}`; tenant custom ingress is `/webhooks/inbound/custom/{webhook_id}`. Verify source signature, timestamp/replay window, IP policy where available, idempotency event ID and body schema before enqueue. Acknowledge quickly; never perform business work synchronously.

### API entitlement/rate limits

Developer API default tiers: Starter 300/min, Growth 1,000/min, Enterprise 5,000/min per key/tenant; lower endpoint-specific limits always win. Per-plan limits are: contacts 1k/10k/unlimited; storage 5/50/500 GB; AI calls 100/1k/10k monthly; active workflows 5/25/100; users 3/15/unlimited; email 200/2k/20k daily; SMS 50/500/5k daily; upload 25/100/500 MB; import batch 1k/5k/50k; webhook destinations 3/15/50; API keys 2/10/50; audit retention 90/365/2,555 days. See Authentication & Security for login, AI, files, bulk and webhook limits. Return `429` with reset/retry metadata; do not leak tenant existence.

# Authentication & Security

## Identity/session architecture

Next.js is the browser authentication broker. It stores only a host-only, Secure, HttpOnly, SameSite=Lax refresh-session cookie satisfying `__Host-` semantics (`Path=/`, no `Domain`) and proxies/refreshes server-side; browser JavaScript never reads a token. FastAPI validates short-lived bearer access tokens.

- Email/password and Google OAuth are required. Magic links are Phase 2; SSO Phase 3; API keys are developer-only; TOTP is required for Owner/Admin and optional for other roles.
- Password: minimum 12, breached-password (HIBP) check, Argon2id `t=3,m=65536,p=4,hash=32,salt=16`, history 5, 5 failures lock 15 minutes. Admin-role passwords expire after 90 days; standard-user passwords do not expire.
- Google: 256-bit one-time `state` in Redis for 10 minutes; validate state, nonce, issuer, audience, expiry and exact redirect URI. Scopes: OpenID/profile/email and only approved Calendar/Gmail scope. Account linkage requires explicit authenticated confirmation.
- Access JWT: RS256, 15-minute expiry, KMS-protected signing key/JWKS, claims `sub,tenant_id,tenant_slug,email,name,roles,permissions,branch/team scope,jti,iat,exp,iss`; revocation `jti` blocklist in Redis. Never use generic HS secret in production.
- Refresh token: opaque, hashed, 7-day sliding lifetime, rotates on use, family reuse revokes all family sessions and sends security event. Max 10 sessions/user (evict oldest); idle re-auth at 2h, hard re-auth at 8h. Password reset revokes all sessions; role/tenant revoke invalidates access immediately/at next authorization check.
- TOTP follows RFC 6238. Encrypt seed; issue eight bcrypt-hashed recovery codes; demand MFA/re-auth for billing, exports, tenant deletion, ownership transfer, API keys, security settings and high-value refunds.

Use CSRF double-submit cookie/header for every unsafe BFF request and strict Origin/Referer fallback. CORS has explicit trusted origins only; never wildcard credentialed origins; reject `null`; OPTIONS returns 204.

## Authorization

Permission format is `resource:action`, enforced server-side before use case and query. Role matrix:

| Resource | Owner | Admin | Manager | Member/Sales/Support | Viewer/Auditor |
|---|---|---|---|---|---|
| Tenant, billing, ownership | all; transfer/delete/billing | settings except ownership/restricted billing | limited configured settings | no | read permitted only |
| Users, roles, branches | all | invite/update/deactivate/roles | team/branch operations only | self/profile only | read where granted |
| Leads/contacts/deals/tasks | all | all except policy-restricted destructive | create/read/update/assign/merge/export team scope | create/read/update assigned/team scope; support inbox scope | read scope only |
| Inbox/channels | all | configure channels; all operations | assign/manage team operations | own/assigned conversations and permitted sends | read scope only |
| Appointments/documents | all | all | operational all/team | assigned/allowed create/update/read | read scope only |
| Payments | all incl Razorpay configuration | read/invoice/approved operations; no owner-only config | read/link/invoice permitted | create payment link where granted | read only |
| Workflows/analytics/AI | all | create/manage/export | create/manage/run/report | run/use permitted templates/reports | read permitted reports |
| API keys/webhooks/audit/compliance | all | developer/config/audit per grant | read operational logs where granted | none unless explicitly scoped | audit/read only |

Scope predicates are `global`, `branch`, `team`, or `self/assigned`; apply them in list query and object read/write, not after fetching. Custom roles are tenant-scoped, permission-allowlisted, capped by policy, and force permission/token refresh within 15 minutes. Owner transfer requires exactly one resulting owner and audit trail.

## Data, secrets, privacy and file security

- TLS 1.3 for application endpoints (ALB compatibility baseline TLS 1.2 policy), TLS to Redis/PostgreSQL with verification, mTLS for approved internal links. Encrypt at rest with envelope encryption: KMS master key -> tenant KEK (encrypted stored) -> per-record DEK; AES-256-GCM, fresh 12-byte nonce/DEK per write; KEK rotate 90 days, master annually.
- Store production credentials only in AWS Secrets Manager/KMS with least-privilege task roles. No secret in code, image, browser bundle, logs, issue, test fixture or Terraform state. Use break-glass audited access and scheduled rotation.
- Classification: P0 public, P1 internal, P2 confidential, P3 restricted PII, P4 secrets. Redact P3/P4 from logs/traces/AI unless an approved minimal policy permits it. Data residency is Mumbai. Support DPDP consent/purpose/minimization/access/correction/deletion/breach workflow; aim GDPR readiness. Report qualifying breach through the approved 72-hour process.
- File flow: authorize initiation -> constrained S3 presigned upload -> completion -> ClamAV/content-type/magic-byte/size scan -> clean/quarantine/reject -> authorized signed download (5 min). UUID object names; owner/tenant check; whitelist types; 50 MB/user file and 500 MB daily default; reject archives/high expansion ratio (>100), unsafe SVG/PDF JavaScript, CSV formula injection; strip EXIF where required.
- Payment: server determines amount/order; verify Razorpay HMAC/signature and external ID; idempotent webhooks/transitions; no PAN/card storage/logging; refund over INR 10,000 requires MFA/approval.

## Abuse prevention, audit, providers and support

Redis sliding-window limits: login 5/15m/IP and 20/hour/account; refresh 10/min/user; Google 5/min/IP; MFA 5/5m/user; password reset 3/hour/email; standard API 60/s, 600/min, 10k/hour/user; inbox read 30/s/send 10/s; socket connection 5/min; lead bulk 10/min tenant; contact import 5/hour tenant; export 5/min user; file 30/min user; developer 300/min/key (paid 3k); provider webhook source limits as configured. AI limits appear in AI System.

Audit immutable auth, authorization, CRUD/bulk, payment, workflow, AI, consent, configuration, provider, secret/access and support events. Include actor/service, tenant, action, resource, correlation, IP/user agent, redacted before/after and outcome. Never log password/token/raw card/secret. Support access is tiered, purpose-bound, time-limited (maximum 30 minutes for elevated access), bannered, dual-approved where required, and never direct production DB access.

Provider ingress uses HMAC/signature, replay window <5 min, dedupe and asynchronous enqueue. Provider egress uses HTTPS, signed payloads, egress allow-list and retry/DLQ. Apply OWASP ASVS L2 baseline, dependency/SAST/DAST/container/IaC scans, threat modeling, quarterly pen test, incident playbooks and security alerting.

# AI System

## Architecture and control plane

All model use passes through `AIGateway`; product modules never call providers directly. Pipeline: authorize/entitle -> task schema -> input guard -> prompt/version/context assembly -> provider router -> tool loop -> output guard/schema validation -> usage/audit/trace -> human confirmation when required. Persist only approved, minimized data. Gate every mutation, send, scheduled action, document generation, payment, or sensitive decision behind explicit confirmation and ordinary RBAC.

`AIGateway` contract accepts `task_id`, category, messages, allowed tools, response schema, temperature/max output and request metadata; returns normalized text/structured output, provider/model, usage, latency, tool trace and safe warnings. It supports complete, streaming SSE, embedding, health, and cancellation.

| Task/category | Target | Default use/control |
|---|---:|---|
| Chat/copilot | first token <3s | streaming, no autonomous external action |
| Generate reply/template/document | <5s | human review before send/use |
| Classify lead/sentiment/intent | <2s | optional/spot-checkable |
| Extract fields/document facts | <2s | structured schema, provenance, review |
| Summarize | <5s | optional; raw source always available |
| RAG | <3s | cite tenant-filtered source chunks |
| Analyze | <10s async | review before decisions |
| Transcribe | <30s | queued, disclosure/consent where needed |
| Translate | <2s | preserve original/reviewable result |

## Models and routing

Pin versions; never use a provider's `latest` alias:

| Tier/task | Primary | Secondary/fallback |
|---|---|---|
| Pro/default chat, generate, analyze | `claude-sonnet-4-20250514` | `gpt-4o-2024-08-06`, then degraded/manual |
| Basic chat/generate/analyze | `gpt-4o-mini-2024-07-18` | `gemini-2.0-flash-001` |
| Classify/extract | `gpt-4o-mini-2024-07-18` | `gemini-2.0-flash-001`, then Claude Haiku |
| Summarize | `claude-haiku-3-5-20241022` | Gemini Flash |
| RAG/translation | GPT-4o mini | Gemini Flash |
| Transcription | Whisper | queue/manual retry |
| Embeddings | approved OpenAI/Cohere multilingual model | approved alternate with reindex |

Router selection is based on task policy, tenant plan/budget, health/circuit, latency and pinned evaluation outcome—not user prompt. Circuit defaults: five consecutive failures/60 s opens 30 s; half-open permits one trial and closes after three successes. Anthropic threshold is three failures/15 s. Record fallback/degraded state visibly.

Degraded behavior: chat explains temporary limitation; generation offers template/manual; classification assigns neutral 50 and review flag; extraction returns empty/manual; summary displays source; RAG offers keyword search; analysis returns raw/exportable data; transcription queues; translation retains original. Never fabricate a successful AI result.

## Prompts, memory, tools, RAG

Prompts are Git-backed `prompts/<task>/v<n>.yaml` and mirrored/audited in `prompts`: task, version, status (`draft|staging|production|deprecated`), Jinja-sandbox template, strict variables, schema, examples, model configuration and changelog. One production version/task. Promotion requires evaluation, staging shadow (10% for 24h where safe), approval and rollback target. Cache compiled current prompts in Redis with invalidation.

Context order: system/task/schema -> user/entity facts -> recent history -> highest-scoring tenant RAG -> examples; truncate oldest/lowest-value context before model limits. Conversation memory: last 20 turns/8k tokens in Redis 24h, then approved safe summary. Entity context: contact/lead, recent interactions (10), deals, relevant documents, notes (5), prior summaries; all tenant/scope filtered.

Readonly tools: `search_leads`, `get_lead_detail`, `get_conversation`, `search_knowledge_base`, `get_pipeline_stats`. Mutating tools: `create_task`, `schedule_appointment`, `send_message`, `update_lead_stage`, `generate_document`; every one applies RBAC/policy and confirmation. Maximum 5 sequential tool calls and 20/session; per-tool rate limit; scrub PII and truncate outputs to 4k.

RAG uses pgvector: `document_chunks` and `lead_embeddings`, 1536-dimensional vectors, HNSW `m=16,ef_construction=200` (IVFFlat only when justified), mandatory tenant filter. Retrieve top 10, similarity threshold .70, rerank top 5. Chunk: knowledge 512/64 overlap, contracts 256/32, conversation/lead coherent units. Re-embed on source change, hash-skip duplicates, batch lead changes every 5 min, and reindex on embedding-model upgrade.

## Safety, quality, privacy and cost

Input guard detects prompt injection and sensitive/harmful content: block injection >.70, sanitize .40–.70, block harmful >.80; block PAN, Aadhaar, card and bank data, and apply minimum-policy treatment to phone/email/GSTIN/address. Delimit untrusted context; tools never follow document instructions. Output guard validates JSON schema, retries safe formatting once, redacts prohibited PII, blocks toxicity >.70, prompt leakage and unsupported sensitive claims. Claim/numeric/citation checks require source evidence.

AI must not diagnose, give tax/legal advice, autonomously reject candidates, guarantee outcomes, set unverified binding price/inventory/finance terms, or act in restricted high-impact domains. Provider retention must be zero/contractually approved; retain trace metadata/redacted evaluations, not arbitrary customer prompts.

`ai_usage_records` meters input/output/cache tokens, provider/model and cost. Baseline tenant budgets: Basic 1M tokens/month, Pro 5M; alert at 80%, downgrade only policy-approved tasks at budget limit, hard-stop at 100% with manual fallback. Apply per-user limits: copilot 20/min, qualify 30/min tenant, generate 30/min user, summarize 20/min user.

Trace with Langfuse, Sentry, Prometheus/Grafana and structured logs. Alert: AI error >2%/5m (P1), circuit opening (P1), P95 >10s (P2), budget/provider anomaly (P2). Maintain versioned gold sets; promotion requires no regression and >=95% approved baseline where applicable, plus task F1 >=.85 for classification/extraction and grounded-answer/citation metrics. Roll back on hallucination >5%, negative feedback >10%, error >2%, or material latency regression.

# Workflow Engine

## Execution model

The visual builder may use self-hosted n8n only to author/import/export a restricted workflow JSON DSL. n8n has no production credentials, database access, durable execution, tenant runtime data, or authority to execute customer automation. The custom Python/Celery engine parses, validates, versions, schedules and executes all production workflows from PostgreSQL state.

Workflow definition fields: tenant, name (1–200), description (0–2,000), category (`lead_nurture|deal_automation|notification|approval|custom`), active window, version, canonical content hash, trigger, nodes, edges and global policy. Canonical hash normalizes key order, whitespace, NFC strings and numbers. Versions are immutable; one active version; rollback creates/activates a prior version; execution always pins version/hash.

DSL supports DAG nodes `condition`, `action`, `delay`, `approval`, `subworkflow`, `parallel` fork/join, `loop`; edges have source, target, label, condition and priority. Expressions expose only scoped event/entity/workflow variables and allowlisted pure functions (`now`, `uuid`, safe string/JSON/base64 transforms); no arbitrary code, filesystem, shell or network. Global controls: `stop|continue|custom` error policy, concurrency 1–100 (default 10), timeout 60–86,400s (default 3,600), retry 0–10 (default 3; fixed/exponential/linear; initial 1–300s, max 60–3,600s), per-workflow rate limit and concurrency key.

## Triggers, conditions, actions

Triggers: entity create/update/field change, stage change, schedule, cron recurrence, relative time, form submission, inbound message, payment event, appointment event, document event, approval event, threshold/aggregate, inbound custom webhook, and manual run. Conditions cover comparison/logical/entity presence, temporal/business-hours, communication/consent, aggregate and tenant context. All trigger payloads are schema-versioned and tenant-bound.

Actions include create/update/assign lead/contact/deal/task, move stage, add/remove tag, create note/activity, send WhatsApp/email/SMS/in-app, wait/remind/escalate, appointment/document/payment-link actions, webhook/API call, AI task, notification, approval, branch/loop/subworkflow and analytics/event emission. Every action declares input schema, output schema, required permission/feature, retry class, idempotency key, timeout and audit event. Unsafe/irreversible actions require approval nodes or explicit user confirmation policy.

Execution states: `pending -> running -> waiting|completed|failed|cancelled`; node states `pending|running|retrying|completed|failed|skipped`. Parallel joins support all/any/majority/count; loop default 1,000 and hard maximum 10,000 iterations. Approval states are requested/approved/rejected/escalated/recalled with assignee, quorum/strategy, due time, reminders and timeout path. Delay is durable/scheduled, never process sleep.

## Scheduling, queues, reliability

Store UTC instants plus IANA timezone (tenant default, user display). Cron retains original timezone and next UTC occurrence. Scheduler processes due work every 10s; webhook sweep every 60s; maintenance/cleanup 03:00 UTC; metrics rollup every 15m. Business hours/holiday calendars handle DST: nonexistent local time moves to next valid instant; duplicate local time uses later occurrence.

Queues and defaults:

| Queue | Concurrency | Priority | Work/timeout |
|---|---:|---:|---|
| `workflow-critical` | 20 | 10 | payment, inbound, urgent message; 30s |
| `workflow-standard` | 50 | 7 | lifecycle actions; 300s |
| `workflow-bulk` | 30 | 4 | bulk; 900s |
| `workflow-scheduled` | 10 | 5 | timers/cron; 300s |
| `workflow-webhook` | 15 | 6 | outbound webhooks; 60s |
| `workflow-ai` | 10 | 8 | AI actions; 120s |
| `workflow-notification` | 20 | 8 | notifications; 60s |
| `workflow-maintenance` | 5 | 1 | cleanup/recovery |

Use Celery JSON, `acks_late`, reject on worker loss, prefetch 1, hard 600s/soft 480s unless queue action limit is stricter, tenant bucket throttles and 14-day DLQ. Retries follow global -> node -> action override with exponential jitter and retry classification; never retry validation/permission/terminal business failures. Idempotency layers: inbound header/event ID in Redis 24h; execution key from original event; action key `execution:node:attempt` plus database natural constraint. Redis locks enforce workflow/tenant concurrency but database state remains authoritative.

Inbound workflow URLs are `https://api.{tenant_slug}.airevenueos.io/v1/webhooks/inbound/custom/{webhook_id}`. Validate HMAC, timestamp, schema and replay/idempotency; enqueue then return within 2s (accepted response even when downstream work is deferred/DLQ). Outbound webhook events originate through transactional outbox, use signed HMAC, 5 retries with backoff, delivery records and DLQ; do not retry known-invalid `400/422` payloads.

Redact logs using security classification; retain operational logs per policy; support dry-run/replay with no external effects, resumable failed state, manual recovery, tenant/workflow/global kill switches effective <5s, and replay provenance. Targets: critical trigger P95 <500ms, webhook acknowledgment P95 <100ms, and sustained 1,000 executions/minute per tenant without cross-tenant starvation.

## n8n authoring isolation

n8n sessions run ephemeral containers (maximum 4h), authenticate through brokered short-lived access, receive no provider secrets and call only restricted design APIs: validate DSL, list allowed node schemas/templates, save draft, publish through approval. Curated custom nodes mirror restricted trigger/condition/action schemas; arbitrary n8n community nodes, shell, credentials and direct HTTP/database nodes are prohibited.

# Infrastructure

## AWS topology

Deploy dev, staging, production and sandbox in separated AWS accounts/state, all primarily `ap-south-1`. Terraform remote state uses private S3 + DynamoDB locking. VPC spans three AZs with public ALB/NAT subnets and private ECS/RDS/Redis subnets; security groups permit only CloudFront/WAF -> ALB -> ECS and ECS -> RDS/Redis/S3/approved egress. Maintain an isolated DR VPC/account plan; no public database/cache.

| Component | Production standard |
|---|---|
| Edge | Route 53, CloudFront HTTP/2/3, WAF managed rules + SQLi/XSS/bot controls + 2,000 requests/5m rate rule, ACM TLS policy `TLSv1.2_2021`, ALB |
| Web/API | ECS Fargate: web 2–8 tasks (0.5 vCPU/1GB); API 4–12 (1 vCPU/2GB); health checks, rolling deploy/circuit breaker, autoscaling |
| Workers | Separate Fargate services for comms 3–10, AI 2–8, general 2–4 and workflow queues; Spot only bulk/maintenance/ephemeral n8n, never critical queues |
| Database | RDS PostgreSQL 16 Multi-AZ, `r6g.xlarge` production baseline, 500GB gp3 autoscale to 2TB, PgBouncer, PITR 5m, 30-day backups, read replica as demand requires |
| Redis | ElastiCache Redis 7 cluster mode: 3 shards x 1 replica (6 nodes), transit/at-rest encryption, automatic failover, `volatile-lru`; no durable-only state |
| Storage | Private S3 buckets for uploads, documents, exports, logs/artifacts/backups; versioning, KMS, block public access, lifecycle to IA/Glacier, deletion/legal-hold policy |
| Security/ops | ECR, KMS, Secrets Manager, IAM task roles/OIDC GitHub federation, CloudWatch logs/alarms, X-Ray, Sentry, Langfuse, Prometheus/Grafana, PagerDuty/on-call |

## Deployment and operations

Local Compose runs Postgres, Redis, FastAPI, Next.js, Celery workers/beat, n8n and Nginx. Configuration is Pydantic/settings-driven, typed and environment-overridable; `.env` is local only. No production secret reaches image or frontend. Public Next variables are allowlisted and non-secret.

CI: PR runs formatting/lint/typecheck/unit/component/a11y/build, dependency/SAST/SCA/IaC/container scan. `develop` deploys dev; staging runs migrations, contract/integration/E2E, k6, ZAP and approval checks; signed/tagged release promotes the already-built image to production. Production flow: Terraform plan/apply approval, backward-compatible pre-deploy migration, rolling ECS deploy, 5-minute health/circuit observation, smoke/telemetry gate, automatic/operational rollback. Never rebuild an image per environment.

Migrations are release-gated and backward compatible. Health endpoints distinguish live/ready/dependency degraded. Track JSON logs with correlation/tenant redaction, API P50/P95/P99, queue depth/age/retries/DLQ, DB/Redis capacity, provider success/circuit, AI cost/latency, workflow lag, RPO backup success, WAF/security events and business funnel anomalies. Define warning/critical alerts with owner/runbook/escalation.

Backups: RDS PITR + daily snapshots, S3 versioning/replication/lifecycle, Terraform state/versioned artifacts, tested restore at least quarterly. Recovery targets: local service/AZ failure RPO <2m/RTO <30m where replicas apply; full regional recovery RPO 5m/RTO <4h. Cost allocation tags (`environment`, `tenant tier`, `service`, `owner`, `cost-center`), budgets and anomaly alerts are required.

# Testing Requirements

## Test strategy and quality bars

Testing is a delivery responsibility (budget 20% of each sprint) and runs against isolated tenant fixtures. Unit tests cover pure domain/app/client logic; integration tests use real Postgres/Redis/worker and provider sandboxes/fakes; contract tests verify public API/webhook/provider schemas; E2E tests verify real browser journeys; security, accessibility, performance, chaos, DR and AI evaluation are release gates.

| Area | Minimum line/branch (target) | Mandatory focus |
|---|---:|---|
| Backend services/core | 90/85 (95/90) | domain policy, errors, idempotency, concurrency |
| Backend routes | 85/80 (90/85) | auth, validation, response/error contract |
| Models/schemas/permissions | 80/80 (95/90+) | DB constraints, RLS, scope deny paths |
| AI guards/prompts | 95/90 (95/95) | injection/PII/output/schema/fallback/evals |
| Frontend components | 85/80 (90/85) | states, keyboard, permissions |
| Hooks/stores | 90/85 (95/90) | query invalidation, optimistic rollback, tenant switch |
| Utilities/shared validators | 95/90 (100/100) | parsing/money/date/phone/security |
| Application overall | 80/80 | no newly reduced coverage; >2% drop warns/fails by policy |

Mutation targets: services 75%, AI 80%, auth 85%, utilities 75%, hooks 70%; make mutation gating mandatory within three months. New/changed diff coverage meets the module bar. Quarantine flakes only with owner/expiry; recurring flakes are defects.

## Required suites

- **Unit:** domain state transitions, pricing/entitlements, consent/quiet-hours, permission/scope predicates, UUID/validation, AI guard/router/parser, workflow DSL/compiler, retry/backoff/idempotency, UI components/hook behavior.
- **Integration:** Alembic up/down and expand/contract, RLS allow/deny, repositories/UoW/outbox, Redis-down correctness, Celery retry/DLQ, storage scan, Razorpay/WhatsApp/email/calendar sandbox contracts, WebSocket/SSE authorization, endpoint envelope/openapi compatibility.
- **E2E:** owner onboarding; lead form -> dedupe -> qualification -> assignment -> deal; consent-safe inbound/outbound inbox + handoff; public booking under concurrency; document scan/extract/review/sign; payment webhook/reconciliation; workflow approval/retry/kill/replay; dashboard/export; tenant switch/role denial; privacy request.
- **Security/privacy:** SAST/SCA/secret/IaC/container scan each PR; DAST weekly staging and pre-release; quarterly pen test; auth/MFA/session fixation/CSRF/CORS/rate limit/RLS/IDOR/file/webhook/AI prompt-injection tests; PII redaction/retention/DSR testing.
- **Accessibility:** axe automated plus keyboard/manual screen reader (JAWS/Chrome, NVDA/Firefox, VoiceOver/Safari, TalkBack/Chrome). Zero critical/serious violations; Lighthouse accessibility >=95.
- **Performance/reliability:** API P95 read <200ms/write <500ms; web LCP <2.5s, INP <200ms, CLS <.1, TTFB <600ms; shared JS <200KB, route JS <50KB, total initial <2MB. k6 profiles: 500 normal, 1,500 peak, 2,000 spike, 100 noisy-tenant mix. Soak >=8h (24h preferred), chaos provider/Redis/worker/AZ fault, backup restore and DR exercises.
- **AI:** versioned gold sets, F1 >=.85 classification/extraction, grounded citation/faithfulness checks, no >2% regression, guard false-positive/negative threshold, provider fallback/timeout/cost tests. Human reviewers sample sensitive and high-impact tasks.

Pipeline sequence: lint/typecheck -> unit/component -> build -> integration/contract -> security/a11y -> deploy preview -> E2E -> performance/DAST -> staging approval -> production smoke/monitoring. Release is blocked by critical/high security defects, unresolved cross-tenant exposure, failed restore, failed material acceptance criterion, unavailable rollback, missing telemetry/on-call, or noncompliant PII/consent behavior.

# Cross-Module Dependencies

| Producer | Consumer | Contract/dependency |
|---|---|---|
| Tenancy/entitlement | Every module | tenant context, plan/feature/quota and branding/business-hours configuration |
| Identity/RBAC | Every protected API/UI/worker | principal, role permissions, branch/team/self scope, session revoke event |
| CRM/Leads | AI, workflow, analytics, inbox, appointments | lead/contact/deal lifecycle events and authorized entity context |
| Consent/preferences | Communications, workflows, AI, exports | policy gate before contact/processing; revocation cancels queued/running work |
| Communications | CRM, AI, workflow, analytics | immutable conversation/message/delivery/handoff events |
| Appointments | CRM, communications, workflows, analytics | booking/outcome/reminder events and availability lock |
| Documents | AI/RAG, workflows, payments, CRM | scanned file/document/extraction/signature events |
| Payments | Workflows, analytics, audit/subscription | verified payment/refund/reconciliation events only |
| AI Gateway | Leads, inbox, documents, workflows, analytics | task request/result, usage/cost, guard/fallback and human-review state |
| Workflow engine | All domain modules | consumes versioned outbox events; invokes only public application ports/actions; publishes execution/audit events |
| Audit/outbox | Every mutation/provider | transactionally emitted event and immutable evidence |
| Analytics | All business modules | read models/materialized rollups only; never source-of-truth writes |
| Storage | Documents, inbox, exports, AI extraction | tenant-scoped object ownership, scan state and signed URL authorization |

No module may query another module's private ORM model to bypass its application contract. Cross-module synchronous reads are limited to explicit ports and authorization-safe projections; state changes use outbox events. Delete/revoke/tenant-switch events invalidate cache, search/embedding material, sessions, websocket subscriptions, queued automations and signed access as applicable.

# Global Acceptance Criteria

The following are release-blocking MVP criteria. Each must have automated evidence where practical and staged manual evidence otherwise.

1. Eight industry templates complete tenant onboarding with configuration only; no industry code fork.
2. Tenant isolation holds across UI, REST, WebSocket/SSE, workers, analytics, cache, object storage, support and exports.
3. Duplicate capture preserves source event and offers correct normalized candidate handling.
4. Assignment, next action, task and escalation/SLA queues operate under role/team scope.
5. Lead/SLA status is visible and accurate through lifecycle changes.
6. AI qualification returns score, evidence/reasons/missing fields and permits human accept/edit/reject/defer with audit.
7. Any AI/provider/guard failure leaves a clear manual path and never blocks core CRM operation.
8. WhatsApp inbound/outbound delivery is signature-verified, idempotent, tracked and retried without duplicate customer contact.
9. Opt-out/revocation immediately blocks queued and running communications/automation.
10. Human handoff transfers conversation context, ownership and automation stop state.
11. Branded webchat restricts domains/origins, identifies public sessions safely and offers handoff.
12. Concurrent booking cannot double-book a slot/resource; cancel/reschedule/reminders respect policy.
13. Files remain tenant/private, scan before use and cannot be downloaded cross-tenant.
14. Document extraction displays provenance and requires confirmation before material data update/use.
15. Razorpay order amount is server derived, webhook HMAC/idempotency is enforced, and no card data is processed/stored.
16. Workflow drafts validate restricted DSL, test safely, publish immutable version and run with idempotency/retry/DLQ.
17. Workflow pause/kill/replay/approval/version rollback have durable audit and no unsafe duplicate external effect.
18. n8n is authoring-only and has no production execution credential/database path.
19. Dashboards give correct funnel/source/SLA/qualification/appointment/payment/team results, definitions and authorized drilldown.
20. Export is entitlement/role checked, asynchronous, encrypted/private, auditable and tenant isolated.
21. Revoke, deactivation and ownership transfer immediately constrain access and preserve audit evidence.
22. Audit log reconstructs material action, actor/service, correlation, resource and redacted change context.
23. Performance and noisy-tenant tests meet stated SLOs without starving other tenants.
24. Backup/restore evidence meets product RPO <=15 minutes/RTO <=4 hours and stronger infrastructure targets where provisioned.
25. Primary user paths satisfy WCAG 2.2 AA and screen-reader/keyboard verification.
26. Voice is disabled until consent/disclosure/escalation/concurrency/budget and legal acceptance are signed off.
27. Provider outage (AI, WhatsApp, Razorpay, storage, calendar) degrades safely with queue/manual/reconcile behavior and alerting.
28. Feature/tier/plan/quota enforcement is consistent in UI, API, workers and billing/metering.
29. All eight templates enforce prohibited-domain guardrails: no diagnosis, tax/legal advice, autonomous candidate rejection, guaranteed outcomes, or unverified binding price/inventory/finance claims.
30. Privacy data-access/export/delete requests, consent evidence and retention/hold workflow operate end to end.

Release requires every P0 capability, all criteria above, no known cross-tenant issue or critical vulnerability, staging sandbox evidence, backups/rollback/on-call/monitoring/quotas, provider and legal approvals, and a pilot in each enabled industry. Deferred P1 work is feature-flagged with an approved fallback.

# Master Implementation Roadmap

Execute the following milestones automatically and sequentially under the Autonomous execution protocol. Each is independently shippable behind flags and must satisfy the global definition of done. A listed external prerequisite permits a disabled, mocked adapter implementation and does not block later independent milestones; it blocks only real-provider enablement and final GA evidence. In the compact implementation field below: `BE`=backend; `FE`=frontend; `DB`=schema/migration; `API`=contracts; `AI`=AI work; `INF`=infrastructure; `T`=testing; `AC`=acceptance; `OUT`=expected output.

## M01 — Repository and local foundation

**Objective/scope:** establish monorepo, backend modular skeleton, web shell, Compose, standards and developer workflow. **Prerequisites:** none. **Modules:** shared kernel/observability only. **BE:** FastAPI app, settings, error/correlation middleware, health, lint/type/test tooling. **FE:** Next shell, design tokens, providers, Storybook. **DB:** local Postgres/Redis bootstrap. **API:** health/version envelope. **AI:** none. **INF:** Docker, Makefile, pre-commit, GitHub baseline. **T:** lint/type/unit smoke, compose health. **AC:** clean clone runs locally and CI gates pass. **OUT:** reproducible engineering foundation.

## M02 — Environments, IaC, CI/CD, observability

**Objective/scope:** provision secure dev/staging/sandbox/prod foundations. **Prerequisites:** M01. **Modules:** platform. **BE/FE:** container-ready configuration. **DB:** managed RDS/Redis/S3 provisioning. **API:** readiness/dependency health. **AI:** secrets placeholders only. **INF:** Terraform accounts/VPC/ECS/ECR/ALB/CloudFront/WAF/KMS/Secrets/CloudWatch, OIDC CI image promotion. **T:** Terraform/security scan/deploy smoke. **AC:** isolated environments deploy immutable image and emit telemetry. **OUT:** audited deployment pipeline/runbooks.

## M03 — Database, migrations, outbox and tenancy substrate

**Objective/scope:** create durable tenant-safe data platform. **Prerequisites:** M01–M02. **Modules:** tenancy, audit/outbox, shared persistence. **BE:** async UoW/repositories, tenant transaction context, outbox poller. **FE:** none beyond diagnostics. **DB:** UUIDv7, base schemas, plans/templates/tenants/audit/outbox, RLS, partitions, Alembic expand/contract. **API:** internal health/admin bootstrap. **AI:** none. **INF:** RDS backups/PgBouncer/Redis namespaces. **T:** migration, RLS allow/deny, outbox idempotency/restore. **AC:** no tenant query succeeds without scoped context. **OUT:** audited multi-tenant persistence core.

## M04 — Authentication, sessions, RBAC and security baseline

**Objective/scope:** secure access control. **Prerequisites:** M03. **Modules:** identity, tenancy, audit. **BE:** Argon2, Google OAuth, RS256/JWKS, refresh rotation, MFA, permission/scope dependencies, CSRF/CORS/rate limits. **FE:** auth/invite/reset/MFA pages, BFF broker, permission gate. **DB:** users/roles/permissions/sessions/audit. **API:** auth/user/role/session endpoints. **AI:** blocked until guards later. **INF:** KMS keys, Secrets Manager, WAF/security alerts. **T:** auth/session/IDOR/RLS/CSRF/rate-limit suite. **AC:** role/scope denial and token/session revocation proven. **OUT:** production-ready identity boundary.

## M05 — Design system and tenant application shell

**Objective/scope:** accessible navigable product frame. **Prerequisites:** M04. **Modules:** shared UI/tenancy. **BE:** tenant/profile/feature read models. **FE:** layouts, tenant switch, sidebar/topbar, states, theme/branding, responsive/a11y primitives. **DB:** branding/settings additions. **API:** tenant/profile/flags endpoints. **AI:** copilot placeholder only. **INF:** frontend monitoring. **T:** component/a11y/tenant-switch tests. **AC:** authorized user can switch tenant with cache/realtime isolation. **OUT:** reusable dashboard shell.

## M06 — Onboarding, templates, plans and channel readiness

**Objective/scope:** self-serve tenant initialization. **Prerequisites:** M04–M05. **Modules:** tenancy/subscription/templates. **BE:** onboarding state, template application, invites, entitlement/meter checks, channel-test abstraction. **FE:** multi-step onboarding. **DB:** tenant template/subscription/usage tables. **API:** onboarding, plan, tenant config, invite endpoints. **AI:** template rubric storage only. **INF:** billing/provider sandbox secrets. **T:** template/config/no-fork and entitlement tests. **AC:** all eight templates can provision a tenant/configuration. **OUT:** repeatable tenant launch flow.

## M07 — CRM foundation

**Objective/scope:** contacts/accounts, activities, tags, notes, imports and timeline. **Prerequisites:** M06. **Modules:** CRM/audit/storage. **BE:** contact/account CRUD, merge, timeline, imports/exports jobs. **FE:** contact list/detail/forms/timeline. **DB:** contacts/accounts/activities/tasks/tags/saved views/files. **API:** CRM and file contracts. **AI:** none. **INF:** private S3 scan pipeline. **T:** CRUD/merge/scope/file isolation tests. **AC:** authorized users manage canonical customer record with complete history. **OUT:** CRM usable without AI/channel dependencies.

## M08 — Leads, forms, attribution, duplicate handling and assignment

**Objective/scope:** capture-to-workqueue lead operations. **Prerequisites:** M07. **Modules:** leads/CRM/work queues. **BE:** public form/webhook capture, source events, normalization/dedupe, assignment, import. **FE:** lead table/board/detail, form builder/publish, exception queues. **DB:** leads/forms/enrichments/dedupe. **API:** lead/form/public submission endpoints. **AI:** manual qualification fields only. **INF:** public WAF/rate limits. **T:** public abuse, dedupe, attribution, isolation. **AC:** captured duplicate preserves source and produces correct actionable lead. **OUT:** lead intake engine.

## M09 — Deals, pipelines, tasks and SLA

**Objective/scope:** pipeline execution and accountability. **Prerequisites:** M08. **Modules:** CRM/deals/analytics events. **BE:** pipelines/stages, required fields, deal transitions, task/SLA policies. **FE:** pipeline drag/drop, task queues, deal detail. **DB:** deals/pipelines/stages/SLA. **API:** pipeline/deal/task endpoints with ETag. **AI:** none. **INF:** worker scheduling for SLA. **T:** transition/concurrency/scope/SLA tests. **AC:** invalid stage moves fail and overdue work is visible/escalated. **OUT:** operational sales pipeline.

## M10 — Consent, preferences and unified inbox core

**Objective/scope:** policy-safe conversations. **Prerequisites:** M09. **Modules:** consent, communications, audit. **BE:** consent ledger, preferences, conversations/messages, suppression/quiet/frequency policy, assignment/handoff. **FE:** inbox, conversation timeline, consent views. **DB:** channels/templates/conversations/partitioned messages/consent. **API:** inbox/consent/template contracts. **AI:** none. **INF:** realtime service/worker queues. **T:** opt-out cancels queued/running work, message idempotency, realtime auth. **AC:** human can safely manage channel-neutral customer conversation. **OUT:** compliant inbox foundation.

## M11 — Branded webchat

**Objective/scope:** secure public chat channel. **Prerequisites:** M10. **Modules:** webchat/communications. **BE:** widget/domain/session/anti-abuse/handoff service. **FE:** embeddable widget, dashboard configuration, public chat. **DB:** widget/domain/session metadata. **API:** public and tenant webchat contracts. **AI:** optional safe suggestions only. **INF:** CloudFront/WAF/origin rules. **T:** origin/session/rate-limit/handoff E2E. **AC:** only approved domains can initiate safe isolated chat. **OUT:** first live customer channel.

## M12 — AI gateway, prompt governance and lead qualification

**Objective/scope:** safe provider-neutral AI baseline. **Prerequisites:** M10–M11. **Modules:** AI/leads/audit/usage. **BE:** gateway/router/guards/prompts/SSE/usage/evals/qualifier. **FE:** copilot surface, qualification review/provenance/fallback. **DB:** prompts/usage/evaluation/AI review. **API:** AI endpoints. **AI:** pinned models, guardrails, eval set, human confirmation. **INF:** provider secrets, Langfuse/metrics/cost alerts. **T:** injection/PII/schema/fallback/eval tests. **AC:** AI qualification is reviewable, auditable and fails safely. **OUT:** governed AI platform.

## M13 — Documents, extraction, knowledge and RAG

**Objective/scope:** secure document lifecycle and grounded retrieval. **Prerequisites:** M07, M12. **Modules:** documents/storage/AI. **BE:** presigned scan lifecycle, templates/generation/extraction/review/chunking/search. **FE:** uploader/document detail/review/knowledge UI. **DB:** document/signature/extraction/chunk/vector tables. **API:** file/document/signature/RAG contracts. **AI:** extraction/RAG citation workflows. **INF:** S3/ClamAV/vector monitoring. **T:** malware/tenant/download/extraction-provenance/RAG filter tests. **AC:** unscanned/cross-tenant files inaccessible; extracted facts need confirmation. **OUT:** trusted document knowledge base.

## M14 — Appointments and calendar

**Objective/scope:** availability and booking operations. **Prerequisites:** M09–M13. **Modules:** appointments/communications/CRM. **BE:** slot calculation, locking, booking/reminders/outcomes/calendar port. **FE:** calendar/admin availability/public booking. **DB:** appointments/resources/availability/reminders/locks. **API:** booking/appointment contracts. **AI:** optional assisted scheduling behind confirmation. **INF:** scheduler/provider sandbox. **T:** concurrent booking/DST/holiday/reminder tests. **AC:** no double booking; public reschedule/cancel is policy-safe. **OUT:** booking workflow.

## M15 — Email channel

**Objective/scope:** add approved email provider. **Prerequisites:** M10, provider decision. **Modules:** communications. **BE:** email adapter, templates/delivery/bounce/webhook processing. **FE:** compose/template/channel health. **DB:** channel/template/delivery metadata. **API:** channel/template/send contract. **AI:** human-reviewed reply generation only. **INF:** SES/SendGrid secrets/domain DNS. **T:** provider sandbox/webhook/opt-out tests. **AC:** consent/policy/idempotency govern email send/delivery. **OUT:** email integration.

## M16 — WhatsApp channel

**Objective/scope:** MVP primary messaging channel. **Prerequisites:** M10, M12, provider approval. **Modules:** communications/AI/workflow hooks. **BE:** WhatsApp Cloud adapter, template sync, signed webhooks, delivery/retry/reconcile. **FE:** WhatsApp health/template/compose states. **DB:** channel/template/message provider data. **API:** WhatsApp configuration/message contracts. **AI:** approved human-reviewed suggestions. **INF:** provider credentials/alerting/queue scale. **T:** webhook signature/replay/template/opt-out/outage tests. **AC:** no duplicate send, visible delivery failure and immediate opt-out stop. **OUT:** production WhatsApp channel.

## M17 — Payments and invoices

**Objective/scope:** hosted INR collection. **Prerequisites:** M10, Razorpay decision. **Modules:** payments/documents/workflows. **BE:** order/payment/refund/reconcile adapters and state machine. **FE:** invoices/payment links/status. **DB:** immutable payments/refunds/invoices/reconciliation. **API:** order/payment/webhook contracts. **AI:** none. **INF:** Razorpay secret/webhook/WAF. **T:** amount tamper/HMAC/idempotency/refund authorization/reconciliation. **AC:** payment history is correct with no raw card handling. **OUT:** Razorpay payments.

## M18 — Workflow engine and n8n authoring

**Objective/scope:** controlled automation runtime. **Prerequisites:** M09–M17. **Modules:** workflows/all producers. **BE:** DSL compiler, immutable versions, scheduler, executor, approvals, queues/DLQ/kill/replay. **FE:** builder, test/publish/history/execution logs/approvals. **DB:** workflow version/execution/node/schedule/DLQ tables. **API:** workflow/approval/webhook contracts. **AI:** safe AI action node only. **INF:** isolated workflow worker pools/n8n ephemeral authoring. **T:** DAG, retries/idempotency/approval/kill/replay/load tests. **AC:** n8n cannot execute production workflow; custom engine meets critical trigger target. **OUT:** governed automation platform.

## M19 — Voice (conditional)

**Objective/scope:** guarded voice capability. **Prerequisites:** M12, M14, M18 and legal/provider approval. **Modules:** voice/communications/AI. **BE:** provider port, consent/disclosure/recording/escalation/concurrency/budget policies. **FE:** call controls/transcript/consent state. **DB:** call metadata/recording retention. **API:** voice endpoints. **AI:** transcription/summarization under policy. **INF:** approved telecom provider. **T:** consent/recording/outage/escalation tests. **AC:** keep feature disabled until all controls signed off. **OUT:** feature-flagged voice or documented disabled state.

## M20 — Analytics, reporting and exports

**Objective/scope:** decision-ready metrics. **Prerequisites:** M08–M19. **Modules:** analytics/all event producers. **BE:** rollups/definitions/drilldown/export jobs. **FE:** dashboards/reports/filter/timezone/export UI. **DB:** materialized views/export jobs. **API:** analytics/export contracts. **AI:** usage/cost dashboard. **INF:** refresh/worker monitoring. **T:** metric fixture/denominator/timezone/export isolation/perf tests. **AC:** reports reconcile to source records and exported data stays private. **OUT:** governed analytics.

## M21 — Security, quality and performance hardening

**Objective/scope:** close systemic release gaps. **Prerequisites:** M01–M20. **Modules:** all. **BE/FE:** remediation, accessibility/perf/cache/error/observability hardening. **DB:** index/partition/query/retention tuning. **API:** contract backward-compatibility and abuse controls. **AI:** red-team/eval/cost hardening. **INF:** WAF/alerts/scan/backup/least privilege verification. **T:** full security, a11y, load, soak, chaos and mutation gates. **AC:** all global quality bars and no release-blocking vulnerability. **OUT:** release candidate baseline.

## M22 — Resilience and disaster recovery

**Objective/scope:** prove recoverability and operational response. **Prerequisites:** M21. **Modules:** platform/all stateful modules. **BE/FE:** degradation UX/runbook hooks. **DB:** restore/failover/partition verification. **API:** health/degraded behavior. **AI:** provider regional/fallback drill. **INF:** backup restore, DR VPC/account, on-call/incident automation. **T:** AZ/provider/Redis/worker chaos and RPO/RTO drill. **AC:** documented, timed restore meets targets and external outage is safe. **OUT:** signed DR evidence/runbooks.

## M23 — Controlled pilots

**Objective/scope:** validate real users/templates safely. **Prerequisites:** M22 and provider/legal approvals. **Modules:** enabled product set. **BE/FE/DB/API/AI/INF:** feature-flagged pilot operations, telemetry, feedback and support processes; no architecture redesign in pilot. **T:** pilot acceptance suite, production monitoring and regression. **AC:** one approved pilot per enabled industry, no critical isolation/security issue, measured SLO/usage/support evidence. **OUT:** GA decision package.

## M24 — General availability

**Objective/scope:** launch approved scope. **Prerequisites:** M23 and all release gates. **Modules:** all approved P0 modules. **BE/FE/DB/API/AI/INF:** production enablement, quotas/billing, documentation, support/on-call, rollback. **T:** final release smoke, monitoring, restore/rollback readiness. **AC:** all global criteria/P0 evidence, signoffs, no critical vulnerability, stable pilot metrics. **OUT:** GA release and operated service.
