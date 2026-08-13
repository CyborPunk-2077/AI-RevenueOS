# Sangam — project state

**Read this first.** It exists so a new session does not have to rediscover the
repository. Companion file: `docs/CURRENT-REALITY.md` (the feature-by-feature
reality map). Older documents in `docs/` predate 2026-08-12 and describe the
product under its previous name; where they disagree with this file or with the
running system, they are wrong.

Last updated: **2026-08-14** (session 5 final verification: one green baseline).

## Accepted checkpoints

Both are annotated tags on `master`; neither has been rewritten.

| Tag | Commit | What it is |
| --- | --- | --- |
| `sangam-baseline-session02` | `405e227` | First commercial slice with truthful first-response measurement |
| `sangam-founder-dogfood-session03` | `d293425` | The founders can enter real prospects: quick add, CSV import, duplicate matching, honest outreach recording, daily work queue |
| `sangam-safe-dogfood-session04` | `0974320` | **Current.** Session 4 + 4B: reassignment/auth scope and validation repairs, plus manifest-scoped demo refresh, mandatory local backup before anything destructive, and Claida recovered |

`master` is at the session-4 tag. Session 4 + 4B were integrated by fast-forward
from `sangam-dogfood-repairs`, so no history was rewritten and the two earlier
tags still point where they always did. Session branches are kept rather than
deleted, so `sangam-first-slice`, `sangam-founder-dogfood` and
`sangam-dogfood-repairs` still point at their work.

**Session 5 is on `sangam-pilot-whatsapp` and is not merged or tagged.** It is
verified and green (section 10) and waiting on project-head review. No existing
tag was touched.

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
- **A read that happens before a tenant is known needs its own policy, and
  `platform_session`.** An unscoped session is not "no filter", it is "match
  nothing": with `app.tenant_id` unbound the tenant policy is false for every row.
  Sign-in (`0004`), the Razorpay ingress (`0007`) and the two anonymous surfaces -
  a published form and an active chat widget (`0012`) - each get a **SELECT-only**
  policy gated on a deliberately bound, logged platform context, scoped as
  narrowly as the case allows. Reaching for `unscoped_session` instead does not
  fail loudly; it returns nothing, and the feature quietly reports that it does
  not exist. That is exactly how web chat and public forms sat broken.
- `app.activities` and the audit log are **append-only**, enforced by a database
  trigger. Do not disable the trigger — including for seed or test convenience.
- **What counts as answering a customer is defined once**, in
  `domain/leads/first_response.py`: a customer-reaching channel, plus a direction,
  plus an **outcome**. A missed call, a meeting still in the diary, an inbound
  message nobody answered and a send the provider rejected all leave the prospect
  waiting; an inbound call somebody picked up counts. Do not re-implement that
  test anywhere else. Every provider feeds
  `application/leads/first_response.record_first_response` rather than writing
  `first_response_at` directly - including WhatsApp, which asks the same function
  the timeline form does.
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
- **A workspace says what it is for**, in `tenants.settings.workspace_kind`:
  `founder`, `pilot`, `test` or `demo`. `application/tenants/provisioning.py` is
  the one place a workspace is created, for the seed and for a pilot alike - a
  second copy is how a workspace ends up with managers and no team. A `pilot`
  counts as real data everywhere it matters, so `RESET_DEMO` refuses while one
  exists.
- **A pilot workspace has no demo manifest**, so no refresh can delete anything in
  it. That is a property of how it was created, not a check somebody remembered
  to write.
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

## 8a. Pilot workspaces

A real SME running a shadow pilot gets **its own tenant**, created by
`src/scripts/provision_pilot.py`. Never a folder, a tag or a filtered view.

```
docker compose exec api python src/scripts/provision_pilot.py \
    --name "Sharma Motors" --slug sharma-motors \
    --owner owner@sharmamotors.in "Rakesh Sharma" \
    --manager manager@sharmamotors.in "Deepa Sharma" \
    --member sales@sharmamotors.in "Imran Khan"
```

- No sample prospects, ever. A pilot's starting baseline has to mean something.
- Owner/manager/salesperson get global/team/self scope, **and the team exists**
  with real memberships.
- Re-running never resets a real person's password; the demo seed's opposite
  behaviour is deliberate and does not apply here.
- Credentials are printed for the founder to hand over. Email is provider-gated
  and cannot deliver an invitation, and the script says so rather than implying
  one was sent.

A third workspace, **`sangam-pilot-e2e`**, is seeded for the session-5 browser
acceptance. It is stamped `test`, not `pilot`, because a `pilot` counts as real
data in the destructive guards and a workspace the tests write to must not make
every reset warning look like a false alarm.

**Starting baseline.** `application/leads/baseline.py`, captured once per
workspace from the same metrics the Today page reads, stored in
`tenants.settings`. It is a *before* picture and is never presented as an
improvement. Where there is not enough history for a truthful figure it says so
instead of printing a zero.

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
- Sign-in is rate limited to **5 attempts per IP per 15 minutes**, and rotating a
  session (`/auth/refresh`) to **10 per 60 seconds per IP**. Both are keyed on the
  caller's address, and every browser request reaches the API from the same
  place - the BFF container - so the whole suite shares one budget with whoever is
  using the app. The browser suites therefore **do not sign in at all**: see
  section 10. Keep both numbers in mind before adding an automated login or an
  automated refresh anywhere.
- **A normal start never rotates anybody's password.** `seed_sangam.py` creates
  credentials for accounts that do not exist and leaves existing ones alone.
  Rotation is `--reset-passwords`, asked for by name. This used to rewrite every
  seeded hash on every run, so starting the stack without `DEMO_PASSWORD` minted
  a random password and locked the founders out of their own workspace.

For a fixed password (needed by the browser tests):
`powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 -Password "..."`

## 10. Latest test evidence (2026-08-14)

**One green baseline, from a clean environment.** Nothing in the table below is
qualified, expected-to-fail or run one file at a time.

| Gate | Result |
| --- | --- |
| **Backend, complete suite** | **1408 passed, 18 skipped, 0 failed, 0 errors** (exit 0, 2m29s), from `docker compose run --rm tests` |
| The 18 skips | All of `test_worker_runtime.py`, which needs `redislite` as a real Celery broker and says so. The only expected skip family; nothing else in the suite skips |
| Backend ruff + format | Clean, 331 files |
| Backend mypy (strict) | Clean, 313 source files |
| import-linter | 6 contracts kept, 0 broken |
| Fresh-database migration chain | **Clean** — a brand-new database migrates `0001`→`0012` with no error, once per suite run |
| Test isolation from real credentials | **Enforced twice** — the `tests` service carries no `env_file`, and `tests/conftest.py` strips provider credentials and feature flags from the process |
| Test isolation from the real database | **Repaired.** Two files reached `admin_session()` without first starting the ephemeral server; run alone they used the real local database. Both now depend on `migrated_database` |
| WhatsApp provider contract | **29 passed** — signatures, replay, routing, isolation, no fabricated success |
| Web typecheck | Clean |
| Web lint | Clean, 0 warnings |
| Browser, all six suites in one command | **12 passed, 0 failed** — sessions 02, 03, 04, 04B, 05 and Inbox hardening |
| Browser sign-in attempts spent | **Zero.** Sessions are established once per machine and reused; the limiters are untouched |
| Founder workspace isolation | Verified: the audit log for `sangam` shows only `auth.login`, `auth.refresh` and `auth.session_revoked` — no writes |
| Founder data | 19 prospects intact, Claida's original `first_response_at` unchanged |
| Live WhatsApp history | 13 messages intact, including the truthful `queued` that never sent, the `sent`, three `read` and one genuine `failed`. No status rewritten |

**Any migration after `0001` must tolerate what the baseline already built.** The
baseline is built from live model metadata, so anything a later migration adds
that the models already declare will exist before that migration runs. `0010`
learned this the hard way; `0012` adds only policies, which metadata never
creates.

**What the previously-red tests actually were.** The last session left two
families red and called them pre-existing. Neither was what it looked like:

- The **20 errors** were the harness, not the tests: they read files above
  `backend/`, and nothing had ever mounted the checkout where a container could
  see it. It does now.
- The **23 failures** were seven distinct causes, and five of them were real
  product defects — a pre-tenant read that could never see its own row, a widget
  key pattern that rejected two thirds of the keys the product mints, and one
  each in merge, deduplication and disqualification. `docs/CURRENT-REALITY.md`
  has the full breakdown. Updating the expected values in bulk would have buried
  all five.

## 10b. How to run the checks

**Backend, everything, from a clean ephemeral environment:**

```
docker compose run --rm tests
```

A `test`-profile service. It differs from `api` in three ways that all exist to
stop a test run depending on, or disturbing, the machine it runs on:

- The **checkout is mounted read-only at `/repo`** and named in `REPO_ROOT`. The
  tests that assert on `docker-compose.yml`, the launcher, the reset script,
  Terraform and the workflows read files that live above `backend/`; inside a
  container that mounts only `backend/` they used to error on a path that could
  never exist. Read-only, because a test run must not edit what it is verifying.
- It has **its own Redis** (`redis-test`, no host port). The auth tests call
  `FLUSHALL` between cases - they have to, the limiter's state is what they are
  testing - and pointing them at the running stack's Redis would wipe its
  sessions and counters underneath whoever was using the app. `fakeredis` is not
  an option either: it cannot run the limiter's Lua script, so every limit
  assertion would pass for the wrong reason.
- It carries **no `env_file` and no `DATABASE_URL`**. The suite starts its own
  PostgreSQL per session, and the real Meta credentials in `.env.local` never
  enter the process. `tests/conftest.py` strips them as well; this is the outer
  half of the same guarantee.

**Browser suites**, all six in one command, which is new:

```
$env:DEMO_PASSWORD='sangam-demo-2026'
pnpm --filter @airevenueos/web exec playwright test sangam-first-response sangam-founder-prospecting sangam-dogfood-repairs sangam-data-safety sangam-pilot-readiness sangam-inbox-live
```

Named one by one rather than matched with `sangam-`, deliberately.
`sangam-first-slice.spec.ts` shares the prefix and is **not** one of the six: it
predates the tenant boundary and still creates its prospect in the founders' own
`sangam` workspace. Leave it out of routine runs. Moving it to `sangam-e2e` like
the others is a small job nobody has done yet.

**Static, type and architecture gates:**

```
docker compose run --rm tests sh -c "ruff check src tests && ruff format --check src tests && mypy && lint-imports"
pnpm --filter @airevenueos/web typecheck
pnpm --filter @airevenueos/web lint
```

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

## 12b. WhatsApp: what is now real

The adapter was always complete. What was missing was everything after it - a
verified inbound event was deduplicated, logged and dropped.

- Inbound messages route to a workspace by the **business number they arrived on**
  (`app.channels`, claimed with `src/scripts/claim_whatsapp_number.py`). An
  unclaimed number is refused, not guessed.
- The sender is matched to an existing prospect on the last ten digits, or a thin
  new prospect is created carrying the number and the WhatsApp profile name.
  Nothing else is invented.
- Everything lands in the canonical lead/conversation/activity/message tables.
  There is no WhatsApp copy of a customer.
- Idempotency is on the provider's message id **in the database**, not only in
  Redis, because Meta redelivers hours later.
- **An inbound message never counts as a reply.** It is recorded with outcome
  `received` and asked the same canonical question a phone call is asked.
- An outbound reply records what the provider decided: accepted counts, rejected
  does not, unconfigured queues honestly. Status callbacks only move a message
  forward through sent → delivered → read.
- The Test Centre shows `NOT_CONFIGURED` / `CONNECTED` / `ERROR`, and `CONNECTED`
  requires a live Graph API call that succeeded. **As of 2026-08-14 it reports
  `ERROR`**: credentials are present and Meta refused them, which is what an
  expired temporary access token looks like. That is the page doing its job, not
  a fault in Sangam - and it is why the pilot browser spec no longer asserts one
  particular state. It asserts that the state is one the system actually
  observed, and that this workspace has observed nothing of its own.

**The two-way path is proven.** A message from a real phone reached Sangam
through Meta, and a reply sent from the Sangam Inbox reached that phone, with
real provider ids and delivery/read reconciliation. The stored history - the
truthful `queued` record that never sent, the `sent`, the `read`, and one genuine
`failed` - is preserved and was not rewritten by any of this verification.

Getting back to `CONNECTED` **needs a human at Meta** - a fresh access token, and
the tunnel hostname still trusted. `docs/WHATSAPP-LIVE-TEST.md` has the exact
steps and the number policy (never convert a personal WhatsApp number).

## 13. Next task

**Pending project-head review before Session 05 merge/checkpoint.**

Session 5 made the product ready for one real SME shadow pilot, built the real
WhatsApp Cloud API path and proved it two-way against a real phone, and has now
been verified end to end from a clean environment with nothing red. No roadmap
item is chosen here; the project head decides it after reviewing this state.

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
