import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { signInAs } from './support/auth';

/**
 * The first commercial slice, exercised as a business journey and photographed.
 *
 * This is deliberately not a set of unit assertions about widgets. It walks the
 * path Sangam is actually being sold on - an enquiry arrives, somebody takes
 * ownership of it, it gets scored, a follow-up is promised, the call is recorded,
 * and the operational counts move - and writes a screenshot at each step that a
 * non-engineer can look at.
 *
 * **It runs in `sangam-e2e`, not in the founders' own workspace.** Every other
 * browser suite moved across in session 3; this one predates that boundary and
 * kept creating its prospect, its follow-ups and its activities in `sangam`,
 * where the founders now keep real prospecting data. Activities and source events
 * are append-only, so nothing it wrote there could ever be tidied away.
 *
 * Moving it meant it can no longer lean on the seeded demo businesses - the test
 * workspace is seeded empty on purpose - so the journey now **creates the
 * business it walks**, which is a better test anyway: every figure it asserts on
 * is one this run produced.
 *
 *   .\RUN_DEMO.cmd
 *   $env:DEMO_PASSWORD='sangam-demo-2026'
 *   pnpm --filter @airevenueos/web exec playwright test sangam-first-slice
 */

// Repo-relative so the evidence lands beside the code rather than in a temp
// directory that the next session cannot find.
const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence');

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true });
}

/** The operational count the owner is judged on, read off Today. */
async function overdueCount(page: Page): Promise<number> {
  const text = await page.getByTestId('stat-overdue').innerText();
  return Number(text.match(/\d+/)?.[0] ?? '-1');
}

function localDateTime(offsetMs: number): string {
  // `datetime-local` wants wall-clock time in the browser's own zone, so the
  // usual toISOString() trick would post a follow-up several hours out.
  const at = new Date(Date.now() + offsetMs);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    `T${pad(at.getHours())}:${pad(at.getMinutes())}`
  );
}

test('a Bengaluru enquiry is owned, scored, scheduled and recorded', async ({ page }) => {
  test.setTimeout(180_000);

  // Run-unique, because the test workspace accumulates across runs and a phone
  // number is the strongest duplicate signal there is.
  const stamp = Date.now();
  const business = `SmileCraft Dental Care ${stamp}`;
  const phone = `+91 98${String(stamp).slice(-8)}`;

  // --- 1. the login screen ---------------------------------------------------
  // Photographed without submitting: the suite adopts a stored session rather
  // than spending one of the five sign-in attempts the limiter allows per IP.
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Sangam' })).toBeVisible();
  await shot(page, '01-sign-in');

  await signInAs(page, 'e2e-owner');

  // --- 2. the enquiry arrives ------------------------------------------------
  await page.getByTestId('nav-leads').click();
  await expect(page.getByRole('heading', { name: 'Prospects' })).toBeVisible();
  await page.getByTestId('new-lead').click();
  await page.getByTestId('lead-company').fill(business);
  await page.getByTestId('lead-phone-input').fill(phone);
  await page.getByTestId('more-details').click();
  await page.getByLabel('Contact person').fill('Shreya');
  await page.getByLabel('Surname').fill(`Bhat ${stamp}`);
  await page.getByLabel('What they do').fill('Dental clinic');
  await page.getByLabel('Area or city').fill('Indiranagar, Bengaluru');
  await page
    .getByLabel('Why we think they need us')
    .fill('Reception keeps reminders in a diary and three branches miss the evening list.');
  await page.getByTestId('create-lead').click();
  await expect(page.getByTestId('lead-rows')).toContainText(business);

  // --- 3. Today: what is slipping -------------------------------------------
  await page.getByTestId('nav-today').click();
  await expect(page.getByRole('heading', { name: 'Today', exact: true })).toBeVisible();
  // The business just added has had no reply, so it is in the queue that says so.
  await expect(page.getByTestId('no-reply-rows')).toContainText(business);
  await shot(page, '02-today');

  // --- 4. the prospect list, with ownership and next actions -----------------
  await page.getByTestId('nav-leads').click();
  await expect(page.getByTestId('lead-rows')).toContainText(business);
  // The two facts that make this list worth opening in the morning.
  await expect(page.getByTestId('lead-rows')).toContainText('Unassigned');
  await expect(page.getByTestId('lead-rows')).toContainText('no reply yet');
  await shot(page, '03-prospects');

  // --- 5. an untouched enquiry ----------------------------------------------
  await page
    .getByRole('row', { name: new RegExp(business) })
    .getByRole('link')
    .first()
    .click();
  // The record header identifies this run's business. Asserted on the stamp
  // rather than on which of the two names leads, because that is precisely what
  // the redesign changes: `lead-name` currently renders the contact person and
  // becomes the business (UI/UX system §16). Both carry the stamp, so this holds
  // either way and does not have to be relaxed mid-redesign.
  await expect(page.getByTestId('lead-name')).toContainText(String(stamp));
  await expect(page.getByRole('main')).toContainText(business);
  await expect(page.getByTestId('lead-requirement')).toContainText('branches');
  // Untouched means nobody has replied yet - not that nobody owns it. This
  // workspace assigns a new prospect on capture, so asserting "unassigned" here
  // would be asserting a state the product does not produce.
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();
  await expect(page.getByTestId('lead-next-action')).toContainText('No follow-up is scheduled');
  await shot(page, '04-prospect-untouched');
  const leadUrl = page.url();

  // --- 6. hand it to the person who will actually call -----------------------
  await page.getByTestId('lead-owner-select').selectOption({ label: 'Test Rep' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Rep');

  // --- 7. score it, with no AI provider connected ----------------------------
  await page.getByTestId('qualify-rules').click();
  await expect(page.getByTestId('lead-score')).not.toContainText('Not scored yet');
  // The reasons are the point: a score nobody can interrogate is a number, not a
  // qualification.
  await expect(page.getByTestId('qualify-reasons')).toBeVisible();
  await shot(page, '05-owned-and-scored');

  // --- 8. promise a follow-up ------------------------------------------------
  await page.getByLabel('Follow-up').fill(`Call Shreya about the three branches ${stamp}`);
  await page.getByLabel('Due').fill(localDateTime(26 * 3_600_000));
  await page.getByTestId('add-task').click();
  await expect(page.getByTestId('task-rows')).toContainText('Call Shreya');
  await expect(page.getByTestId('lead-next-action')).toContainText('Call Shreya');

  // --- 9. record what was actually said --------------------------------------
  await page.getByLabel('Subject').fill('Called Shreya about reminder handling');
  await page.getByTestId('activity-outcome').selectOption('spoke');
  await page
    .getByLabel('Details')
    .fill(
      'Reception writes reminders in a diary. Two of three branches miss the evening list. ' +
        'Wants missed calls followed up the same day.',
    );
  await page.getByTestId('log-activity').click();
  await expect(page.getByTestId('timeline-entries')).toContainText('Called Shreya');
  await shot(page, '06-history-and-follow-up');

  // --- 10. the promise appears in the shared queue ---------------------------
  await page.getByTestId('nav-follow-ups').click();
  await expect(page.getByTestId('follow-up-rows')).toContainText('Call Shreya');
  await shot(page, '07-follow-up-queue');

  // --- 11. closing one moves the operational count ---------------------------
  // A promise this run made and this run has already broken, so the overdue count
  // is something this journey produced rather than something the workspace
  // happened to be carrying.
  await page.goto(leadUrl);
  await page.getByLabel('Follow-up').fill(`Send the pricing note ${stamp}`);
  await page.getByLabel('Due').fill(localDateTime(-30 * 3_600_000));
  await page.getByTestId('add-task').click();
  await expect(page.getByTestId('task-rows')).toContainText('Send the pricing note');

  await page.getByTestId('nav-today').click();
  const overdueBefore = await overdueCount(page);
  expect(overdueBefore).toBeGreaterThan(0);

  await page.goto('/follow-ups?filter=overdue');
  const closing = page
    .getByRole('row', { name: new RegExp(`Send the pricing note ${stamp}`) })
    .getByTestId(/^done-/);
  await expect(closing).toBeVisible();
  await shot(page, '08-overdue-queue');
  await closing.click();
  await expect(closing).toHaveCount(0);

  await page.getByTestId('nav-today').click();
  await expect(page.getByTestId('stat-overdue')).toBeVisible();
  // Closing a follow-up has to change the number the owner is judged on. If this
  // does not move, the dashboard is decoration.
  expect(await overdueCount(page)).toBe(overdueBefore - 1);
  await shot(page, '09-today-after-closing');

  // --- 12. the pipeline ------------------------------------------------------
  await page.getByTestId('nav-deals').click();
  await expect(page.getByRole('heading', { name: /Deals|Pipeline/ })).toBeVisible();
  await shot(page, '10-pipeline');

  // --- 13. the internal status page -----------------------------------------
  await page.goto('/test-center');
  await expect(page.getByRole('heading', { name: 'Test Centre' })).toBeVisible();
  await expect(page.getByTestId('provider-rows')).toBeVisible();
  await shot(page, '11-test-centre');

  // No cleanup step. The records stay in the test workspace, which is exactly
  // what it is for - and deleting them would mean deleting append-only activity
  // history, which the database rightly refuses.
});
