# Finish plan

Ordered, each step independently shippable and verifiable. Copy the prompt under
a step to run it.

Two rules that make the difference between this working and drifting:

- **One step per session.** Each ends with a green `validate.ps1` and a commit.
  Batching two steps means a failure in the second obscures the first.
- **Paste the failure output.** Nothing here is verifiable without running it, so
  a step is not done until the gate says so.

---

## Where the product actually stands

| Area | State |
|---|---|
| Backend modules M01–M24 | Implemented, 1,100+ tests |
| API surface | 110 endpoints |
| P0 blockers | P0-1…P0-4 resolved; P0-5 (AWS) and P0-6 (legal) external |
| Design tokens, fonts, primitives | Built and gate-verified |
| Form builder UI | Built |
| CSV import UI | Built, asserted at 1648/352 by the Playwright spec |
| Assignment rules UI | Built |
| Dedupe / merge UI | Built |
| Component migration to primitives | All eight modules migrated |
| External channel activation | Blocked on credentials |

Steps 1 through 7, 9 and 10 are done. What remains is step 8 (measurement under
real volume, which needs the app running) and the externally gated items at the
bottom of this file, which no amount of code closes.

---

## Step 1 — Verify and commit the current working tree

Nine files are uncommitted, including the whole design-token change. Nothing
below is safe until this is green.

```
Run validate.ps1. Fix any ruff, mypy, eslint or tsc failures in the files I
changed most recently: apps/web/src/app/globals.css, tailwind.config.ts,
app/layout.tsx, features/ui/primitives.tsx, features/ui/theme-toggle.tsx,
features/webchat/widget-settings-form.tsx, and the settings/webchat page.

Then run: pnpm --filter @airevenueos/web build-storybook
and confirm the Design System > Primitives stories render.

Report the output. Once green, commit as:
"UI: design tokens, Inter/Outfit, and shared primitives"
```

## Step 2 — Mount the theme toggle without a flash

The `.dark` class is defined and the toggle exists, but nothing sets the class
before first paint, so a dark-mode user sees a white flash on every load.

```
In apps/web/src/app/layout.tsx add a blocking inline script in <head> that reads
localStorage 'airev-theme' (falling back to prefers-color-scheme) and sets the
'dark' class on <html> before paint. Mount ThemeToggle in the WorkspaceShell
header. Add a settings sub-nav linking Integrations, Team and Web chat, since
Settings currently points only at Integrations.

Verify with pnpm typecheck and pnpm lint, then commit.
```

## Step 3 — CSV import wizard (highest-value missing screen)

Backend is done: `/v1/imports/leads/preview` and `/v1/imports/leads`. The preview
returns headers, a suggested mapping, accepted/rejected counts and per-row
rejection reasons. The fixture `backend/tests/fixtures/leads_messy_2000.csv`
exercises every rejection path.

```
Build the CSV import UI at (dashboard)/[tenantSlug]/imports using the existing
API. Three steps in one page: drop a file, confirm the column mapping the server
suggested, then review the preview before committing.

The review step must show accepted and rejected counts and the per-row rejection
reasons - that is the whole point of the preview and it must not be hidden behind
a summary. Generate the import_key client-side so a double-click cannot import
twice. Use the primitives in features/ui.

Test it against backend/tests/fixtures/leads_messy_2000.csv: 1648 rows should be
accepted and 352 rejected. Add stories for the empty, mapping, preview and
result states. Verify and commit.
```

## Step 4 — Form builder UI

```
Build the capture form builder at (dashboard)/[tenantSlug]/forms against the
existing /v1/forms endpoints. List, create, edit the draft, publish, unpublish,
archive.

The draft/published distinction is the product decision that matters: show
"unpublished changes" when has_unpublished_changes is true, and make clear that
editing does not change what is live until Publish. Show the embed snippet and
the allowed-origins list on the published view.

Add stories for draft, published, and published-with-pending-changes. Verify and
commit.
```

## Step 5 — Assignment rules and duplicate review

```
Two screens against existing APIs.

(1) Assignment rules at settings/assignment: ordered list with drag or
up/down reordering (POST /v1/assignment-rules/reorder), create and edit with the
condition builder limited to the fields the domain allows, and a dry-run against
a chosen lead using ?dry_run=true.

(2) Duplicate review on the lead detail page: call POST /v1/leads/{id}/deduplicate,
show candidates with match reason and confidence, and offer Merge with a clear
statement of which record survives and which fields will be filled.

Merge is destructive-feeling even though it is reversible; the confirmation must
name both records. Verify and commit.
```

## Step 6 — Migrate the 26 components to the design system

```
Migrate the existing feature components onto features/ui/primitives, module by
module, in this order: leads, contacts, accounts, deals, inbox, appointments,
analytics, settings.

Replace ad-hoc divs with Card, PageHeader, StatusPill, EmptyState and
ListSkeleton. Keep every existing aria attribute and test id - the vitest and
Playwright suites select on them.

Do one module per commit. After each, run pnpm a11y and confirm zero violations.
```

## Step 7 — Analytics charts and loading states

```
The analytics page renders rollup numbers as text. Add interactive charts using
Recharts: pipeline by stage, lead source mix, and won/lost over time.

Every chart needs a data table equivalent behind a "View as table" toggle - a
canvas chart is invisible to a screen reader and the a11y gate will not accept
colour-only series. Add ListSkeleton loading states to every route that fetches.

Verify with pnpm a11y and commit.
```

## Step 8 — Performance under real volume

```
Load backend/tests/fixtures/leads_messy_2000.csv through the import UI, then
measure. The lead list currently fetches page_size=50 with no virtualisation.

Check: list render time with 2000 rows, the N+1 risk in the deals board when
every stage loads its deals, and whether the duplicate scan (MAX_SCAN=500) is
adequate at that volume. Add cursor pagination or virtualisation where the
measurement justifies it - not before.

Report the numbers before and after.
```

## Step 9 — End-to-end coverage for the new surfaces

```
Add Playwright specs under apps/web/e2e for: invitation accept, CSV import
preview then commit, form publish then public submission, and a webchat visitor
session from an allowed origin.

These are the flows that cross the front end, the API and the database, so they
are the ones unit tests cannot cover. Verify and commit.
```

## Step 10 — Documentation and release truth

```
Update docs/RELEASE-BLOCKERS.md, docs/IMPLEMENTATION-LOG.md and
docs/ACCEPTANCE-EVIDENCE.md to match reality after the steps above. Every claim
must name the test or gate that proves it.

Do not mark anything GA. Confirm the external gates in
docs/GA-ACTIVATION-CHECKLIST.md are still listed as open.
```

---

## Externally blocked — not solvable by code

These need credentials or approval from outside the team. The adapters are
written and fail closed until each arrives.

| Channel | What is needed | Where it goes |
|---|---|---|
| WhatsApp | Meta app id, phone number id, permanent token, webhook verify token, **business verification and template approval** | `backend/.env` |
| Email | SES keys or SendGrid API key, **verified sender domain with SPF/DKIM/DMARC** | `backend/.env` |
| SMS | Provider key, **India DLT entity and template registration** | `backend/.env` |
| Voice | Exotel/Twilio SID and token, **recording-consent legal disclosure** | `backend/.env` |
| Razorpay | Test `key_id`/`key_secret`, webhook secret, **commercial approval** | `backend/.env` |
| Google Calendar | OAuth client id/secret, **app verification** | `backend/.env` |
| Tracing | OTLP collector endpoint | `OTEL_EXPORTER_ENDPOINT` |
| Infrastructure | AWS accounts, Route 53, ACM, KMS, GitHub OIDC | Terraform, gates 4.1–4.8 |

Web chat is the exception: first-party, no credentials, configurable at
`settings/webchat` today.

## Sequencing note

Steps 3–5 close functional gaps and matter more than steps 6–7, which are
polish. If time is short, ship 1–5 and leave the product visually plain but
functionally whole, rather than the reverse.
