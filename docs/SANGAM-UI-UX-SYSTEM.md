# Sangam — UI/UX system

**Authoritative visual and product-interface specification.** Where this document
and any screen disagree, the screen is wrong.

Written 2026-08-14, against the accepted Session 05 checkpoint
(`sangam-pilot-whatsapp-session05`, master `9d622a9`). Companions:
`docs/PROJECT-STATE.md` (what the repository is) and `docs/CURRENT-REALITY.md`
(what actually works). **This document specifies presentation only.** It does not
add capability, and nothing in it may be implemented by inventing data the
product does not hold — section 4 lists exactly what exists.

---

## 1. What this is for

Sangam works. It measures first response honestly, it carries a real WhatsApp
conversation, and an SME can run a shadow pilot on it. It does not yet *look*
like software a business would buy, and that is now the gap.

The next session implements the redesign. This document exists so that session
spends its time building rather than rediscovering taste, and so the result is
one coherent application rather than eight separately-styled pages.

Read sections 2–4 before writing any code. Sections 5–13 are the system.
Sections 14–21 are per-screen. Section 22 is the execution order.

---

## 2. Product character

Sangam is **daily-use B2B operations software for Indian SMEs**. Somebody opens
it at 9:40am, works from it for ten minutes, and comes back four times before
lunch. It is not visited; it is used.

It must feel: professional, calm, trustworthy, operational, fast to scan, easy to
train a new salesperson on, and high quality without being fashionable.

It must not look: vibe-coded, AI-generated, Dribbble-inspired, neon SaaS, overly
rounded, gradient-heavy, card-heavy, toy-like, overstimulating, or decorated for
no reason.

The reaction we want is **"this looks like software my company could actually use
every day"** — not "this looks like another AI-generated dashboard".

Three tests to apply to any screen before calling it done:

1. **The grayscale test.** Print it in black and white. Every state — overdue,
   waiting, unassigned, failed — must still be identifiable. If removing colour
   removes meaning, the screen is wrong.
2. **The squint test.** Blur it. You should see a clear title, one dominant
   information surface, and calm margins — not a grid of floating rounded boxes.
3. **The training test.** Could you teach a new salesperson this screen in one
   sentence? Today: *"this is what needs a call before the day ends."*

---

## 3. Design direction

The approved Today / Daily Command Center concept is **inspiration, not a
pixel-perfect specification**. The real implementation should be more disciplined
than the concept, not less: fewer boxes, fewer colours, fewer badges, more
alignment.

The governing idea is **document, not dashboard**. A page is a titled document
with sections separated by rules and space. It is not a tray of independent
floating cards. Containment is earned: a box appears only when the information
inside it genuinely needs to be separated from what surrounds it.

---

## 4. What the product actually holds

**Do not design against data that does not exist.** Verified against the running
system at the Session 05 checkpoint.

### Available today

| Concept | Where it lives | Notes |
| --- | --- | --- |
| Business name | `lead.capture.company` | JSON capture field, not an FK |
| Contact person | `lead.first_name` + `lead.last_name` | See the trap below |
| Owner | `lead.assignee_id` → `/users/members` for the name | Names must be resolved by the page |
| Source | `lead.source` | Free-ish string (`web_form`, `referral`, …) |
| Status | `lead.status` | new, contacted, qualified, nurturing, converted, disqualified, archived |
| First response | `lead.first_response_at` | Never backfilled, never overwritten |
| Age / waiting | `lead.created_at` | Derived in the page |
| Next action | `/tasks?status=open` joined on `entity_id` | Server decides `is_overdue` |
| Operational counts | `/leads/response-metrics` | Server-side, in the caller's scope |
| Starting baseline | `/leads/starting-baseline` | Captured once per workspace |
| Conversations | `/conversations` | channel, status, `unread_count`, `last_message_at`, `assignee_name`, and a `lead` context block with name/company/phone/owner |
| Message delivery state | `message.status` | queued, sent, delivered, read, failed |
| Pipeline totals | `/deals/board` | `open_count`, `open_value_minor` |
| Analytics sections | `/analytics/dashboard` | leads, revenue, appointments, conversations, sla, team_performance, lead_sources, pipeline_by_stage, daily, scope |

### The Business/Contact trap — read this twice

`new-lead-form.tsx` sets `first_name = person || company`. When a business is
added with no named contact — which is the common case for a prospecting list —
**the company name is stored in the contact-name field**, and `capture.name_is_business = true`
is set to say so.

Consequences the redesign must honour:

- **A prospect row must lead with the business.** Render `capture.company` when
  present; otherwise render `first_name` as the business.
- **The contact column must be empty, not duplicated.** If
  `capture.name_is_business` is true, there is no contact person — show `—`.
  Printing the same string in both columns is the exact confusion this section
  exists to prevent.
- Business, Primary Contact and Owner are **three different columns** and never
  interchangeable. A demo row where all three are the same person is a bug.

Correct:

```
Business            Primary contact     Owner
GreenField Foods    Amit Patel          Neha Sharma
Anand Xerox         —                   Kiran Deshpande
```

### Not available — do not design as though it were

- **No server-side column sorting or pagination.** Lists fetch a fixed page
  (`page_size=50`/`100`). Sorting may be done client-side over the loaded page
  and must be labelled honestly; do not draw a pager that cannot page.
- **No full-text search endpoint** for prospects.
- **No "suggested next action" engine.** Any right-rail suggestion must be
  derived from rules already visible in the data (no next action set, oldest
  wait, overdue task) and worded as an observation, not advice from a model.
- **No unified activity feed across entities** — activity is per-record.
- **No saved views, no bulk actions, no CSV export** (export is deliberately
  disabled).
- **Analytics figures are unreconciled** against the underlying records. The
  screen must keep saying so.
- **Email, SMS, voice, payments, documents and AI are provider-gated.** The UI
  states the real reason and disables the control; it never fabricates success.

---

## 5. What must change — implementation inventory

Grounded in the current code. This is the work, not a wish list.

### 5.1 Tokens and global CSS — `src/app/globals.css`

| Current | Problem | Change |
| --- | --- | --- |
| `--radius: 0.75rem`, `--radius-lg: 1.25rem` | Overly rounded; reads consumer | `--radius-sm: 4px`, `--radius: 6px`, `--radius-lg: 8px` |
| `body` two radial gradients, `background-attachment: fixed` | Gradient-heavy; the single loudest "AI dashboard" signal | **Delete.** Flat canvas |
| `.surface` = border + `radius-lg` + shadow, applied to everything | Card-heavy | Keep `.surface` for genuine panels only; drop the shadow, keep a 1px border |
| `.interactive` lifts `translateY(-2px)` + shadow on hover | Decorative motion on data | **Delete.** Rows tint; cards do not fly |
| `.pill` + four tints, used for every status | The named anti-pattern | Replace with section 9's system |
| `.glass` backdrop-blur | Fashion | Remove, or keep only for the sticky table header if it earns it |
| `.stagger` fade-up on list children | Gratuitous | **Delete.** Data appears; it does not perform |
| `--shadow-sm/md/lg` used on cards | Depth where none is needed | Shadows only for overlays (menus, drawers, dialogs) |
| Global `min-height: 44px` on every `button`, `a[href]` | Correct for a11y, and it inflates dense UI | **Keep.** The existing `td a[href]` / `p a[href]` exemption is what makes tables possible — do not remove it |

### 5.2 Typography — `src/app/layout.tsx`

Currently **Inter** (`--font-sans`) plus **Outfit** (`--font-display`, applied by
`.heading`). Outfit is a geometric display face and is a large part of why the
product reads as designed-for-a-portfolio.

**Change: drop Outfit. One family — Inter — across the whole product.** Hierarchy
comes from size, weight and colour, not from a second typeface. Remove the
`Outfit` import, keep `--font-display` mapped to Inter so `.heading` keeps
working during migration, then retire `.heading` in favour of explicit classes.

### 5.3 Shared primitives — `src/features/ui/primitives.tsx`

| Component | Verdict |
| --- | --- |
| `Card` | Keep, restyle: 1px border, `radius-lg`, no shadow, no `interactive` |
| `Stat` | **Rewrite.** Currently an interactive card with a `text-3xl` figure and a coloured delta pill. Becomes a quiet metric block (section 14.1) |
| `StatusPill` | **Replace** with `StatusText` / `SeverityMark` / `LabelChip` (section 9). Keep a deprecated shim until the last caller is migrated |
| `PageHeader` | Keep, restyle to the section 6 header |
| `EmptyState` | Keep, restyle: no dashed border |
| `Skeleton`, `ListSkeleton` | Keep; mirror the new table shape |

New shared components to add: `AppShell` (sidebar + utility bar), `DataTable`,
`SectionHeader`, `Avatar`, `ChannelIcon`, `RelativeTime`, `Money`, `OwnerCell`,
`BusinessCell`, `Toolbar`, `Drawer`, `FieldRow`.

### 5.4 Application chrome — `src/features/crm/workspace-shell.tsx`

Currently a two-row top header with an **eleven-item horizontal tab strip** that
scrolls sideways, and `max-w-6xl` content. Eleven peers in a scrolling strip is
not navigation; it is a menu bar that hides half of itself.

**Change to a persistent left sidebar with grouped navigation plus a slim top
utility bar** (section 6). This is the single largest structural change and the
reason Today is implemented first.

### 5.5 Constraints that must not break

- **`data-testid` attributes are a contract.** Twelve browser tests across
  Sessions 02–05 and the Inbox hardening suite assert on them, and several assert
  on visible text (`no reply yet`, `Unassigned`, `sample`, `overdue`, workspace
  name). Move markup freely; **keep every `data-testid` and every asserted
  string**. If one genuinely must change, change the spec in the same commit and
  say so in the message.
- **The accessibility gate is Storybook + axe** (`pnpm a11y`). Every new shared
  component needs a story, and contrast must pass in **both** themes.
- **The Card `data-testid` forwarding fix must survive.** JSX drops hyphenated
  attributes on components silently; that cost a session once already.
- Tables already use `font-variant-numeric: tabular-nums` via `td, th, .tabular`.
  Keep it.
- No new heavyweight dependency. `lucide-react` (icons) and `recharts` (charts)
  are present and sufficient. A ~10-line `cn()` class-merge helper is acceptable.

---

## 6. Layout and application structure

```
┌────────────┬──────────────────────────────────────────────────────────┐
│            │  utility bar   workspace · search · theme · account      │  52px
│  sidebar   ├──────────────────────────────────────────────────────────┤
│  240px     │                                                          │
│            │  Page title                              [primary action]│
│  grouped   │  One line of context.                                    │
│  nav       │  ──────────────────────────────────────────────────────  │
│            │                                                          │
│            │  content, max 1280px, left-aligned                       │
└────────────┴──────────────────────────────────────────────────────────┘
```

**Sidebar — 240px, fixed, full height, its own 1px right border.** No shadow. The
active item is marked by a 2px left rule in the accent plus foreground text and a
subtle sunken background; never a filled pill.

Grouped, in the order the working day runs:

```
WORK          Today · Prospects · Follow-ups · Inbox
RECORDS       Contacts · Accounts · Deals · Appointments
DATA          Import · Analytics
SETUP         Settings   (Test Centre appears in local builds only)
```

Group labels: 11px, 500, uppercase, 0.06em tracking, muted, 16px above / 6px
below. Items: 14px, 34px high, 8px radius, icon 16px at 10px gap.

Collapses to a 64px icon rail below 1200px; a hamburger opens it as an overlay
below 900px.

**Utility bar — 52px.** Workspace name and kind marker on the left (this is the
current `data-testid="workspace-name"` / `workspace-kind` content and must keep
those ids), then a right cluster: theme toggle, account menu carrying the email
and sign-out. The `tenant-badge` test id lives here.

**Page header.** Title 24/600. Optional single-line description, 14px muted.
Primary action right-aligned on the same baseline. A 1px bottom rule closes the
header and separates it from content. **One `h1` per page.**

**Content.** `max-width: 1280px`, left-aligned, 32px page padding, 32px between
major sections. Sections separate with space and a hairline rule — not by putting
each one in a rounded rectangle.

---

## 7. Typography

One family: **Inter**. Weights 400, 500, 600 only. No 700 in the application
chrome; no 300.

| Role | Size / line-height | Weight | Colour | Notes |
| --- | --- | --- | --- | --- |
| Page title | 24 / 30 | 600 | `--text-primary` | `-0.01em`; one per page |
| Section heading | 15 / 20 | 600 | `--text-primary` | Dominates labels clearly |
| Subsection | 13 / 18 | 600 | `--text-primary` | Inside panels |
| Body | 14 / 21 | 400 | `--text-primary` | Default |
| Table cell | 14 / 20 | 400 | `--text-primary` | 500 for the identifying column |
| Table header | 12 / 16 | 500 | `--text-muted` | Uppercase, 0.04em. The only uppercase in the product |
| Secondary / metadata | 13 / 18 | 400 | `--text-muted` | Never below 13px for real content |
| Metric value | 26 / 30 | 600 | `--text-primary` | Tabular figures |
| Metric label | 13 / 18 | 500 | `--text-muted` | Sentence case, not uppercase |
| Form label | 13 / 18 | 500 | `--text-primary` | Above the field |
| Helper / error | 13 / 18 | 400 | muted / critical | |
| Micro | 12 / 16 | 500 | `--text-muted` | Group labels, chips. Sparingly |

Rules: page → section → label hierarchy must be obvious at a glance. Nothing
below 12px, and 12px only for labels and chips, never for data. No letter-spacing
tricks on body text. Numbers in tables and metrics are always tabular. Currency
is `₹` with `en-IN` grouping; durations are whole units (`3 hrs`, `2 days`) — the
existing `duration()` helper is right and should be shared.

---

## 8. Colour

Mostly neutral. Colour is a signal, not a surface treatment. **Target: fewer than
10% of pixels carry hue.**

Warm-neutral ramp at hue 30 so surfaces feel like paper rather than screens.

### Light

```css
--canvas:            30 20% 98%;   /* page background, warm off-white */
--surface:            0  0% 100%;  /* panels, table body */
--surface-sunken:    30 12% 96%;   /* table header, active nav, inset */
--surface-hover:     30 12% 97%;

--text-primary:      24 10% 12%;   /* warm charcoal — 15.8:1 on surface */
--text-secondary:    24  7% 32%;   /* 9.1:1 */
--text-muted:        24  6% 45%;   /* 5.9:1 — floor for real content */
--text-disabled:     24  6% 60%;   /* non-content only */

--border:            30 10% 89%;   /* hairlines, table rules */
--border-strong:     30 10% 78%;   /* inputs, dividers that must read */
--border-focus:     214 62% 44%;

--accent:           214 62% 34%;   /* Sangam Blue — links, primary action, 8.1:1 */
--accent-hover:     214 62% 27%;
--accent-soft:      214 45% 96%;   /* selected row, quietly */
--accent-fg:          0  0% 100%;

--critical:           4 60% 41%;   /* overdue, failed — 6.4:1 */
--critical-soft:      4 60% 96%;
--warning:           32 72% 33%;   /* due today, at risk — 6.0:1 */
--warning-soft:      32 72% 95%;
--positive:         152 44% 27%;   /* completed, answered — 6.2:1 */
--positive-soft:    152 40% 95%;
```

### Dark

Designed alongside, not inverted. Elevation comes from tonal steps, never from
glow. Surfaces get lighter as they come forward; text stays near-white and is
never pure white.

```css
--canvas:           220 14%  9%;
--surface:          220 13% 12%;
--surface-sunken:   220 14% 15%;   /* raised: headers, active nav */
--surface-hover:    220 13% 16%;

--text-primary:      30 12% 94%;   /* 14.6:1 on surface */
--text-secondary:    30  8% 76%;   /* 8.7:1 */
--text-muted:        30  6% 62%;   /* 5.2:1 */
--text-disabled:     30  6% 44%;

--border:           220 10% 21%;
--border-strong:    220 10% 32%;
--border-focus:     213 70% 62%;

--accent:           213 72% 68%;   /* 7.4:1 */
--accent-hover:     213 72% 76%;
--accent-soft:      215 40% 19%;
--accent-fg:        220 14%  9%;

--critical:           4 72% 69%;   /* 6.6:1 */
--critical-soft:      4 40% 19%;
--warning:           35 78% 62%;   /* 7.9:1 */
--warning-soft:      35 35% 18%;
--positive:         152 45% 60%;   /* 7.2:1 */
--positive-soft:    152 30% 17%;
```

Every pair above carries an intended ratio. **Change the lightness, keep the
ratio** — the a11y gate fails the build otherwise.

Colour is reserved for: critical/overdue, warning/due, positive/completed,
links/actions, and channel recognition where it genuinely helps. Nothing else.
No coloured section backgrounds, no tinted cards, no coloured group headings, no
coloured bullets before headings.

---

## 9. Status design

**Banned:** rows of `[ HIGH ] [ MEDIUM ] [ LOW ]` and
`[ WAITING ] [ CONTACTED ] [ FOLLOW-UP DUE ]` in filled rounded pills. That
pattern is the single clearest tell of a generated interface, and it makes every
row shout equally.

Preference order — always take the highest one that works:

1. **Ordering.** Urgency is usually best expressed by position. The oldest wait
   goes first; nothing needs to be red for that to be understood.
2. **Plain text.** `Unassigned`, `Not yet`, `None set` — the words already carry
   the meaning.
3. **Text emphasis.** Weight 500 plus `--critical` on the words themselves. This
   is the default for overdue.
4. **A narrow severity mark.** A 2px left rule on the row, or a 6px dot before a
   value. Used where a whole row needs to be findable while scanning.
5. **A label chip.** Last resort, only where the word alone is genuinely
   ambiguous. Rectangular, `radius-sm`, 1px border, **no fill**, 12px/500, in
   `--text-secondary` unless semantic. Examples that earn one: the `sample`
   marker, the workspace kind, a `failed` delivery.

Status vocabulary is sentence case (`Qualified`, not `QUALIFIED` or `qualified`).

Worked example — a prospect table row:

```
Business            Contact       Owner          Waiting      Next action
▌GreenField Foods   Amit Patel    Neha Sharma    3 days       Call back  Overdue
 Anand Xerox        —             Unassigned     4 hrs        None set
```

`▌` is a 2px critical rule. `Overdue`, `Unassigned` and `None set` are emphasised
text. No pills. It survives grayscale, because the rule is a shape and the words
are words.

---

## 10. Icons

Functional only. **`lucide-react`, 16px in dense UI, 18px in navigation, 1.5px
stroke, `currentColor`.** One family, no exceptions.

Use icons for: sidebar items, communication channels (WhatsApp, email, SMS,
call, web chat), actions on buttons where the verb is repeated often, utility
controls (theme, account, close, search), and rare state recognition.

**Do not** put an icon before every metric, section heading or table header.
"First response time" does not need a clock. If the label already says it, the
icon is noise.

Decorative illustration: none. An empty state is a sentence and a button.

---

## 11. People and avatars

**Never scrape or generate a photograph.** No external avatar service, no
gravatar, no stock faces, no AI portraits.

Resolution order:

1. The Sangam user's uploaded profile image, if one exists.
2. An explicitly stored contact image supplied by the business.
3. **Deterministic initials.**

Initials: up to two characters from the stored name, `surface-sunken` background,
`--text-secondary` foreground, 1px border, 500 weight, 12px in a 24px circle
(tables) or 13px in 28px (headers). Neutral by default. A deterministic tint from
a set of **four** muted hues is permitted for scanning in dense lists — never
saturated, never more than four.

The interface must look complete and correct when **every** person has initials
only, because that is the normal state. Avatars never carry status.

---

## 12. Design tokens

Implementation-ready. Keep this set small; resist adding to it.

```css
/* spacing — 4px base */
--space-1: 4px;   --space-2: 8px;   --space-3: 12px;  --space-4: 16px;
--space-5: 24px;  --space-6: 32px;  --space-7: 48px;

/* radii — deliberately small */
--radius-sm: 4px;  --radius: 6px;  --radius-lg: 8px;  --radius-full: 9999px;
/* radius-full is for avatars and nothing else */

/* elevation — overlays only */
--shadow-overlay: 0 4px 12px hsl(24 10% 12% / 0.10), 0 1px 3px hsl(24 10% 12% / 0.08);
--shadow-drawer:  0 8px 32px hsl(24 10% 12% / 0.14);
/* dark: same geometry, hsl(0 0% 0% / 0.44) and 0.56 */

/* controls */
--control-height: 36px;        /* inputs, selects, secondary buttons */
--control-height-sm: 30px;     /* toolbar, inline */
--control-height-lg: 40px;     /* primary action, mobile */
/* the global 44px min-target rule still applies to buttons and links; satisfy it
   with padding, not by inflating visual height */

/* tables */
--row-height: 44px;            /* default */
--row-height-compact: 36px;
--cell-x: 16px;
--table-header-height: 36px;

/* layout */
--sidebar-width: 240px;
--sidebar-collapsed: 64px;
--utility-bar-height: 52px;
--page-max: 1280px;
--page-pad-x: 32px;
--reading-max: 68ch;           /* prose and help text */
```

Border radius never exceeds 8px on a container. If something looks like a pill,
it is wrong unless it is an avatar.

---

## 13. Tables

Tables are Sangam's primary interface, not a fallback. They get first-class
treatment via a shared `DataTable`.

- **Density.** 44px rows default; 36px compact as a per-table preference. 16px
  horizontal cell padding. No zebra striping — a 1px `--border` bottom rule per
  row is enough and much calmer.
- **Header.** `--surface-sunken`, 36px, 12px/500 uppercase muted, 1px bottom
  border in `--border-strong`. Sticky under the utility bar for any table that
  can exceed ~15 rows.
- **The identifying column comes first**, weight 500, and is the link target.
  Rows link through the identifying cell, not the whole row — a row-wide click
  target makes text selection impossible and breaks the 44px exemption.
- **Hover:** `--surface-hover` background, 120ms. Nothing moves.
  **Selected:** `--accent-soft` with a 2px accent left rule.
  **Focus:** the global 2px focus ring, never suppressed.
- **Numeric and duration columns are right-aligned** and tabular. Text columns
  are left-aligned. Never centre data.
- **Sorting:** client-side over the loaded page only, indicated by a 12px caret
  in the active header. Say so in the caption when the set is truncated
  ("Showing the 50 most recent"). Do not draw a pager until the API pages.
- **Filters** live in a `Toolbar` directly above the table: segmented text links
  carrying counts (the current Inbox and Follow-ups filters already do this and
  are the right model). Active filter is 500 weight with a 2px underline.
- **Empty state** sits inside the table frame: one sentence saying what would put
  rows here, plus the primary action. Never a bare "No results".
- **Column widths:** the identifying column flexes; metadata columns are fixed.
  Truncate with ellipsis and a `title`; never wrap a table cell to three lines.
- **Responsive:** below 1100px drop the lowest-value columns in a declared order
  per table (each screen spec below names them). Below 700px the table becomes a
  stacked list of records showing identity, one status line and one action.
  Horizontal scroll only as a last resort, never for the identifying column.
- **Every table has a `<caption>`** (visually hidden is fine) and proper `scope`
  attributes. This is already done today and must not regress.

---

## 14. Screen — Today (Daily Command Center)

The most important screen in the product, and the one a demo opens on. Its job is
**not** to show everything Sangam knows. It answers five questions:

> What requires attention? Who owns it? How late is it? What should happen next?
> What changed recently?

### 14.1 Summary strip

**Five metrics maximum.** Today currently renders seven plus a pipeline pair;
that is the overload this section removes.

```
First response (typical)   Waiting for reply   Answered   Overdue follow-ups   Open pipeline
2 hrs                      7                   23 of 30   3                    ₹18,40,000
```

A single row, separated by 1px vertical rules — **not five cards**. Each is a
label (13/500 muted) above a value (26/600 tabular). Each links to the rows
behind it; the existing `stat-*` test ids move here unchanged. No sparklines, no
deltas, no arrows, no icons. If a figure cannot be computed the value is `—` and
the label says why in the hint.

The Starting Baseline block stays where it is, beneath the strip, unchanged in
behaviour: a *before* picture, no arrows, no percentages, and words rather than a
zero where there is not enough history.

### 14.2 Needs attention now — the primary surface

One sophisticated operational table, not four separate ones. Groups are section
headings **inside** the same table — a full-width `<tr>` with a 13/600 label and
a count — so the columns stay aligned across groups and the eye reads one grid.

Group order, fixed:

1. **Waiting for a first reply** — oldest first
2. **Follow-ups due today**
3. **Recently contacted** (last 7 days, most recent first)
4. **Stalled** — only rendered when non-empty

No coloured bullets before group headings. No coloured group backgrounds.

Columns:

| Column | Source | Align | Drops at |
| --- | --- | --- | --- |
| Business | `capture.company` → `first_name` | left | never |
| Primary contact | `first_name`/`last_name`, `—` when `name_is_business` | left | 900px |
| Source | `lead.source` | left | 1100px |
| Owner | `assignee_id` → member name, else `Unassigned` | left | never |
| Waiting / Due | derived from `created_at` or `due_at` | right | never |
| Last touch | `first_response_at` / `last_message_at` | right | 1100px |
| Next action | task title, else `None set` | left | 900px |

Row identity: a 24px initials avatar plus the business name in 500 weight.
Overdue rows carry the 2px critical left rule. `Unassigned`, `None set` and
`Overdue` are emphasised text. **No pills anywhere in this table.**

### 14.3 Right rail — narrow, optional, honest

240–280px, only rendered above 1280px, and only with content that exists:

- **At risk today** — the three longest waits and any follow-up already overdue.
  Derived, not predicted.
- **Team load** — open prospects per owner, from `assignee_id` counts. A short
  list with a count; no bar chart.

**Do not build "suggested next actions" as though a model produced it.** If it
appears at all it is an observation from a stated rule — "4 prospects have no next
action" linking to that filter.

### 14.4 Bottom

Pipeline snapshot (open deals count and value, linking to the board) and Recent
activity if it is genuinely useful. Both are quiet. Neither is a chart.

---

## 15. Screen — Prospects

The working list. **Business-first**, per section 4.

Toolbar: filter links with counts (`All`, `Waiting for a first reply`,
`Unassigned`, `No next action` — these already exist as server query params and
already carry the `clear-filter` test id), then the primary action **Add a
business** on the right.

Columns: Business · Primary contact · Owner · Next action · First reply · Age ·
Status. Drop Source and Age first at narrow widths.

- `no reply yet` stays as emphasised critical text beside the business name
  (existing test id `no-reply-{id}`).
- The `sample` marker stays as a bordered `LabelChip` — this one earns a chip,
  because mistaking demo data for a real prospect is exactly the error that cost
  a founder record once (existing test id `demo-{id}`).
- `Unassigned` stays emphasised critical text (existing test id `unassigned-{id}`).
- Status becomes plain sentence-case text, muted for settled states. **The
  `StatusPill` here goes.**

**Add a business** moves from an always-open form at the top of the list into a
right-hand drawer opened by the primary action. The list is what people come for;
the form is what they came to do once. Field-level validation behaviour and every
`error-*` test id are preserved exactly.

---

## 16. Screen — Prospect detail

Currently eight stacked `Card`s. Becomes a **two-column workbench** on desktop.

```
┌──────────────────────────────────────┬───────────────────────────┐
│  Business name            [actions]  │  Ownership & next action  │
│  Contact · phone · email             │  Qualification            │
│  ────────────────────────────────    │  Follow-ups               │
│  What they asked for                 │  Duplicates               │
│  Timeline / activity  (primary)      │                           │
│  Record an outreach                  │                           │
└──────────────────────────────────────┴───────────────────────────┘
```

- **Header:** business name as the `h1` (test id `lead-name`), with the contact
  person, phone and email as a metadata line beneath — three distinct facts,
  visibly distinct.
- **First response** is the most important sentence on the page. Either
  `First reply: 3 hrs after the enquiry arrived` or the emphasised critical
  `Waiting for a first reply`. Existing test ids `lead-first-response`,
  `lead-response-time`, `lead-awaiting-response` stay.
- **Timeline** is the primary surface: a single-column list, 13px timestamp
  muted, direction stated in words ("We contacted them" / "They contacted us"),
  outcome as text. Append-only — no edit or delete affordance, ever.
- **Record an outreach** stays one save: channel, direction, outcome, note, next
  action + due date. It is a form section, not a floating card.
- Right column panels are separated by hairlines, not individually boxed.

---

## 17. Screen — Inbox

**Professional sales/support operations software, not a WhatsApp clone.** No
chat bubbles with tails, no wallpaper, no emoji reactions, no coloured balloons.

Two-pane at ≥1100px: a 360px conversation list and the transcript. Below that,
list and thread are separate routes as they are today.

**Conversation list row** — distinguishing all seven required facts:

```
[WA]  GreenField Foods              14:32
      Amit Patel · Neha Sharma       ●2
      "Can you send the quote for…"
```

Line 1: channel icon, **business**, time right-aligned. Line 2: contact ·
owner, unread count right-aligned as a small accent dot with a number (the
existing `unread-{id}` test id). Line 3: last message preview, one line,
truncated, muted. Unread rows: business name at 600 rather than a coloured
background. Status filters keep their counts (`filter-*` test ids) — that
behaviour was fixed in Session 05 and is correct.

**Transcript.** Readability first: a single column, max ~68ch, left-aligned.
Inbound and outbound are distinguished by alignment and a subtle surface step —
inbound on `--surface`, outbound on `--surface-sunken` with a 2px accent left
rule — plus a stated sender and time. Message text 14/21.

**Provider truth stays honest and visually quiet.** `queued`, `sent`,
`delivered`, `read`, `failed` render as 12px muted text under the message.
`failed` is the one that earns `--critical` and a bordered chip, because it means
the customer never received it. Never invent a tick-mark system that implies more
than the provider told us.

The canonical customer context (name, business, owner, phone) stays in a header
strip above the transcript, linking to the prospect. The dev-only "record an
inbound message" control remains hidden on provider-connected channels — that is
proven by the Inbox hardening spec and must not regress.

---

## 18. Screen — Follow-ups

The shared promise queue. A single table, soonest first.

Toolbar filters `All` / `Overdue` / `Mine` with counts (existing `filter-*` test
ids). Columns: Follow-up · Business · Owner · Due · Action. Overdue rows carry
the critical left rule and emphasised `Overdue` text — **not** a red pill.

Completion is an inline secondary button in the row that removes the row on
success and updates the Today count. This is the interaction that proves the
dashboard is real; it must feel immediate.

---

## 19. Screen — Import

A three-step wizard: **Upload → Review → Confirm**. Steps are a numbered
horizontal indicator (the existing `step-dot` styling, restyled square-ish and
without the scale animation).

The Review step is the whole product here and must stay legible:

- **How the first rows will be saved** — a preview table showing cleaned values.
- **Already in Sangam** — matched rows with *what they matched on*, in words.
- **Rows that will not be imported** — with a per-row reason.

Three sections, three counts, one confirm button that states exactly what it will
do (`Import 24 businesses`). Nothing is written before that click, and the screen
must keep saying so. Existing behaviour and test ids are preserved.

---

## 20. Screen — Analytics

Charts render via `recharts` with a table equivalent beneath each — that already
exists and is right.

**The unreconciled-figures caveat must remain visible on the page**, not buried
in a doc. A single quiet notice at the top: these numbers have not been checked
against the underlying records, and are not for customers.

Reduce the ten-`Stat` grid to the sections the API actually returns, each with a
heading and its own small table: leads, revenue, conversations, SLA, team
performance, lead sources, pipeline by stage, daily. Chart colours come from the
accent plus neutral steps — **not** a categorical rainbow. Export stays disabled
with its real reason.

---

## 21. Screen — Settings / Integrations

A two-column settings layout: a section list on the left, content on the right.

The integrations list is one table: Capability · Status · What it needs. Status
is text (`Connected`, `Not configured`, `Error`), with `Error` in `--critical`.
Each gated capability states the **real external prerequisite** in a sentence —
"needs a provider with a verified sending domain" — because that honesty is a
product feature, not a placeholder.

The Test Centre keeps its live-probe behaviour and stays development-only. Its
WhatsApp block must keep reporting the genuinely observed state; the pilot spec
asserts on `whatsapp-state` and the `data-observed` attributes.

---

## 22. Forms

- Labels **above** fields, 13/500, always visible. No placeholder-as-label.
- Field width matches expected content: phone ~180px, name ~280px, notes full
  width. A full-width input for a 10-digit number looks unconsidered.
- Group related fields under a subsection heading with a hairline. Progressive
  disclosure via a "More details" toggle is already the right pattern in quick
  add — keep it.
- **Validation:** server faults map to the field they belong to, in the founders'
  language, with `aria-invalid` and `aria-describedby`. Typed values are always
  preserved. Message sits directly beneath the field in `--critical` at 13px,
  with a 2px critical left rule on the field. Never a toast, never a summary at
  the top only, never framework wording. This behaviour was hard-won in Session
  04 and is pinned by tests.
- One obvious primary action, bottom-left of the form, in the accent. Secondary
  actions are text buttons. Destructive actions are never adjacent to the primary.
- Submitting disables the button and states what is happening ("Saving…").

---

## 23. Interaction and motion

Daily-use speed is the point.

- Navigation is predictable: sidebar → page → record. A record always opens as a
  page with its own URL; drawers are for creating and editing, never for reading.
- **Drawers/side panels only where they remove a navigation step** — add a
  business, edit a field, review a duplicate. Right-side, 480px, `shadow-drawer`,
  Escape closes, focus is trapped and returned.
- Hover and focus states are immediate (≤120ms). Focus is never suppressed.
- Inline actions (complete a follow-up, assign an owner) act in place and update
  the count they affect.
- Forms are keyboard-complete: logical tab order, Enter submits single-field
  forms, Escape closes drawers.

**Motion budget:** 120ms for state (hover, focus, selection), 180ms for entry
(drawer, menu). Transform and opacity only. No staggered list entry, no page
transitions, no lifting cards, no shimmer where a plain skeleton works.
`prefers-reduced-motion` is already honoured globally and must stay.

---

## 24. Responsiveness

Desktop is primary — this is business operations software used on a laptop.

| Width | Behaviour |
| --- | --- |
| ≥1440px | Full layout; right rail on Today |
| 1200–1439px | Right rail drops or moves below; content stays ≤1280px |
| 900–1199px | Sidebar collapses to a 64px icon rail; tables drop their declared low-value columns |
| 700–899px | Sidebar becomes an overlay; two-pane Inbox becomes list-then-thread |
| <700px | Tables become stacked record lists: identity, one status line, one action |

**Do not destroy hierarchy to claim mobile support.** A prospect list on a phone
shows business, owner and how long they have waited — not a squashed seven-column
grid. Reflow at 320px without two-dimensional scrolling is already required and
must hold.

---

## 25. Accessibility

Non-negotiable, and already gated by `pnpm a11y`.

- Text ≥4.5:1, boundaries and non-text ≥3:1, **in both themes**.
- Visible focus everywhere; never `outline: none` without a replacement.
- Semantic controls: a button is a `<button>`, navigation is `<nav>`, tables use
  `<th scope>` and a `<caption>`.
- **No state communicated by colour alone** — the grayscale test in section 2 is
  the same requirement stated for designers.
- Minimum 44px interactive targets (already enforced globally, with the
  in-table-link exemption that makes dense tables possible).
- Zoom to 500% is never disabled.
- Live regions for asynchronous updates: the Inbox auto-refresh should announce
  new messages politely, not silently reorder a list under someone's cursor.

---

## 26. Component reuse strategy

The pages must form one application. That happens through shared components, not
through eight pages that happen to use the same colours.

**Layer 1 — tokens.** `globals.css` + `tailwind.config.ts`. No component ever
hard-codes a colour, radius or spacing value.

**Layer 2 — primitives** (`src/features/ui/`):
`Button`, `Field`, `Select`, `Checkbox`, `LabelChip`, `StatusText`,
`SeverityMark`, `Avatar`, `ChannelIcon`, `RelativeTime`, `Money`, `Skeleton`,
`EmptyState`, `Drawer`, `Toolbar`, `SectionHeader`.

**Layer 3 — composites** (`src/features/ui/`):
`AppShell` (sidebar + utility bar + page header), `DataTable` (header, density,
sort, sticky, empty, responsive column dropping), `MetricStrip`, `RecordHeader`,
`FilterLinks`.

**Layer 4 — domain** (`src/features/{leads,crm,imports,analytics}/`): screen
pieces built only from layers 2 and 3.

Rules: a screen may not introduce a new visual pattern without adding it to layer
2 or 3 first. Every layer 2 and 3 component ships with a Storybook story covering
both themes, because that is what the a11y gate scans. If two screens need the
same thing twice, it moves down a layer — this is exactly how the current
eleven-tab header ended up duplicated across three layouts before it was
extracted.

---

## 27. Demo quality bar

Good enough to put in front of an SME owner without apologising for the
interface — and never at the cost of honesty.

- **No fabricated data or capability.** No fake avatars, no invented company
  logos, no mocked "AI insights", no numbers that do not reconcile to records
  someone can open.
- Demo rows must be *logically coherent*: a business, a different contact person,
  a different internal owner.
- A gated capability shows its real state and the real reason.

The story the interface must make obvious, end to end:

> enquiry arrives → prospect exists → owner assigned → first response →
> follow-up → activity → Today surfaces the next work

If a viewer can follow that path across Today, Prospects, Prospect detail and
Follow-ups without narration, the redesign has succeeded.

---

## 28. Execution order for the next session

Do them in this order. Each step ends green — `pnpm --filter @airevenueos/web typecheck`,
`lint`, and the browser suites for the screens touched.

| # | Step | Why here |
| --- | --- | --- |
| 0 | **Tokens + shell.** Rewrite `globals.css` tokens, drop the body gradients, drop Outfit, build `AppShell` with the sidebar. | Everything else inherits this. Doing it later means restyling twice. |
| 1 | **Layer 2/3 components** with stories: `DataTable`, `MetricStrip`, `Avatar`, `StatusText`, `LabelChip`, `Drawer`, `Toolbar`. | The screens are then assembly, not invention. |
| 2 | **Today.** | Highest-value screen, and it exercises every new component at once. |
| 3 | **Prospects** (+ add-business drawer). | Reuses `DataTable` immediately; proves the abstraction. |
| 4 | **Prospect detail.** | Completes the core loop with Today and Prospects. |
| 5 | **Inbox.** | Most bespoke layout; benefits from the system being settled. |
| 6 | **Follow-ups.** | Small once `DataTable` exists. |
| 7 | **Import.** | Self-contained wizard. |
| 8 | **Analytics.** | Mostly chart restyling; keep the caveat. |
| 9 | **Settings / Integrations.** | Lowest traffic. |
| 10 | **Shared polish + dark-mode verification.** Walk every screen in both themes, run `pnpm a11y`, run all six browser suites, regenerate visual evidence. | Dark mode is verified as a first-class pass, not assumed. |

Retire `StatusPill` and `.pill` only after step 9, when the last caller is gone.

At each step: **preserve every `data-testid` and asserted string** (section 5.5).
The browser suites are the safety net that makes a redesign of this size sane —
if they stay green, the product still works.

---

## 29. Decisions for the project head

Flagged rather than assumed:

1. **Accent colour.** Section 8 proposes a deep, restrained Sangam Blue
   (`214 62% 34%`) over the current indigo. It is a brand decision, not a
   technical one.
2. **Dropping Outfit.** Section 5.2 recommends one typeface. If Sangam later
   wants a wordmark face, it should be used for the wordmark only, never for
   headings.
3. **Sidebar vs. the current top tabs.** The sidebar is a real change to how the
   product is navigated. It is the right call for eleven sections, but it is
   visible to anyone already trained on the current build.
4. **Today's five metrics.** Choosing five means four current figures move off
   the summary strip (they remain reachable as filtered lists). Confirm the five.
5. **`sangam-first-slice.spec.ts`** still writes to the founders' workspace and
   will photograph the redesign there. Moving it to `sangam-e2e` should happen
   before the redesign regenerates evidence.
