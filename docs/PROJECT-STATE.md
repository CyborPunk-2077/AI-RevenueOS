# Sangam — project state

**Read this first.** It exists so a new session does not have to rediscover the
repository. Companion file: `docs/CURRENT-REALITY.md` (the feature-by-feature
reality map). Older documents in `docs/` predate 2026-08-12 and describe the
product under its previous name; where they disagree with this file or with the
running system, they are wrong.

Last updated: **2026-08-13** (session 4B: data safety and Claida recovery).

## Accepted checkpoints

Both are annotated tags on `master`; neither has been rewritten.

| Tag | Commit | What it is |
| --- | --- | --- |
| `sangam-baseline-session02` | `405e227` | First commercial slice with truthful first-response measurement |
| `sangam-founder-dogfood-session03` | `d293425` | **Current.** The founders can enter real prospects: quick add, CSV import, duplicate matching, honest outreach recording, daily work queue |

`master` is at the session-3 tag. Session branches are kept rather than deleted,
so `sangam-first-slice` and `sangam-founder-dogfood` still point at their work.

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
- **What counts as answering a customer is defined once**, in
  `domain/leads/first_response.py`: outbound direction, on a channel that reaches
  the customer. Do not re-implement that test anywhere else. When a real provider
  is switched on, feed its events through
  `application/leads/first_response.record_first_response` rather than writing
  `first_response_at` directly.
- **`first_response_at` is never backfilled and never overwritten.** It is set by
  a conditional `UPDATE ... WHERE first_response_at IS NULL`, in the same
  transaction as the activity that justifies it.
- **Operational numbers are computed server-side, in the caller's scope**, in
  `application/leads/metrics.py`. Do not re-derive a count in a page component; two
  definitions of "open" will disagree and the owner will stop believing both.
- **Roles and team membership must be read inside `tenant_session`.** Those tables
  are tenant-owned and RLS-protected, so a platform-scoped session sees none of
  them - which silently demoted every manager to member scope and left team-scoped
  users matching nothing. `application/auth/service.load_roles_and_scope` is the
  one place that resolves them.
- **A mutation returns the state from inside its transaction, never a fresh scoped
  read.** Re-reading after a change that moves a record out of the caller's scope
  reports "not found" for a write that succeeded.
- **A demo refresh may only delete rows the seed recorded creating.** The manifest
  lives in `tenants.settings` and `application/tenants/demo_data.py` owns it.
  Never delete by `tenant_id` alone - that destroyed a real founder prospect once.
  Unmarked means real; `capture.demo_data` is a display label and must never
  authorise a delete.
- **Anything destructive takes a local snapshot first and aborts if it fails.**
  `scripts/backup_local.py`, output in git-ignored `backups/`.
- **Browser tests run in the `sangam-e2e` tenant, never in `sangam`.** The
  founders' workspace is real working data now. Isolation is a tenant, not an
  `is_test` column and not a cleanup step - activities and source events are
  append-only and cannot be tidied away afterwards.
- **An import never modifies an existing prospect.** A matched row is recorded as
  a `LeadSourceEvent` with `outcome="duplicate"` pointing at what it matched. No
  automatic merging, ever.
- **Free text arriving from a spreadsheet goes through
  `shared/utils/spreadsheet.neutralise_formula`** on the way in, so a cell
  beginning `=` cannot execute in a later export.
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

**The workflow now measures itself.** Waiting-for-first-reply, time to first
reply, the tenant median, longest current wait, overdue follow-ups, unassigned
prospects and prospects with no next action all come from normal product use, are
computed server-side in the caller's scope, and each count links to the filtered
list of records behind it. `sangam-first-response.spec.ts` proves in a browser
that assignment, qualification, an internal task, an internal note and an
*inbound* call all leave a prospect waiting, that the first outbound contact
records the response, and that a second contact does not move the timestamp.

**The founders can now put real businesses in.** Quick add (business name plus one
contact route is the whole required form), CSV prospect import with a template,
column mapping, cleaned-up preview values, duplicate matching on phone and email,
per-row rejection reasons and a created / already-had / unusable summary. Outreach
made outside Sangam is recorded in one save, together with its outcome and the
next action. `sangam-founder-prospecting.spec.ts` proves that whole path in a
browser.

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
- Every seeded prospect carries `capture.demo_data = true` and is labelled
  **sample** in the list, so real entries are never confused with the invented
  ones.
- A second tenant, **`sangam-e2e`** (`owner@sangam-e2e.test`, `rep@sangam-e2e.test`,
  same password), exists only for the browser suites. It is seeded empty; each
  scenario creates exactly what it asserts on.

**The seed is additive and idempotent.** If the tenant already holds prospects it
rewrites nothing, because the founders are expected to use this workspace for
real prospecting. `--refresh` rebuilds the synthetic rows and is the only path
that deletes; it touches no other tenant. It cannot delete activities — the
append-only trigger forbids it — so refreshed runs leave orphaned activity rows
behind. Use `RESET_DEMO.cmd` for a genuinely empty slate.

## 8b. Data safety and backups

Local snapshots are written to `backups/` (git-ignored: they hold real prospect
data). They are taken automatically before a demo refresh and before a reset, and
**a failed snapshot stops the destructive operation**. Ten are kept.

To restore one:

```
docker compose exec -T postgres psql -U airevenueos -d airevenueos < backups/<file>.sql
```

`docker compose exec api python src/scripts/founder_data_report.py` counts genuine,
non-sample records. `RESET_DEMO.cmd` consults it and refuses `-Force` when any
exist. The non-destructive alternative is
`docker compose exec api python src/scripts/seed_sangam.py --refresh`.

`src/scripts/recover_lead.py` rebuilds a deleted lead from surviving append-only
evidence. It is disaster recovery, not a product feature.

## 9. How it runs

Double-click **`RUN_DEMO.cmd`**. Nothing else. If Docker Desktop is installed but
closed, the launcher starts it and waits; if it is not installed, it says so in
plain English with the download link rather than throwing. It then starts the
stack, waits for health, migrates, seeds reference data, seeds both demo tenants
and the Sangam workspace, proves a sign-in works, prints the credentials and
opens the browser. **Verified from a genuinely cold Docker on 2026-08-12**: the
volume kept its original creation date, both seeds reported the existing data
untouched, and every service reached healthy. `-NoBrowser` suppresses the last step for CI and for the
Playwright runs, which drive their own browser.

Two traps worth remembering before touching that script:

- `docker version` can **hang** rather than fail while Docker Desktop is starting,
  so every probe is bounded by `Test-DockerEngine -TimeoutMs`.
- The script runs under `$ErrorActionPreference = 'Stop'`, and Windows PowerShell
  turns a native command's stderr into a terminating error. Any new `docker ...`
  call that is allowed to fail needs the same treatment as `Test-DockerEngine`.

- App: http://localhost:3000 — API docs: http://localhost:8000/v1/docs
- Data lives in the `airevenueos_pgdata` volume and survives restarts.
- `RESET_DEMO.cmd` wipes it and makes you type "reset" first.
- Sign-in is rate limited to **5 attempts per IP per 15 minutes**. Keep this in
  mind before adding automated logins anywhere.

For a fixed password (needed by the browser tests):
`powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 -Password "..."`

## 10. Latest test evidence (2026-08-13)

| Gate | Result |
| --- | --- |
| Backend ruff + format | Clean, 223 files |
| Backend mypy (strict) | Clean, 223 source files |
| import-linter | 6 contracts kept, 0 broken |
| Backend unit + contract **in the container** | **872 passed, 6 skipped, 0 failed** |
| Repo-layout suites, checkout mounted | **62 passed** (the 6 skips above, run where their files exist) |
| Permission/RBAC subset | 41 passed |
| Web typecheck | Clean |
| Web lint | Clean, 0 warnings |
| Browser e2e (`sangam-first-slice`) | 1 passed — full business journey, 11 screenshots |
| Browser e2e (`sangam-first-response`) | 1 passed — 9 measurement assertions, 6 screenshots |
| Browser e2e (`sangam-founder-prospecting`) | 1 passed — import + duplicates + outreach, 7 screenshots |
| Browser e2e (`sangam-dogfood-repairs`) | 3 passed — reassignment, team scope, field-level validation, 7 screenshots |
| Browser e2e (`sangam-data-safety`) | **2 passed** — recovered prospect visible with its history, samples beside it |
| Demo-refresh safety (`test_demo_refresh_safety.py`) | **8 passed** — sample-only deletion proven against the real schema |
| Founder workspace isolation | Verified: `sangam` held 15 prospects before and after two full browser runs |
| Cold-start launcher | **Verified**: Docker closed → `RUN_DEMO.cmd` → app open in browser |

The container run is now clean. The 6 skips are whole modules that assert on files
outside `backend/` (terraform, workflows, alert rules, lock files); they name the
reason and they pass when run with the checkout mounted, which is how the 62 above
were confirmed. Nothing is hidden.

## 11. Visual evidence

`artifacts/visual-evidence/` — three session folders, regenerated by:

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
6. **Response measurement depends on the recording habit.** A call nobody logs
   leaves the prospect showing as waiting. Honest, but say it out loud to any
   pilot customer before they read the number as "our team ignored these people".

## 13. Next task

**Pending project-head review.** Session 4 repaired the two defects the founder
found by hand; it chose no new roadmap item.

Session 3 delivered what the founders need to start entering real prospects. The
next task is deliberately not chosen here; the project head decides it after
reviewing this state.

The earlier recommendation in this slot (weekly metric snapshots) was explicitly
overridden and should not be picked up without a fresh instruction.

Standing constraints for whatever comes next: no live WhatsApp, email, AI, voice,
payments, documents, broad analytics or deployment work without an explicit
decision, and none of them is required by the current commercial slice.

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
