# ADR 0001: Modular monolith with independently scalable workers

- Status: Accepted
- Date: 2026-08-01
- Deciders: Platform engineering

## Context

Year-one targets are 5,000 tenants, normal concurrency of 50 and P95 concurrency of
200 users, with up to one million leads per tenant. The team is small and every
request must be tenant isolated end to end.

## Decision

Ship a modular monolith. The API and workers share one deployable codebase and one
PostgreSQL database, but communicate cross-module state changes through domain
events and the transactional outbox rather than direct cyclic calls.

Layering is `API -> application -> domain <- infrastructure` and is enforced
mechanically by `import-linter` (`backend/.importlinter`), not by convention:

- API: HTTP parsing, authentication dependencies, response mapping. No business
  logic, no ORM queries, no provider calls.
- Application: commands, queries, DTOs, orchestration, transactions, permissions, ports.
- Domain: pure entities, value objects, policy and events. No FastAPI, SQLAlchemy,
  Redis, network or I/O of any kind.
- Infrastructure: SQL repositories, provider clients, cache, event transport, storage.

Workers scale independently per queue (`workflow-critical`, `workflow-ai`, and so on)
even though they share the image.

## Consequences

- One transaction can commit a state change and its outbox row together, which is
  what makes at-least-once event delivery correct.
- Cross-module coupling shows up as an import-linter failure in CI rather than as a
  production incident.
- Extraction to a service later is a port swap, because every seam is already an
  explicit protocol (`application/ports.py`).
- The trade-off accepted: a single deployment unit means a bad release affects every
  module. Mitigated by feature flags, kill switches and rolling deploys with circuit
  breakers.
