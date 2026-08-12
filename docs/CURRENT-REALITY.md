# Sangam — feature reality map

Last established: **2026-08-12** (second session), against the running local
stack at commit `cc5e9aa` plus this session's work.

This file records what is *actually true when the product is running*, not what
the specification intends. Where something was checked in a browser this session
it says so; where the classification comes from reading code, it says that too.
Prior completion claims elsewhere in `docs/` predate this and were not taken on
trust.

## Classifications

| Label | Means |
| --- | --- |
| **VERIFIED-USABLE** | Real UI + real backend, exercised this session and evidenced |
| **BACKEND-ONLY** | Backend works; no owner-facing screen |
| **PARTIAL** | Works, but the workflow has a real gap |
| **PROVIDER-GATED** | Implemented; needs an external account nobody has opened |
| **BROKEN** | Intended path exists and currently fails |
| **SPEC-ONLY** | Schema/scaffold only, no usable workflow |

---

## The first commercial slice

| Module | Status | Notes |
| --- | --- | --- |
| Authentication | VERIFIED-USABLE | Sign-in, sign-out, session cookie, rate limiting. Browser-verified. MFA and Google sign-in exist but are untested this session (Google is PROVIDER-GATED). |
| Tenant isolation | VERIFIED-USABLE | Three enforcement layers including forced Postgres RLS. Covered by existing e2e tests. |
| Users and roles | VERIFIED-USABLE | Owner/manager/member with global/team/self scope, seeded and signed in as. `GET /users/members` added this session to feed assignee pickers. |
| Today (operational dashboard) | VERIFIED-USABLE | Counts waiting-for-reply, unassigned, no-next-action and overdue, **all computed server-side in the caller's scope** by `application/leads/metrics.py`. Every figure links to the filtered list that makes it up. Verified that closing a follow-up decrements the overdue count and that answering a prospect decrements the waiting count. |
| First-response measurement | VERIFIED-USABLE | **New this session.** `first_response_at` is set automatically, in the same transaction as the activity that justifies it, the first time an *outbound* contact on a customer-reaching channel is logged against a lead. Idempotent by conditional UPDATE, never overwritten, never backfilled. Rule lives in `domain/leads/first_response.py` so real provider events can feed it unchanged. Nine-assertion browser acceptance test. |
| Response-time reporting | VERIFIED-USABLE | Per-prospect time to first reply, plus tenant median and longest current wait. Median, not mean. Derived only from logged contact, so it moves when behaviour moves and at no other time. |
| Prospects (leads) list | VERIFIED-USABLE | **Rebuilt this session** to show owner, next action, age and a "no reply yet" flag. |
| Prospect detail | VERIFIED-USABLE | **Rebuilt this session** into a workbench: requirement, ownership, qualification, follow-ups, history, duplicates. |
| Assignment | VERIFIED-USABLE | Manual assignment to a named person, with optimistic-concurrency check. Rule-based auto-assignment exists at `/leads/{id}/assign` and in a settings screen — not exercised this session. |
| Qualification | VERIFIED-USABLE | Rule-based scoring with visible reasons and missing fields, working with **no AI provider**. Manual override present. |
| Follow-ups / tasks | VERIFIED-USABLE | **New queue screen this session** with all/overdue/mine filters and inline completion. Overdue is decided server-side. Tasks can now hang off a lead, not only contacts and deals. |
| Activity history | VERIFIED-USABLE | Extended to leads, so history predates conversion instead of restarting at it. Activities are append-only, enforced by a database trigger. **Now carries a direction** ("we contacted them" / "they contacted us"), shown in the timeline, because only outbound contact answers an enquiry. |
| Notes | VERIFIED-USABLE | Editable by their author only, enforced server-side. |
| Contacts and accounts | VERIFIED-USABLE | Pre-existing; list, search, create, edit, timeline. |
| Deals and pipeline | VERIFIED-USABLE | Board by stage, stage moves, won/lost with loss reason. Seeded and viewed this session; stage-move interaction not re-exercised. |
| Duplicate detection | PARTIAL | Candidates are detected, surfaced with reason and confidence, and left for a human. The merge path exists in the API but was not exercised, and the candidate panel renders a poor summary ("Unknown record") when the duplicate has no email. |

## Everything else

| Module | Status | Notes |
| --- | --- | --- |
| Onboarding / tenant creation | PARTIAL | An onboarding route group exists. Not exercised; tenants are created by seed today. |
| Team invitations | PARTIAL | Full backend (migration 0011, 28 tests) and an accept screen. The invitation email cannot be delivered — see email below — so in practice the link must be passed by hand. |
| Test Centre | VERIFIED-USABLE | **New this session.** Development-only; the route refuses to render in a production build. Provider rows are probed live. |
| Analytics / reporting | PARTIAL | Charts render with table equivalents and skeletons. **The numbers have not been reconciled against the underlying records.** Do not quote them. Export is deliberately disabled. |
| Unified inbox | PARTIAL | The screen and conversation model are real, but with no channel able to send it is a record of nothing. |
| WhatsApp | PROVIDER-GATED | Adapter, signature verification, retry and reconciliation all exist. Needs a Meta WhatsApp Business account and template approval. Reports "not configured"; never fabricates a send. |
| Email | PROVIDER-GATED | Needs a provider with a verified sending domain. |
| SMS | PROVIDER-GATED | Needs Indian DLT registration. |
| Voice | PROVIDER-GATED | Also needs legal sign-off on call-recording consent. |
| Web chat | PARTIAL | Full stack implemented (commit 5ebd36f) with a visitor e2e spec. Not exercised this session. |
| Appointments | PARTIAL | Bookings can be recorded and rescheduled. Calendar sync is PROVIDER-GATED on Google OAuth verification and reports itself as inactive. |
| Documents and files | PROVIDER-GATED | Metadata is recorded; no upload URL is issued because there is no object storage. The API reports this honestly and the UI disables the control with the real reason. |
| Payments | PROVIDER-GATED | Razorpay adapter exists. Needs a commercial agreement and KYC. |
| Workflows / automations | BACKEND-ONLY | Engine, schedules and outbox all run. No builder screen, no logs screen. |
| Forms and capture | PARTIAL | Builder and publish-snapshot exist with a publish permission. Publishing puts an unauthenticated write surface on the internet, so it is treated as a sensitive permission. Not exercised this session. |
| CSV import | PARTIAL | Wizard exists with an e2e spec. Never run against real customer data — treat as untested. |
| AI / copilot | PROVIDER-GATED | Gateway, prompt registry, evals and degradation paths exist. No model provider is configured. Every AI-touching path has a rule-based fallback; qualification proves it. |
| Notifications | BACKEND-ONLY | Events flow through the outbox. No in-product notification surface. |
| Audit and consent | VERIFIED-USABLE (backend) | Every mutation writes an immutable audit row in the same transaction. Tenant-scoped. No screen to read it. |
| Integrations | PARTIAL | A settings screen lists integrations and their real state. |
| Plan / feature entitlement | SPEC-ONLY | Plans and feature flags are seeded as reference data. Nothing gates a module by plan yet. This is the mechanism the commercial strategy depends on and it does not exist. |
| Deployment | SPEC-ONLY | Terraform for four environments, statically validated only. No AWS account. Nothing has ever been deployed. |

---

## Defects found and fixed in session 2 (measurement)

1. **`first_response_at` was seed-only.** Nothing in normal use ever set it, so
   the headline leakage metric would have been permanently wrong the moment a
   founder used Sangam for real prospecting. Now written automatically from logged
   outbound contact.
2. **The AI prompt registry could not find its prompts inside the container.**
   `PROMPT_ROOT` was inferred by counting four directories up from the module,
   which lands on `/` when only `backend/` is mounted. A genuine runtime path bug
   that had been showing up as two "failing tests". Fixed with an explicit
   `PROMPT_ROOT` environment variable and a read-only `./prompts:/prompts` mount.
3. **The launcher could hang forever on a half-started Docker.** `docker version`
   does not always fail fast — while Docker Desktop is coming up the named pipe
   can exist without answering, and the CLI blocks indefinitely. The probe is now
   bounded and the wait loop is visible. (Found by actually killing Docker and
   running the launcher cold.)
4. **`$ErrorActionPreference = 'Stop'` turned the Docker check into a crash.**
   Windows PowerShell wraps a native command's stderr in an ErrorRecord, so
   `docker version 2>$null` *terminated* the launcher on the very line whose job
   was to detect that Docker was down.
5. **Seeded first-response times had no evidence behind them.** The seed set the
   timestamp without writing the call that justified it. It now writes the
   outbound activity at exactly that moment, so every demo figure reconciles to a
   record the owner can open.

## Defects found and fixed in session 1 (workflow)

1. **Only the Owner could record that a call happened.** `activity:create` was
   withheld from admin, manager and member, so the salespeople who make the calls
   could not log them. Activities are append-only at the database level, so
   granting create cannot rewrite history. Fixed in `domain/auth/permissions.py`.
2. **Adding a follow-up appeared to do nothing.** The handler read
   `event.currentTarget` after an `await`; React nulls it by then, so the
   resulting TypeError swallowed the refresh. The task saved and the screen still
   said "No follow-ups yet". Fixed in `task-panel.tsx` and `timeline.tsx`.
3. **The same date rendered two different days.** Server components formatted in
   the container's UTC and client components in the browser's IST, so a follow-up
   due late evening showed as two different dates on two screens. All formatting
   now goes through `lib/dates.ts`, pinned to Asia/Kolkata.
4. **The navigation bar overlapped the wordmark** at laptop width once there were
   eleven sections. Rebuilt as a two-row header with a scrolling tab strip.
5. **The launcher would have locked the owner out.** Verifying three sign-ins
   consumed three of the five attempts the IP rate limiter allows per fifteen
   minutes. It now verifies one.

## Known defects not fixed

- The duplicate panel shows "Unknown record — no contact details" when the
  candidate has no email, which is exactly the case the seeded duplicate
  demonstrates. It should fall back to the phone number and captured company.
- Analytics figures are unreconciled (above).
- **Sangam measures what is recorded, not what happened.** A call that nobody logs
  leaves the prospect showing as waiting. This is the honest behaviour — the
  alternative is guessing — but it makes the metric a measure of the recording
  habit as much as of the responding habit. Worth saying out loud to any pilot
  customer.
- **`crm-contacts.spec.ts` "create an account, create a contact against it, edit
  and persist" fails** at `getByLabel('Job title').nth(1)` — the contact detail
  page no longer renders a second field with that label. **Confirmed
  pre-existing**: it fails identically with this session's web source stashed and
  the image rebuilt from the previous commit, so it is a regression from the UI
  primitive migration in `dd7c8e8`, not from this work. The other two tests in
  that file pass.
- **The browser suite cannot be run in one command.** Sign-in is rate limited to
  5 attempts per IP per 15 minutes and the specs collectively need more than
  that, so a full run produces spurious `waitForURL` timeouts. Run one spec file
  at a time. The clean fix is a per-worker storage-state fixture that signs in
  once and reuses the cookie.
- ~~19 backend tests fail inside the API container only.~~ **Resolved.** Two
  different causes were hiding behind one symptom. The prompt tests were a real
  path bug in production code, now fixed and mounted. The rest assert on files
  that genuinely live outside `backend/` (Terraform, workflows, alert rules, lock
  files); they now locate the checkout by marker file and **skip with a reason**
  when it is absent, instead of failing. Nothing was weakened — running pytest
  from the repository root on the host still executes every one of them.
