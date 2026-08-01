# ADR 0003: Externally gated capabilities ship disabled, never faked

- Status: Accepted
- Date: 2026-08-01

## Context

Several capabilities depend on decisions and approvals outside engineering control:
WhatsApp BSP mode and template approval, an email provider and sender domain,
Razorpay commercial terms, voice legal sign-off, n8n hosting ownership and signature
provider agreements. Waiting on them would stall the whole build.

## Decision

For every gated capability, implement the complete path and leave it safely off:

- A provider port in `application/ports.py` and a concrete adapter.
- `is_configured()` returns `False` unless both the feature flag **and** every
  required credential are present. It never returns `True` optimistically.
- An `activation_status()` method naming the exact missing configuration and the
  external prerequisite, surfaced through `GET /v1/tenant/feature-flags` and the GA
  activation checklist.
- Signature verification, replay windows, idempotency, retry and reconciliation
  implemented and tested against recorded payloads with `httpx.MockTransport`.
- The feature flag defaults to `False` in `FeatureFlagDefaults`.
- A runbook describing activation and rollback.

Voice goes further: `VoiceControls` requires seven independent sign-offs, and the
feature flag alone cannot enable it.

**A provider result is never fabricated.** With no credential a send returns
`ok=False, queued=True` with `PROVIDER_NOT_CONFIGURED`, so the work is durable and
visible rather than silently lost or falsely reported as delivered.

## Consequences

- Milestones M15 to M19 are code complete and test complete without any credential.
- The remaining work at GA is configuration and sign-off, enumerated in
  `docs/GA-ACTIVATION-CHECKLIST.md` - not new code.
- `python src/scripts/verify_release_gates.py` fails the build if any gated
  capability is ever defaulted on.
