# ADR 0005: All model access flows through one governed gateway

- Status: Accepted
- Date: 2026-08-01

## Context

AI must never diagnose, give tax or legal advice, autonomously reject a candidate,
guarantee an outcome or set an unverified binding commercial term. It must also
degrade safely: a provider outage cannot block core CRM work.

## Decision

Every model call goes through `AIGateway`. Product modules never call a provider.
The pipeline is fixed: authorise and entitle, task schema, input guard, prompt and
context assembly, provider router, tool loop, output guard and schema validation,
usage and audit, then human confirmation where required.

Key properties:

- **Pinned models.** Exact versions only; `assert_no_latest_aliases()` is a release
  gate. A floating alias would change behaviour without a deploy.
- **Routing is policy driven** by task, plan, budget, circuit health and evaluation
  outcome - never by the user's prompt text.
- **Guards are pure and independently testable.** PAN, Aadhaar, card and bank
  identifiers are blocked before a provider ever sees them; email, phone and GSTIN
  are minimised. Retrieved context is delimited as untrusted and tools never follow
  instructions found inside a document.
- **Industry guardrails are enforced on output**, keyed to the tenant's template
  (`TEMPLATE_PROHIBITIONS`), so a clinic tenant cannot emit a diagnosis even if the
  model produces one.
- **Degradation is explicit per task.** Classification assigns a neutral 50 with a
  review flag; generation offers a template; RAG falls back to keyword search. The
  gateway never fabricates a successful result.
- **Mutating tools are confirmation gated.** `send_message`, `create_task`,
  `schedule_appointment`, `update_lead_stage` and `generate_document` return
  `awaiting_confirmation` with the proposed arguments rather than executing.

## Consequences

- Adding a provider is a `ProviderClient` implementation plus a routing table entry.
- With no credentials configured at all, every AI surface degrades to a documented
  manual path and the product remains fully usable - proven by
  `tests/e2e/test_lead_lifecycle.py::test_ai_qualification_degrades_to_the_rule_engine_without_credentials`.
- Guard false positives are a real cost; thresholds are tuned against versioned gold
  sets and tracked in the nightly AI evaluation job.
