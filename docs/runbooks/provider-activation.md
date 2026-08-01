# Runbook: activating a gated provider

Every externally gated capability is implemented, tested and disabled. Activation is
configuration plus verification. No code change is required.

## Preconditions common to all providers

1. The external decision is recorded (see `docs/GA-ACTIVATION-CHECKLIST.md`).
2. Credentials are stored in AWS Secrets Manager, never in code, image, Terraform
   state, CI log, issue or test fixture.
3. The ECS task role has least-privilege read on that specific secret ARN only.

## WhatsApp (M16)

**Decision gate:** BSP versus direct Cloud API, credential ownership, template
approval and a named operational owner.

1. Record the decision as an ADR.
2. Store `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`
   and `WHATSAPP_VERIFY_TOKEN`.
3. Point the Meta webhook at `https://api.{slug}.airevenueos.io/v1/webhooks/inbound/whatsapp/cloud`.
   The `GET` challenge must return the challenge value; a wrong verify token returns 403.
4. Submit templates and wait for approval. `message_templates.status` must be
   `approved` before any out-of-window send is permitted.
5. Enable in **staging only**: `FEATURE_WHATSAPP_ENABLED=true`.
6. Verify:
   - `GET /v1/tenant/feature-flags` shows `whatsapp.enabled = true`.
   - `channel_activation_report()` shows `configured: true` with no missing configuration.
   - Send to a test number inside the 24-hour window; confirm one message, one
     `sent` then `delivered` status and no duplicate.
   - Reply `STOP`; confirm the contact is suppressed and every queued automation for
     that contact stops.
   - Post a webhook with a forged signature; confirm 403 and no state change.
7. Enable in production per tenant cohort. Watch `airev_provider_calls_total` and
   `airev_circuit_state` for 30 minutes.

**Rollback:** set `FEATURE_WHATSAPP_ENABLED=false`. In-flight sends queue; nothing is
lost. No deployment is required.

## Email (M15)

**Decision gate:** provider (SES or SendGrid), commercial terms, ap-south-1
availability and sender domain ownership.

1. Verify the sending domain and publish SPF, DKIM and DMARC records.
2. Store `EMAIL_PROVIDER`, `EMAIL_API_KEY` and `EMAIL_FROM_ADDRESS`.
3. Configure the bounce and complaint webhook; confirm a hard bounce adds a
   suppression entry.
4. Enable in staging, send a seed-list test, then enable in production.

**Rollback:** `FEATURE_EMAIL_ENABLED=false`.

## Razorpay (M17)

**Decision gate:** commercial model, collections versus SaaS billing and the
refund/reconciliation policy.

1. Store `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET`.
2. Register the webhook for `payment.authorized`, `payment.captured`,
   `payment.failed`, `refund.created`, `refund.processed` and `order.paid`.
3. Verify in staging with Razorpay test mode:
   - The order amount is server derived. Tampering with the client amount returns
     `VALIDATION_ERROR` and no order is created.
   - A forged webhook signature returns 403.
   - A replayed webhook is deduplicated by `external_event_id`.
   - No card data appears in `payments.provider_payload` or in any log.
   - A refund above INR 10,000 without MFA and an approver is refused.
4. Run reconciliation (every 30 minutes) and confirm zero discrepancies.
5. Enable in production.

**Rollback:** `FEATURE_PAYMENTS_ENABLED=false`. Order creation queues and reconciles.

## Voice (M19) - additional legal gate

Voice cannot be enabled by a feature flag alone. All seven `VoiceControls` must be
`True`: disclosure copy approved, recording consent flow approved, escalation path
defined, concurrency limit set, budget limit set, legal sign-off and provider
contracted. Until then `place_call` returns `FEATURE_NOT_AVAILABLE` and lists the
outstanding controls.

## n8n authoring (M18)

**Decision gate:** hosting, licensing and a named operational owner.

n8n never receives a production credential or database path. Start it with
`docker compose --profile authoring up n8n`. Confirm `NODES_EXCLUDE` still removes
`executeCommand`, `readWriteFile`, `postgres`, `mySql`, `ssh` and `httpRequest`
before granting access.
