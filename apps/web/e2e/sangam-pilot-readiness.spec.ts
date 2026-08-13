import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

/**
 * Is Sangam ready to carry one real SME's enquiries?
 *
 * The whole session-5 argument, exercised the way a pilot business would meet it:
 * a workspace of its own, three people with three different scopes, prospects
 * arriving by hand and by spreadsheet, and - the part founder dogfooding proved
 * was wrong - a first-response measurement that can tell a conversation from a
 * missed call and a meeting that happened from one that is merely in the diary.
 *
 * Runs in `sangam-pilot-e2e`, provisioned by the same `provision_workspace` call
 * a real pilot goes through, with all three roles and their real scopes. It is
 * stamped `test` rather than `pilot` on purpose: a `pilot` workspace counts as
 * real data in the destructive-maintenance guards, and labelling a workspace that
 * browser tests write to as real would make every reset warning look like a false
 * alarm. Provisioning a genuinely pilot-kind workspace is proven against a
 * throwaway tenant in `tests/integration/test_pilot_provisioning.py`.
 *
 * Sign-ins are rationed. Sign-in is rate limited to five attempts per IP per
 * fifteen minutes, and this file uses four.
 *
 *   .\RUN_DEMO.cmd
 *   $env:DEMO_PASSWORD='sangam-demo-2026'
 *   pnpm --filter @airevenueos/web exec playwright test sangam-pilot-readiness
 */

const PASSWORD = process.env.DEMO_PASSWORD ?? 'sangam-demo-2026';

const PILOT_OWNER = 'owner@pilot-e2e.test';
const PILOT_MANAGER = 'manager@pilot-e2e.test';
const PILOT_SALES = 'sales@pilot-e2e.test';
const FOUNDER = 'abhishek@sangam.co.in';

/** A genuine founder record. Nothing in this file may see it or change it. */
const CLAIDA = '019ff7f2-41eb-76b3-b229-68280ce353e3';

const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence/session-05-pilot-readiness');

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true });
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('sign-in').click();
  await page.waitForURL('**/today');
}

/** The number on a Today tile, so an assertion can reconcile against it. */
async function statValue(page: Page, testId: string): Promise<number> {
  const text = await page.getByTestId(testId).innerText();
  return Number(text.match(/\d+/)?.[0] ?? '-1');
}

/** Create a prospect and land on its detail page. */
async function newProspect(page: Page, name: string, phone: string): Promise<string> {
  await page.goto('/leads');
  await page.getByTestId('new-lead').click();
  await page.getByTestId('lead-company').fill(name);
  await page.getByTestId('lead-phone-input').fill(phone);
  await page.getByTestId('create-lead').click();
  await page
    .getByRole('row', { name: new RegExp(name) })
    .getByRole('link')
    .first()
    .click();
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();
  return page.url();
}

/** Log one contact against the prospect currently on screen. */
async function logContact(
  page: Page,
  options: { type: string; direction: string; outcome?: string; subject: string; next?: string },
): Promise<void> {
  await page.getByTestId('activity-type').selectOption(options.type);
  await page.getByTestId('activity-direction').selectOption(options.direction);
  if (options.outcome) {
    await page.getByTestId('activity-outcome').selectOption(options.outcome);
  }
  await page.getByLabel('Subject').fill(options.subject);
  if (options.next) {
    await page.getByTestId('next-action-input').fill(options.next);
    const due = new Date(Date.now() + 26 * 3_600_000).toISOString().slice(0, 16);
    await page.getByTestId('next-action-due').fill(due);
  }
  await page.getByTestId('log-activity').click();
  await expect(page.getByTestId('timeline-entries')).toContainText(options.subject);
}

test('a pilot workspace carries a real day of work, and measures it honestly', async ({ page }) => {
  test.setTimeout(600_000);
  const stamp = Date.now();
  const tail = String(stamp).slice(-5);

  await signIn(page, PILOT_OWNER);

  // --- 1 & 2. the workspace says whose it is, and the owner is in it ---------
  await expect(page.getByTestId('workspace-name')).toContainText('Pilot Test Workspace');
  await expect(page.getByTestId('workspace-kind')).toBeVisible();
  await shot(page, '01-pilot-workspace-identity');

  // --- 5. and it cannot see the founders' workspace -------------------------
  // A guessed id from another tenant. Row-level security makes this a "not
  // found" rather than an empty page, because an empty page would confirm the
  // record exists somewhere.
  await page.goto(`/leads/${CLAIDA}`);
  await expect(page.locator('body')).not.toContainText('Claida');
  await shot(page, '02-cross-tenant-record-denied');

  // --- 21 & 22. the starting baseline, captured once and reconcilable -------
  await page.goto('/today');
  const absent = await page.getByTestId('baseline-absent').count();
  if (absent > 0) {
    await shot(page, '03-starting-baseline-not-yet-captured');
    await page.getByTestId('capture-baseline').click();
  }
  await expect(page.getByTestId('baseline-present')).toBeVisible();
  // The "Now" column is the same figure the Today tile shows. If a baseline
  // could disagree with the dashboard neither would be worth reading.
  const awaitingTile = await statValue(page, 'stat-no-reply');
  await expect(page.getByTestId('current-awaiting_first_response')).toHaveText(
    String(awaitingTile),
  );
  await shot(page, '04-starting-baseline');

  // --- 6. a prospect added by hand ------------------------------------------
  const byHand = `Pilot Motors ${stamp}`;
  await newProspect(page, byHand, `+91 900${tail}01`);
  await shot(page, '05-untouched-prospect');

  // --- 16. a task does not answer anybody -----------------------------------
  // Logged on its own, with no follow-up attached, so the "nothing scheduled"
  // reconciliation at the end of this test measures exactly one promise.
  await page.getByTestId('activity-type').selectOption('task');
  await page.getByLabel('Subject').fill('Internal: prepare the quote');
  await page.getByTestId('log-activity').click();
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // --- 17. nor does an internal note ----------------------------------------
  await page.getByLabel('Note').fill('Owner is the son, not the father listed on the sheet.');
  await page.getByTestId('add-note').click();
  await expect(page.getByTestId('timeline-entries')).toContainText('Owner is the son');
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // --- 4 & 10. nor does giving it to somebody -------------------------------
  await page.getByTestId('lead-owner-select').selectOption({ label: 'Pilot Salesperson' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Pilot Salesperson');
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // --- 13. a missed call is a real record and not a reply -------------------
  await logContact(page, {
    type: 'call',
    direction: 'outbound',
    outcome: 'no_answer',
    subject: 'Tried the shop number',
  });
  await expect(page.getByTestId('timeline-entries')).toContainText('no answer');
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();
  await shot(page, '06-missed-call-still-waiting');

  // --- 11 & 19. the call that connects is what answers them -----------------
  await logContact(page, {
    type: 'call',
    direction: 'outbound',
    outcome: 'spoke',
    subject: 'Spoke to the owner about their enquiry',
    next: `Send the pricing note ${stamp}`,
  });
  await expect(page.getByTestId('lead-awaiting-response')).toHaveCount(0);
  await expect(page.getByTestId('lead-response-time')).toBeVisible();
  await expect(page.getByTestId('task-rows')).toContainText(`Send the pricing note ${stamp}`);
  await expect(page.getByTestId('lead-next-action')).toContainText(`Send the pricing note ${stamp}`);
  const answeredAt = await page.getByTestId('lead-response-time').innerText();
  await shot(page, '07-first-response-recorded');

  // --- 18. and a second contact does not restate the clock ------------------
  await logContact(page, {
    type: 'whatsapp',
    direction: 'outbound',
    outcome: 'sent',
    subject: 'Sent the pricing note',
  });
  await expect(page.getByTestId('lead-response-time')).toHaveText(answeredAt);

  // --- 12. an inbound call somebody actually picked up ----------------------
  const rang = `Pilot Bakery ${stamp}`;
  await newProspect(page, rang, `+91 900${tail}02`);
  // First they rang and nobody got to the phone. Still waiting.
  await logContact(page, {
    type: 'call',
    direction: 'inbound',
    outcome: 'no_answer',
    subject: 'Missed call from the bakery',
  });
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();
  // Then they rang again and somebody answered. That is a genuine first
  // engagement, and refusing to count it would punish answering the phone.
  await logContact(page, {
    type: 'call',
    direction: 'inbound',
    outcome: 'spoke',
    subject: 'They rang back and we talked it through',
  });
  await expect(page.getByTestId('lead-awaiting-response')).toHaveCount(0);
  await shot(page, '08-inbound-answered-counts');

  // --- 14 & 15. the diary is not a conversation -----------------------------
  const meeting = `Pilot Interiors ${stamp}`;
  await newProspect(page, meeting, `+91 900${tail}03`);
  await logContact(page, {
    type: 'meeting',
    direction: 'outbound',
    outcome: 'meeting_scheduled',
    subject: 'Site visit booked for Thursday',
  });
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();
  await shot(page, '09-scheduled-meeting-still-waiting');

  await logContact(page, {
    type: 'meeting',
    direction: 'outbound',
    outcome: 'meeting_held',
    subject: 'Went to the showroom and walked through it',
  });
  await expect(page.getByTestId('lead-awaiting-response')).toHaveCount(0);
  await shot(page, '10-completed-meeting-counts');

  // --- 7, 8 & 9. a list arrives as a spreadsheet ----------------------------
  // One row repeats a business already here, one row has no way to contact it.
  const csv = [
    'Business name,Contact person,Phone,Email,City,Industry,Why we are approaching them',
    `Pilot Tiffins ${stamp},Suresh Kumar,900${tail}11,suresh${stamp}@pilottiffins.in,Basavanagudi,Food,Counter orders on paper`,
    `Pilot Tailors ${stamp},,900${tail}12,,Malleshwaram,Tailoring,Measurements in a diary`,
    `Pilot Unreachable ${stamp},,,,Hebbal,Unknown,No way to contact them`,
    `Pilot Motors Again ${stamp},,+91 900${tail}01,,Jayanagar,Motors,Same business from another list`,
  ].join('\n');
  const csvPath = join(tmpdir(), `pilot-prospects-${stamp}.csv`);
  writeFileSync(csvPath, csv, 'utf-8');

  await page.goto('/sangam-pilot-e2e/imports');
  await expect(page.getByTestId('download-template')).toBeVisible();
  await page.setInputFiles('#csv', csvPath);

  await expect(page.getByTestId('normalised-sample')).toBeVisible();
  await expect(page.getByTestId('duplicate-rows')).toContainText('Same phone number');
  await expect(page.getByTestId('rejection-rows')).toContainText('could not be contacted');
  await shot(page, '11-import-preview-duplicates-and-rejections');

  await page.getByTestId('commit-import').click();
  await expect(page.getByTestId('import-summary')).toContainText('2 added');
  await expect(page.getByTestId('import-summary')).toContainText('1 already had');
  await expect(page.getByTestId('import-summary')).toContainText('1 unusable');
  await shot(page, '12-import-summary');

  await page.goto('/leads');
  await expect(page.getByTestId('lead-rows')).toContainText(`Pilot Tiffins ${stamp}`);
  // The unusable row was never created, and the duplicate was not created twice.
  await expect(page.getByTestId('lead-rows')).not.toContainText(`Pilot Unreachable ${stamp}`);
  await expect(page.getByTestId('lead-rows')).not.toContainText(`Pilot Motors Again ${stamp}`);

  // --- 20. finishing a follow-up reconciles against Today -------------------
  // The promise made on the call is in the queue.
  await page.goto('/follow-ups');
  await expect(page.getByTestId('follow-up-rows')).toContainText(`Send the pricing note ${stamp}`);

  // "No next action" counts open prospects with nothing scheduled. Pilot Motors
  // has this follow-up, so it is not in that count yet.
  await page.goto('/today');
  const noNextBefore = await statValue(page, 'stat-no-next-action');

  await page.goto('/follow-ups');
  await page
    .getByRole('row', { name: new RegExp(`Send the pricing note ${stamp}`) })
    .getByRole('button', { name: /done/i })
    .first()
    .click();
  // Counted, not "does not contain": closing the last open follow-up removes the
  // table entirely and renders the empty state, and a `not.toContainText` against
  // an element that no longer exists fails rather than passing.
  await expect(
    page.getByRole('row', { name: new RegExp(`Send the pricing note ${stamp}`) }),
  ).toHaveCount(0);
  await shot(page, '13-follow-up-completed');

  // Closing it leaves that prospect with nothing scheduled, and Today says so.
  // Two screens, one server-side definition of "open".
  await page.goto('/today');
  expect(await statValue(page, 'stat-no-next-action')).toBe(noNextBefore + 1);

  // --- Today reconciles with the records behind it --------------------------
  await page.goto('/today');
  const awaitingNow = await statValue(page, 'stat-no-reply');
  await expect(page.getByTestId('current-awaiting_first_response')).toHaveText(String(awaitingNow));
  await shot(page, '14-pilot-today');

  // --- the Test Centre tells the truth about all of it ----------------------
  await page.goto('/test-center');
  await expect(page.getByTestId('pilot-readiness')).toBeVisible();
  await expect(page.getByTestId('readiness-prospects')).toHaveAttribute('data-state', 'ready');
  await expect(page.getByTestId('readiness-import')).toHaveAttribute('data-state', 'ready');
  await expect(page.getByTestId('readiness-duplicates')).toHaveAttribute('data-state', 'ready');
  await expect(page.getByTestId('readiness-starting_baseline')).toHaveAttribute(
    'data-state',
    'ready',
  );
  await expect(page.getByTestId('readiness-team_scope')).toHaveAttribute('data-state', 'ready');
  // Calls and messages stay a human job during a shadow pilot, and the page says
  // so rather than implying Sangam sends them.
  await expect(page.getByTestId('readiness-manual_calls')).toHaveAttribute('data-state', 'manual');
  await shot(page, '15-test-centre-pilot-readiness');
});

test('a manager sees their team, and a salesperson sees their own work', async ({ page }) => {
  test.setTimeout(300_000);

  // --- 3. the manager's team scope resolves to something --------------------
  // This is the session-4 defect: a team-scoped manager with no team filters on
  // an empty set and is told "not found" for every record in the workspace.
  await signIn(page, PILOT_MANAGER);
  await expect(page.getByTestId('workspace-name')).toContainText('Pilot Test Workspace');
  await page.goto('/leads');
  await expect(page.getByTestId('lead-rows')).toContainText('Pilot Motors');
  await shot(page, '16-manager-sees-the-team');

  // A manager can open a record and reassign it without being told it is missing.
  await page
    .getByRole('row', { name: /Pilot Motors/ })
    .getByRole('link')
    .first()
    .click();
  await expect(page.getByTestId('lead-owner-current')).toBeVisible();
  await expect(page.getByTestId('owner-error')).toHaveCount(0);
});

test('a salesperson sees the work that is theirs', async ({ page }) => {
  test.setTimeout(300_000);

  // --- 4. self scope: narrower on purpose, and it must not be empty ---------
  await signIn(page, PILOT_SALES);
  await page.goto('/leads');
  // The first test assigned "Pilot Motors" to this person, so self scope has to
  // include it - and the Today figures are computed over the same scope.
  await expect(page.getByTestId('lead-rows')).toContainText('Pilot Motors');
  await shot(page, '17-salesperson-self-scope');

  await page.goto('/today');
  await expect(page.getByTestId('stat-no-reply')).toBeVisible();
  await shot(page, '18-salesperson-today');
});

test('the founders’ own workspace is untouched by any of it', async ({ page }) => {
  test.setTimeout(300_000);

  // --- 23. read-only. The pilot work above must not have reached this ------
  await signIn(page, FOUNDER);
  await expect(page.getByTestId('workspace-name')).toContainText('Sangam');

  await page.goto('/leads');
  // The genuine founder prospect recovered in session 4B, still exactly one.
  const claida = page.getByTestId('lead-rows').getByRole('row', { name: /Claida/ });
  await expect(claida).toHaveCount(1);
  // The 15 samples, still labelled as samples.
  await expect(page.getByTestId('lead-rows')).toContainText('SmileCraft Dental Care');
  await expect(page.getByTestId('lead-rows')).toContainText('sample');
  // And nothing this suite created has leaked across the tenancy boundary.
  await expect(page.getByTestId('lead-rows')).not.toContainText('Pilot Motors');
  await expect(page.getByTestId('lead-rows')).not.toContainText('Pilot Tiffins');
  await shot(page, '19-founder-workspace-unchanged');
});
