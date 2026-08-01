# ADR 0004: n8n authors workflows; a custom engine executes them

- Status: Accepted
- Date: 2026-08-01

## Context

A visual builder is valuable, but n8n cannot provide durable multi-tenant execution
with the guarantees this product needs: transaction-scoped tenant isolation,
approval gates on irreversible actions, three-layer idempotency, replay provenance
and sub-five-second kill switches.

## Decision

n8n is **design-time only**. It may produce, import and export a restricted JSON DSL
document. It has no production credential, no database access, no durable execution
role, no tenant runtime data and no authority to execute customer automation.

The custom Python/Celery engine (`application/workflows/executor.py`) parses,
validates, versions, schedules and executes every production workflow from
PostgreSQL state.

Isolation is enforced concretely:

- n8n runs in an ephemeral container (maximum four hours), behind a `docker compose`
  profile that is off by default.
- `NODES_EXCLUDE` removes `executeCommand`, `readWriteFile`, `postgres`, `mySql`,
  `ssh` and `httpRequest`. `N8N_BLOCK_ENV_ACCESS_IN_NODE` is set.
- The DSL validator rejects any expression containing `import`, `eval`, `exec`,
  `process.`, `require(`, `fetch(` or `__`, and permits only the scoped roots
  `event`, `entity`, `workflow`, `node`, `trigger`, `now` plus an allowlist of pure
  functions.
- Any action marked `irreversible` or `external_effect` fails validation unless an
  approval node is upstream in the graph.

## Consequences

- The visual authoring benefit is retained without inheriting n8n's execution model.
- The DSL is the contract, so the builder can be replaced without touching runtime.
- Cost: curated custom nodes must mirror the restricted trigger, condition and
  action schemas; arbitrary community nodes are prohibited.
