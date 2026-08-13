# Sangam — feature reality map

Last established: **2026-08-14** (session 5 final verification), against the
running local stack.

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
| Users and roles | VERIFIED-USABLE | Owner/manager/member with global/team/self scope. **Repaired in session 4:** roles and team membership are read with tenant context bound, so a manager is no longer silently issued a member's scope and a team-scoped user is no longer filtering on an empty set. Branches, a Sales team and memberships are seeded, and a new prospect inherits its creator's team. |
| Today (operational dashboard) | VERIFIED-USABLE | Counts waiting-for-reply, unassigned, no-next-action and overdue, **all computed server-side in the caller's scope** by `application/leads/metrics.py`. Every figure links to the filtered list that makes it up. Verified that closing a follow-up decrements the overdue count and that answering a prospect decrements the waiting count. |
| First-response measurement | VERIFIED-USABLE | `first_response_at` is set automatically, in the same transaction as the activity that justifies it. Idempotent by conditional UPDATE, never overwritten, never backfilled. **Rewritten in session 5** to take an *outcome* as well as a channel and direction: a missed call, a meeting still in the diary, an unanswered inbound message and a rejected send all leave the prospect waiting, while an inbound call somebody picked up counts. Records written before outcomes existed keep exactly their old meaning. 44 domain tests, plus browser acceptance for every case. |
| Response-time reporting | VERIFIED-USABLE | Per-prospect time to first reply, plus tenant median and longest current wait. Median, not mean. Derived only from logged contact, so it moves when behaviour moves and at no other time. |
| Prospects (leads) list | VERIFIED-USABLE | **Rebuilt this session** to show owner, next action, age and a "no reply yet" flag. |
| Prospect detail | VERIFIED-USABLE | **Rebuilt this session** into a workbench: requirement, ownership, qualification, follow-ups, history, duplicates. |
| Assignment | VERIFIED-USABLE | Manual assignment to a named person, with optimistic-concurrency check. **Repaired in session 4:** reassigning a prospect away from yourself used to report "Lead not found" while saving anyway. Browser-proven for an owner and for a team-scoped colleague, including that a stale version is still refused with 412. Rule-based auto-assignment exists but is not exercised. |
| Qualification | VERIFIED-USABLE | Rule-based scoring with visible reasons and missing fields, working with **no AI provider**. Manual override present. |
| Follow-ups / tasks | VERIFIED-USABLE | **New queue screen this session** with all/overdue/mine filters and inline completion. Overdue is decided server-side. Tasks can now hang off a lead, not only contacts and deals. |
| Activity history | VERIFIED-USABLE | Extended to leads, so history predates conversion instead of restarting at it. Activities are append-only, enforced by a database trigger. **Now carries a direction** ("we contacted them" / "they contacted us"), shown in the timeline, because only outbound contact answers an enquiry. |
| Notes | VERIFIED-USABLE | Editable by their author only, enforced server-side. |
| Contacts and accounts | VERIFIED-USABLE | Pre-existing; list, search, create, edit, timeline. |
| Deals and pipeline | VERIFIED-USABLE | Board by stage, stage moves, won/lost with loss reason. Seeded and viewed this session; stage-move interaction not re-exercised. |
| Duplicate detection | VERIFIED-USABLE (detection) / BACKEND-ONLY (merge) | Candidates are detected on import and on demand, surfaced with the evidence, and left for a human. The panel identifies the counterpart by business name, person, phone or email. **Three defects fixed in the final verification**, all found by tests that had been red long enough to be assumed stale: re-running a deduplication inserted the same candidate twice (the guard compared a string against a set of UUIDs, so it matched nothing); merging tried to re-point append-only source events and could therefore never commit; and disqualifying a lead was refused as though no reason had been given, because the reason never reached the state machine. All three now work and are covered. There is still no merge screen. |

## Everything else

| Module | Status | Notes |
| --- | --- | --- |
| Onboarding / tenant creation | PARTIAL | An onboarding route group exists. Not exercised; tenants are created by seed today. |
| Team invitations | PARTIAL | Full backend (migration 0011, 28 tests) and an accept screen. The invitation email cannot be delivered — see email below — so in practice the link must be passed by hand. |
| Test Centre | VERIFIED-USABLE | **New this session.** Development-only; the route refuses to render in a production build. Provider rows are probed live. |
| Analytics / reporting | PARTIAL | Charts render with table equivalents and skeletons. **The numbers have not been reconciled against the underlying records.** Do not quote them. Export is deliberately disabled. |
| Unified inbox | PARTIAL | The screen and conversation model are real, but with no channel able to send it is a record of nothing. |
| WhatsApp | PARTIAL / PROVIDER-GATED | **Completed in session 5, up to the human gate.** A verified webhook now becomes a customer record: tenant routing by business number, phone matching, safe prospect creation, conversation, activity, message, database-level idempotency, outbound reply through the real Cloud API, provider message ids and delivery/read reconciliation. All of it feeds the canonical first-response rule, and an inbound message correctly does *not* count as a reply. 23 provider-contract tests pass without credentials. **Not yet exercised against Meta**: needs a human to log in, accept terms, pass 2FA and claim a test number, plus a temporary HTTPS tunnel. `docs/WHATSAPP-LIVE-TEST.md`. |
| Pilot workspace provisioning | VERIFIED-USABLE (backend) | `src/scripts/provision_pilot.py` creates a real SME's own tenant with owner/manager/salesperson, a branch, a team and real memberships, and no sample data. 14 integration tests cover roles, scopes, team membership, idempotency and the fact that no refresh can reach a pilot's rows. No screen yet; the founder runs one command. |
| Starting baseline | VERIFIED-USABLE | Captured once per workspace on Today, from the same metrics the dashboard shows, stored on the tenant. Shows "at the start" beside "now" with no arrows, no percentages and no characterisation of the difference. Says so in words when there is not enough history for a figure. |
| Workspace identity | VERIFIED-USABLE | The header names the company and what the workspace is for — ours, a pilot's, or the browser-test one. Driven by `workspace_kind` on the tenant, not by a list of slugs. |
| Email | PROVIDER-GATED | Needs a provider with a verified sending domain. |
| SMS | PROVIDER-GATED | Needs Indian DLT registration. |
| Voice | PROVIDER-GATED | Also needs legal sign-off on call-recording consent. |
| Web chat | PARTIAL | Full stack implemented (commit 5ebd36f) with a visitor e2e spec. **The public path could not work at all until the final verification, for two independent reasons.** Resolving a widget by its public key is necessarily a pre-tenant read; it used an unscoped session, and under forced row-level security an unscoped session matches nothing - so every visitor was told the widget was unavailable, including from its own site. Underneath that, the key pattern guarding the lookup allowed only letters and digits while keys are minted from the URL-safe base64 alphabet, so about two in three were rejected as malformed regardless. That second one is why these tests looked flaky rather than broken: whether they passed was the luck of the draw. Migration `0012` adds a SELECT-only policy for **active widgets under a deliberately bound, logged platform context**, the same shape as the sign-in lookup in `0004`; the pattern now accepts what the generator produces, with a unit test pinning that the two halves agree. Still not exercised in a browser. |
| Appointments | PARTIAL | Bookings can be recorded and rescheduled. Calendar sync is PROVIDER-GATED on Google OAuth verification and reports itself as inactive. |
| Documents and files | PROVIDER-GATED | Metadata is recorded; no upload URL is issued because there is no object storage. The API reports this honestly and the UI disables the control with the real reason. |
| Payments | PROVIDER-GATED | Razorpay adapter exists. Needs a commercial agreement and KYC. |
| Workflows / automations | BACKEND-ONLY | Engine, schedules and outbox all run. No builder screen, no logs screen. |
| Forms and capture | PARTIAL | Builder and publish-snapshot exist with a publish permission. Publishing puts an unauthenticated write surface on the internet, so it is treated as a sensitive permission. **Same defect as web chat, same fix**: fetching a published form is a pre-tenant read and returned "form not found" for every form ever published. `0012` exposes **published forms only**, under a logged platform context. Not exercised in a browser. |
| CSV prospect import | VERIFIED-USABLE | **Proven in a browser this session.** Upload, column mapping, cleaned-up preview values, duplicate matching against existing records, per-row rejection reasons, and a created/already-had/unusable summary. CSV only; nothing claims XLSX. The template download uses the founders' own column names. |
| Quick prospect capture | VERIFIED-USABLE | Business name plus one contact route is the whole required form; contact person, area, industry, website, source, pain and owner sit behind "More details". A business with no named contact is a first-class record. **Repaired in session 4:** invalid phone, email or amount now produce a specific message on the offending field, keyed off the API's structured faults, with the typed values kept. |
| Import duplicate matching | VERIFIED-USABLE | Matches on email *and* phone (last ten digits, so `+91 98450 12201` and `09845012201` are the same number). The existing record is never touched; the incoming row is kept as a source event pointing at what it matched. Nothing is merged automatically. |
| Recording outreach made outside Sangam | VERIFIED-USABLE | Channel, direction, outcome, note and the next action with a due date, in one save. Feeds the session-2 first-response measurement unchanged. Sangam sends nothing and says so on the form. |
| AI / copilot | PROVIDER-GATED | Gateway, prompt registry, evals and degradation paths exist. No model provider is configured. Every AI-touching path has a rule-based fallback; qualification proves it. |
| Notifications | BACKEND-ONLY | Events flow through the outbox. No in-product notification surface. |
| Audit and consent | VERIFIED-USABLE (backend) | Every mutation writes an immutable audit row in the same transaction. Tenant-scoped. No screen to read it. |
| Integrations | PARTIAL | A settings screen lists integrations and their real state. |
| Plan / feature entitlement | SPEC-ONLY | Plans and feature flags are seeded as reference data. Nothing gates a module by plan yet. This is the mechanism the commercial strategy depends on and it does not exist. |
| Deployment | SPEC-ONLY | Terraform for four environments, statically validated only. No AWS account. Nothing has ever been deployed. |

---

## Session 5 — what "answered" actually means, and a workspace for a real business

**The first-response rule was too simple, and the founders had already noticed.**
The outreach form offered "No answer" as an outcome, pasted it onto the subject
line, and then marked the prospect as answered anyway — because the rule only
looked at channel and direction. A team could ring twenty people, reach nobody,
and show a clean dashboard.

The rule now takes an outcome as well, and it is still the only place the question
is decided:

| What happened | Counts as answering them? |
| --- | --- |
| Outbound call, they spoke | Yes |
| Outbound call, no answer | **No** |
| Inbound call, somebody picked up | **Yes** — answering the phone is engagement |
| Inbound call, missed | No |
| Inbound message received | No — that is the enquiry |
| Message the provider accepted | Yes |
| Message the provider rejected | **No** |
| Meeting that took place | Yes |
| Meeting booked for later | **No** |
| Task, note, assignment, qualification | No |

An activity with no outcome behaves exactly as it did in session 2, so nothing
already recorded changed meaning.

**A pilot business gets its own tenant**, provisioned by the same code the seed
uses — because a second copy of that logic is how session 4 shipped a manager with
no team. It holds no sample data and no demo manifest, which is what puts every
row in it permanently beyond the reach of a refresh.

**The starting baseline** is captured once, from the same metrics the Today page
reads. It is presented as a "before" picture and never as an improvement, and it
reports missing history in words rather than as a zero.

**Two defects found while building this**, both real and both in accepted code:

1. **`Card` silently dropped `data-testid`.** JSX does not type-check hyphenated
   attributes on a component, so the element rendered, the marker vanished, and
   nothing anywhere said why. Any test written against a `Card` would have failed
   for reasons that looked like an application bug. Now forwarded explicitly.
2. **Provisioning did not flush.** Team memberships existed only in Python until
   something else happened to flush the session, so a caller reading the workspace
   back saw a manager with no team — the exact session-4 defect, reintroduced by
   the fix for it. Caught by the integration test, not by a person.

## Session 4B — a demo refresh destroyed real founder data

**What happened.** `seed_sangam.py --refresh` rebuilt the sample workspace with
`DELETE FROM app.<table> WHERE tenant_id = :t` - every row in the tenant, on the
assumption that a demo workspace holds only demo data. Once the founders began
prospecting for real in that same workspace the assumption was false. During
session 4 the refresh ran twice and destroyed **Claida (Oxon)**, a genuine
prospect the founders had created and worked, along with its notes and tasks.

**What was lost, and what survived.** The lead row, one note and three tasks were
deleted. The append-only tables saved the rest: the `lead_source_event` written at
capture (holding the full payload - name, business, email, phone, area, industry,
requirement, value, owner), the `lead.create` audit entry, two outbound calls
logged by Kiran, and audit rows naming each task.

**What was recovered.** The prospect is back under its original id, so the two
surviving activities reattached rather than being copied. Three tasks were rebuilt
from titles the audit preserved. **One note was not**: the audit proves it existed
but never stored its text, and inventing a plausible sentence would have been
worse than the gap. Founder interactions on two *sample* prospects are also
orphaned; those records are disposable and were not rebuilt.

**How it cannot happen again.**
- The seed now records every row it creates in a manifest held in
  `tenants.settings`, and a refresh deletes **only** those ids. A record the seed
  did not create is not a candidate for deletion - real data survives by
  construction, not by being correctly recognised.
- Unmarked or ambiguous rows are preserved by default, because absence from the
  manifest is the default state.
- `capture.demo_data` remains, but only as the display marker that draws the
  "sample" pill. It no longer authorises any delete.
- Every destructive path takes a local `pg_dump` snapshot first, and **refuses to
  continue if the snapshot fails**. Snapshots live in git-ignored `backups/`.
- `RESET_DEMO.cmd` now counts genuine records first. If any exist it refuses
  `-Force` outright and demands a different typed phrase, having pointed at the
  non-destructive refresh instead.
- Eight regression tests in `tests/integration/test_demo_refresh_safety.py` pin
  each of those guarantees, including that a manifest naming another tenant's row
  still cannot reach it.

## Defects found and fixed in session 4 (found by the founder, by hand)

These were not found by a test. The founder used the accepted session-3 build for
real and hit them within minutes, which is the whole argument for dogfooding.

1. **Reassigning a prospect said "Lead not found" while saving the change
   anyway.** Two independent causes, both real:
   - *Roles and team membership were read under a platform-scoped session*, where
     row-level security hides `roles`, `user_roles`, `teams` and `team_members`.
     The role lookup silently fell back to "member", quietly demoting every
     manager and admin to self scope, and the team lookup returned nothing, so a
     team-scoped principal filtered on an empty set and matched no record at all.
     Both now resolve inside `tenant_session`, in `load_roles_and_scope`.
   - *`LeadService.update` re-read the record under the caller's scope after
     mutating it.* Reassigning a prospect away from yourself moved it out of your
     own scope, so the re-read raised "Lead not found" for a write that had
     already committed. It now returns the committed state from inside the
     transaction.
   The scope check itself was never wrong and has not been relaxed; it was being
   asked to filter on identifiers nobody had supplied.
2. **A prospect created in the UI carried no team**, so a team-scoped manager
   could not see even the records they had just added themselves. A new prospect
   now inherits its creator's team and branch when they belong to exactly one.
3. **The seeded workspace was internally inconsistent**: managers had `team` scope
   and no team existed. The seed now creates a branch, a Sales team, memberships
   and stamps seeded prospects with the team.
4. **Invalid input showed "The request payload failed validation".** The API had
   been returning a structured per-field list all along and the form ignored it.
   Faults are now mapped to the field they belong to, in the founders' language,
   with `aria-invalid` and `aria-describedby` so the message reaches a screen
   reader and does not depend on the red outline. Entered values are preserved.
   Server-side validation is unchanged and remains the authority; the one
   client-only rule (the rough value) is client-only because the server stores
   that field as free-form captured text and has no opinion on it.

## Defects found and fixed in session 3 (founder dogfooding)

1. **Import could never have worked from the browser.** The upload posted without
   a CSRF token, so every preview returned "CSRF validation failed". This is why
   the feature had backend tests and no trustworthy end-to-end story. `mutate()`
   now carries the token and passes `FormData` through untouched, letting the
   browser set the multipart boundary.
2. **Import matched duplicates on email only**, so the same business imported from
   two lists with the same phone and no address was created twice. Phone matching
   was the difference between catching it and quietly building twins.
3. **`--refresh` could not run once the tenant had imports.** It deleted
   `lead_source_events`, which is append-only; it had only ever appeared to work
   because the table was empty. Removed from the delete list, same as activities.
4. **Browser tests were filling the founders' workspace.** Ten invented businesses
   had already accumulated there. Both suites now run in a dedicated `sangam-e2e`
   tenant, which is the boundary tenancy already enforces.
5. **A prospecting list could not be imported at all** if it had no named contact,
   because `first_name` was required. A list of businesses to approach usually has
   the shop and a number and nothing else.

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

- ~~The whole backend suite cannot be run in one command.~~ **Fixed, and then
  finished.** Migration `0010` now checks whether the constraint exists before
  adding it, because `0001` builds the baseline from live model metadata and
  therefore already creates anything the models declare. The two families that
  remained after that are gone as well:

  - The **20 errors** in modules that read `/docker-compose.yml` were a harness
    problem, not a test problem. `docker compose run --rm tests` mounts the
    checkout read-only at `/repo` and names it in `REPO_ROOT`, so those tests run
    where they always should have. Nothing is skipped to get there.
  - The **23 assertion failures** were seven distinct causes, and most of them
    were the product, not the tests. Taken one at a time:

    | Tests | What it really was | Which way it was fixed |
    | --- | --- | --- |
    | 12 | Web chat and public forms cannot read their own row before a tenant is bound | Product: migration `0012` |
    | (same 10) | **And a second defect underneath it**: a widget's public key is generated from the URL-safe base64 alphabet and validated against a pattern that allowed only letters and digits, so roughly two keys in three were rejected as malformed before the lookup even ran | Product: `webchat.py`, plus the unit assertion that would have caught it |
    | 4 | Merge, deduplication and disqualification each genuinely broken | Product: `lifecycle_ops.py` |
    | 3 | The test asked for "today" in UTC; the product buckets by Asia/Kolkata, so these passed or failed on the time of day the suite ran | Test |
    | 1 | Analytics really had grown a `pipeline_by_stage` section | Test |
    | 1 | "No candidate from another tenant" asserted as "no candidates at all", which stopped being true as the file accumulated same-named fixtures | Test, narrowed to what it claims |
    | 2 | `TRUSTED_HOSTS` is now `${TRUSTED_HOSTS:-...}` so a tunnel host can be added without editing a tracked file; split on commas that reads as a hostname called `${TRUSTED_HOSTS:-localhost` | Test, resolves the Compose default |

    Blanket-updating the expected values would have hidden **five real defects**:
    the pre-tenant read, the key pattern, and one each in merge, deduplication and
    disqualification.

- **The whole browser suite can now be run in one command.** ~~Sign-in is rate
  limited to 5 attempts per IP per 15 minutes and the specs collectively need more
  than that.~~ They no longer sign in at all: `e2e/support/global-setup.ts`
  establishes one session per account, stores it in the git-ignored
  `apps/web/e2e/.auth/`, and every spec adopts it. A second limiter matters just as
  much and is easier to miss - `/auth/refresh` allows **10 per 60 seconds per IP** -
  so a stored session is used as it is while its access token is fresh and renewed
  only when it is not. Neither limiter was changed.

- ~~The duplicate panel shows "Unknown record".~~ **Fixed this session.** The
  candidate payload now carries the business name and the panel falls back
  business → person → phone → email. A genuinely missing counterpart now says so
  instead of pretending to be an unknown record.
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
- **Two test files wrote into the founders' own database, and passed while doing
  it.** `admin_session()` reads `ALEMBIC_DATABASE_URL` from the environment.
  Neither `test_whatsapp_provider_contract.py` nor `test_demo_refresh_safety.py`
  depended on the fixture that starts the session's ephemeral PostgreSQL and
  repoints that variable, so running either **on its own** in the API container
  found the compose value instead - the real local database. The WhatsApp file
  provisioned `wa-contract-a` and `wa-contract-b` into it on 2026-08-13, and the
  demo-refresh file, whose whole subject is deletion, was one import away from
  exercising it there. Both now depend on `migrated_database`. Nothing was lost -
  both invent their own tenants and touch only those - and the whole point is that
  they passed either way, which is why nothing noticed. The two stray tenants are
  still in the local database, empty and isolated; they are left alone rather than
  deleted, because nothing in this session may run a destructive operation against
  real data.

- **`sangam-first-slice.spec.ts` still writes to the founders' workspace.** Every
  other browser suite moved to the `sangam-e2e` tenant in session 3; this one
  predates that and was missed. It is excluded from the documented six-suite run
  rather than quietly included, and moving it is a small job nobody has done.
- ~~19 backend tests fail inside the API container only.~~ **Resolved.** Two
  different causes were hiding behind one symptom. The prompt tests were a real
  path bug in production code, now fixed and mounted. The rest assert on files
  that genuinely live outside `backend/` (Terraform, workflows, alert rules, lock
  files); they now locate the checkout by marker file and **skip with a reason**
  when it is absent, instead of failing. Nothing was weakened — running pytest
  from the repository root on the host still executes every one of them.
  **Confirmed 2026-08-12:** the container run is 862 passed / 6 skipped / 0
  failed, and those same 6 modules give 62 passed when run with the checkout
  mounted.
