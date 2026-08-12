import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * Acceptance evidence for the one number the leakage story rests on.
 *
 * The claim being tested is narrow and commercially important: Sangam knows
 * whether a prospect has actually been answered, and it will not be fooled by
 * activity that never reached the customer. A team could assign, score and
 * schedule every enquiry in the book and this figure must not move.
 *
 * The prospect is created here, through the UI, rather than borrowed from the
 * seeded workspace: the run has to be repeatable, and a seeded prospect would
 * already be answered on the second run.
 *
 * Requires the stack running:
 *   .\RUN_DEMO.cmd
 *   $env:DEMO_PASSWORD='sangam-demo-2026'
 *   pnpm --filter @airevenueos/web exec playwright test sangam-first-response
 */

const PASSWORD = process.env.DEMO_PASSWORD ?? 'sangam-demo-2026';
// Runs in the browser-test workspace, not the founders' own. See
// `sangam-founder-prospecting.spec.ts` for why that boundary is a tenant.
const OWNER = 'owner@sangam-e2e.test';

const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence/session-02-first-response');

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true });
}

/** The count on the Today tile, read as a number so it can be compared. */
async function awaitingCount(page: Page): Promise<number> {
  await page.goto('/today');
  const text = await page.getByTestId('stat-no-reply').innerText();
  return Number(text.match(/\d+/)?.[0] ?? '-1');
}

async function logActivity(
  page: Page,
  { type, direction, subject }: { type: string; direction: string; subject: string },
): Promise<void> {
  await page.getByLabel('Type').selectOption(type);
  await page.getByTestId('activity-direction').selectOption(direction);
  await page.getByLabel('Subject').fill(subject);
  await page.getByTestId('log-activity').click();
  await expect(page.getByTestId('timeline-entries')).toContainText(subject);
}

test('first response is recorded only by real outbound contact, and only once', async ({
  page,
}) => {
  test.setTimeout(180_000);

  const stamp = Date.now();
  const surname = `Waiting${stamp}`;

  // --- sign in --------------------------------------------------------------
  await page.goto('/login');
  await page.getByLabel('Email').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('sign-in').click();
  await page.waitForURL('**/today');

  const baseline = await awaitingCount(page);
  expect(baseline).toBeGreaterThanOrEqual(0);
  await shot(page, '01-today-before');

  // --- 1. a genuinely unanswered prospect arrives ---------------------------
  await page.getByTestId('nav-leads').click();
  await page.getByTestId('new-lead').click();
  // Quick add now leads with the business and one way to reach it; the contact
  // person sits behind "More details", because a prospecting list rarely has one
  // on day one.
  await page.getByTestId('lead-company').fill(`Sharma Auto Works ${stamp}`);
  await page.getByLabel('Email').fill(`nikhil-${stamp}@sharmaautoworks.in`);
  await page.getByTestId('more-details').click();
  await page.getByLabel('Contact person').fill('Nikhil');
  await page.getByLabel('Surname').fill(surname);
  await page.getByTestId('create-lead').click();

  const row = page.getByRole('link', { name: new RegExp(`Nikhil ${surname}`) });
  await expect(row).toBeVisible();

  // Sangam counts it as waiting immediately.
  expect(await awaitingCount(page)).toBe(baseline + 1);

  await page.goto('/leads?filter=awaiting');
  await expect(page.getByTestId('lead-rows')).toContainText(surname);
  await shot(page, '02-awaiting-list');

  await page.getByRole('link', { name: new RegExp(`Nikhil ${surname}`) }).click();
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();
  const leadUrl = page.url();

  // --- 2. assignment is not an answer ---------------------------------------
  await page.getByTestId('lead-owner-select').selectOption({ label: 'Test Rep' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Rep');
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // --- 3. qualification is not an answer ------------------------------------
  await page.getByTestId('qualify-rules').click();
  await expect(page.getByTestId('lead-score')).not.toContainText('Not scored yet');
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // --- 4. an internal follow-up is not an answer ----------------------------
  await page.getByLabel('Follow-up').fill('Ring the workshop back on Monday');
  await page.getByTestId('add-task').click();
  await expect(page.getByTestId('task-rows')).toContainText('Ring the workshop');
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // --- 5. an internal note is not an answer ---------------------------------
  await page.getByLabel('Note').fill('Landline rings out; try the mobile number.');
  await page.getByTestId('add-note').click();
  await expect(page.getByTestId('timeline-entries')).toContainText('Landline rings out');
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // --- 6. an INBOUND call is the enquiry, not the reply to it ---------------
  await logActivity(page, {
    type: 'call',
    direction: 'inbound',
    subject: 'Nikhil rang to ask whether we cover two-wheeler workshops',
  });
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();

  // Everything above has happened and the prospect is still, correctly, waiting.
  await shot(page, '03-still-waiting-after-internal-work');
  expect(await awaitingCount(page)).toBe(baseline + 1);

  // --- 7. the first genuine outbound contact ---------------------------------
  await page.goto(leadUrl);
  await logActivity(page, {
    type: 'call',
    direction: 'outbound',
    subject: 'Called Nikhil back about the workshop enquiry',
  });

  // The warning is replaced by a measured time.
  await expect(page.getByTestId('lead-awaiting-response')).toHaveCount(0);
  await expect(page.getByTestId('lead-response-time')).toBeVisible();
  const recorded = await page.getByTestId('lead-first-response').innerText();
  expect(recorded).toContain('First reply');
  await shot(page, '04-first-response-recorded');

  // --- 8. a later contact must not restate the clock ------------------------
  await logActivity(page, {
    type: 'whatsapp',
    direction: 'outbound',
    subject: 'Sent Nikhil the summary we promised',
  });
  const afterSecond = await page.getByTestId('lead-first-response').innerText();
  // Identical text means an identical timestamp: the first response stayed first.
  expect(afterSecond).toBe(recorded);
  await shot(page, '05-second-contact-does-not-move-it');

  // --- 9. the operational count reconciles ----------------------------------
  expect(await awaitingCount(page)).toBe(baseline);
  await shot(page, '06-today-after');

  // And the prospect has left the awaiting list it was in at step 1.
  await page.goto('/leads?filter=awaiting');
  await expect(page.getByTestId('lead-rows')).not.toContainText(surname);
});
