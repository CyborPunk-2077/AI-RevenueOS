# Sangam — project state

**Read this first.** It exists so a new session does not have to rediscover the
repository. Companion file: `docs/CURRENT-REALITY.md` (the feature-by-feature
reality map). Older documents in `docs/` predate 2026-08-12 and describe the
product under its previous name; where they disagree with this file or with the
running system, they are wrong.

Last updated: **2026-08-12**.

---

## 1. Name

The product is **Sangam**. The user-facing UI says Sangam.

The folder, the Git repo, the Docker project (`airevenueos`), the volume
(`airevenueos_pgdata`), the database, the npm scope (`@airevenueos/web`) and the
`AIREVENUEOS_*` environment namespace are all still `airevenueos`/`RevenueOS`.
**This is deliberate. Do not rename any of them.** A namespace migration is a
separate, planned piece of work.

## 2. Vision

Sangam is the connected customer and revenue operations layer for Indian SMEs.
It is **not an ERP** and must never try to become one. It does not replace Tally,
SAP or Odoo, and an SME must never have to migrate its accounting system to use
Sangam's first module.

The spine is one shared customer context:

> Lead → Contact/Company → Conversations → Activities → Follow-ups → Qualification
> → Deal → Appointment → Documents → Payment → Analytics → Automations

Every module reads and writes that same context. WhatsApp, email, appointments
and AI are **not** separate mini-products with their own customer memories.

A business should be able to start with one capability and switch on more later
without migrating data or losing history.

## 3. Commercial strategy

We do not sell the whole platform. Capabilities are enabled one at a time, each
only after it is implemented, tested, visually usable, dogfooded, exercised with
realistic data, understood by the founders, and later shadow-piloted.

**One codebase. One data foundation. Entitlement on top.** Never fork a codebase
per package.

⚠️ **The entitlement mechanism does not exist yet.** Plans and feature flags are
seeded as reference data, but nothing gates a module by plan. The commercial
strategy depends on this and it is unbuilt.

## 4. Current commercial slice

**Lead follow-up and leakage prevention.**

> "Every enquiry gets recorded, assigned, followed up and tracked, so fewer
> opportunities disappear because somebody forgot what to do next."

What we may claim: fewer untouched enquiries, faster first response, fewer
overdue follow-ups, clear ownership, better customer context, better visibility
of next actions.

What we may **not** claim: revenue increases of any percentage, autonomous
selling, staff replacement. No revenue claim until measured against a real
business's before-and-after.

**The core workflow must remain fully usable with AI unavailable.** It currently
is — qualification is rule-based and no model provider is configured.

## 5. Architecture rules that must not be violated

- Layering is enforced by import-linter: `api → application → domain → shared`.
  Infrastructure is an adapter tier; nothing depends on it but the composition
  root, and it may never import the HTTP layer. 6 contracts, all currently kept.
- The API layer must not touch the ORM or provider SDKs directly. Put new logic
  in `application/`, not in a route.
- Every tenant-owned table has row-level security **enabled and forced**. The app
  connects as a role that is neither superuser nor table owner, on purpose.
- `app.activities` and the audit log are **append-only**, enforced by a database
  trigger. Do not disable the trigger — including for seed or test convenience.
- Every state change writes to the transactional outbox in the same transaction.
- No provider may ever fabricate success. An unconfigured channel returns
  "not configured" or "queued", never "sent".
- Do not create per-module copies of the customer. One `contacts`/`accounts`
  spine, shared.

## 6. What is genuinely usable

Browser-verified end to end this session, in the Sangam workspace:

**enquiry → owner → qualification → next action → follow-up → history → deal**

Concretely: Today (operational dashboard), Prospects list and detail, assignment,
rule-based qualification, follow-up queue with overdue filter, activity timeline
on leads, contacts, accounts, deals board, and the Test Centre.

See `docs/CURRENT-REALITY.md` for the full module-by-module map, including what
is partial, backend-only, provider-gated and spec-only.

## 7. External prerequisites (nothing here can be solved by writing code)

| Needed for | Requires |
| --- | --- |
| WhatsApp | Meta WhatsApp Business account + template approval |
| Email | Provider account + verified sending domain |
| SMS | Indian DLT registration |
| Voice | Provider + legal sign-off on recording consent |
| Payments | Razorpay commercial agreement + KYC |
| Google sign-in, calendar sync | Google OAuth app verification |
| File uploads | AWS account, bucket policy, malware scanner |
| AI | A paid model provider |
| Any deployment | AWS account and billing |

None of these is needed for the current commercial slice.

## 8. Dogfood tenant

**Slug `sangam`**, seeded by `backend/src/scripts/seed_sangam.py`, run
automatically by the launcher.

- 15 realistic Bengaluru SME prospects, 6 deals, 11 follow-ups, 16 history items.
- Includes the states the product exists to fix: 4 untouched enquiries, 2 overdue
  follow-ups, 2 due today, an unmerged duplicate, a disqualified prospect with
  its reason, three converted customers, one won deal and one lost deal with a
  loss reason.
- Timestamps are **relative to seed time**, so "overdue by two days" stays true
  whenever it is run.
- Sign-ins: `abhishek@sangam.co.in` (owner, global scope),
  `priya@sangam.co.in` (manager, team), `kiran@sangam.co.in` (member, self).

**The seed is additive and idempotent.** If the tenant already holds prospects it
rewrites nothing, because the founders are expected to use this workspace for
real prospecting. `--refresh` rebuilds the synthetic rows and is the only path
that deletes; it touches no other tenant. It cannot delete activities — the
append-only trigger forbids it — so refreshed runs leave orphaned activity rows
behind. Use `RESET_DEMO.cmd` for a genuinely empty slate.

## 9. How it runs

Double-click **`RUN_DEMO.cmd`** with Docker Desktop running. The launcher starts
the stack, waits for health, migrates, seeds reference data, seeds both demo
tenants and the Sangam workspace, then proves a sign-in works before printing
anything.

- App: http://localhost:3000 — API docs: http://localhost:8000/v1/docs
- Data lives in the `airevenueos_pgdata` volume and survives restarts.
- `RESET_DEMO.cmd` wipes it and makes you type "reset" first.
- Sign-in is rate limited to **5 attempts per IP per 15 minutes**. Keep this in
  mind before adding automated logins anywhere.

For a fixed password (needed by the browser tests):
`powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 -Password "..."`

## 10. Latest test evidence (2026-08-12)

| Gate | Result |
| --- | --- |
| Backend ruff + format | Clean, 220 files |
| Backend mypy (strict) | Clean, 220 source files |
| import-linter | 6 contracts kept, 0 broken |
| Backend unit + contract | **856 passed**, excluding the container-path suites below |
| Permission/RBAC subset | 41 passed |
| Web typecheck | Clean |
| Web lint | Clean, 0 warnings |
| Browser e2e (`sangam-first-slice`) | **1 passed** — full business journey, 11 screenshots |

**19 backend tests fail inside the API container only.** The container mounts
`backend/` at `/app`, so tests resolving repo-root paths (`/prompts`,
`/backend/requirements.lock`, `infra/`, `.github/`) cannot find them. Environment
artefact, not a regression — verified by inspecting the failures. Run the full
suite from the repo root on the host to get a true result.

## 11. Visual evidence

`artifacts/visual-evidence/` — 11 full-page screenshots, regenerated by:

```
$env:DEMO_PASSWORD='sangam-demo-2026'
pnpm --filter @airevenueos/web exec playwright test sangam-first-slice
```

Files `01-sign-in` through `11-test-centre`. The spec asserts the journey as it
photographs it, so a screenshot can only exist if the step actually worked.

## 12. High-priority defects

1. **Analytics numbers are unreconciled.** Charts render; nobody has checked the
   figures against the records. Do not show these to a prospective customer.
2. **The duplicate panel renders "Unknown record"** when the candidate has no
   email — which is precisely the seeded demo case. Should fall back to phone and
   captured company name.
3. **No entitlement gating** (section 3). Blocks the commercial model.
4. **CSV import is untested** against real data despite having a spec.
5. **Invitations cannot reach anybody** — the email channel is gated, so the link
   must be handed over manually.

## 13. Exact next recommended task

**Make the "no reply yet" claim measurable: record first response automatically.**

`first_response_at` is the field the whole leakage story rests on — the Today
dashboard, the "no reply yet" flag and any future before/after measurement all
read it. It is currently only ever set by the seed script. Logging a call,
sending a message or completing the first follow-up against a prospect does not
set it, so the moment a real founder uses Sangam for real prospecting the number
is wrong and quietly stays wrong.

Set it in the application layer the first time an outbound activity is recorded
against a lead, expose "time to first response" per prospect and as a tenant
median, and cover it with a test that proves a second activity does not move it.
That converts the headline metric from seeded fiction into something we could
honestly show a real SME.

---

## Session working rules

- Never reset, stash, discard or rewrite Git history.
- Never delete or recreate a Docker volume to fix a problem. Other unrelated
  stacks share this Docker Desktop — do not touch them.
- Do not activate real WhatsApp/email/payment/voice integrations.
- Do not build mock UI that pretends an incomplete feature works. Label it in the
  Test Centre instead.
- Four levels of evidence are required for user-facing work: the code exists;
  automated checks pass; the owner can see it in a browser; and a realistic
  business scenario demonstrates why it exists. An HTTP 200 is not product proof.
