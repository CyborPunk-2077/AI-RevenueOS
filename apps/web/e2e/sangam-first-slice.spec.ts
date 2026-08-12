import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The first commercial slice, exercised as a business journey and photographed.
 *
 * This is deliberately not a set of unit assertions about widgets. It walks the
 * path Sangam is actually being sold on - an enquiry arrives, somebody takes
 * ownership of it, it gets scored, a follow-up is promised, the call is recorded,
 * and the operational counts move - and writes a screenshot at each step that a
 * non-engineer can look at.
 *
 * Requires the stack running and the Sangam workspace seeded:
 *   .\RUN_DEMO.cmd                                  (or scripts\demo.ps1)
 *   $env:DEMO_PASSWORD='sangam-demo-2026'
 *   pnpm --filter @airevenueos/web test:e2e sangam-first-slice
 */

const PASSWORD = process.env.DEMO_PASSWORD ?? 'sangam-demo-2026';
const OWNER = 'abhishek@sangam.co.in';

// Repo-relative so the evidence lands beside the code rather than in a temp
// directory that the next session cannot find.
const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence');

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function shot(page: import('@playwright/test').Page, name: string): Promise<void> {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true });
}

async function signIn(page: import('@playwright/test').Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('sign-in').click();
  await page.waitForURL('**/today');
}

test('a Bengaluru enquiry is owned, scored, scheduled and recorded', async ({ page }) => {
  test.setTimeout(120_000);

  // --- 1. the login screen ---------------------------------------------------
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Sangam' })).toBeVisible();
  await shot(page, '01-sign-in');

  // --- 2. Today: what is slipping -------------------------------------------
  await signIn(page);
  await expect(page.getByRole('heading', { name: 'Today', exact: true })).toBeVisible();
  const overdueBefore = Number(
    (await page.getByTestId('stat-overdue').innerText()).match(/\d+/)?.[0] ?? '0',
  );
  expect(overdueBefore).toBeGreaterThan(0);
  await expect(page.getByTestId('no-reply-rows')).toContainText('SmileCraft Dental Care');
  await shot(page, '02-today');

  // --- 3. the prospect list, with ownership and next actions -----------------
  await page.getByTestId('nav-leads').click();
  await expect(page.getByRole('heading', { name: 'Prospects' })).toBeVisible();
  await expect(page.getByTestId('lead-rows')).toContainText('Vidyapeeth Academy');
  // The two facts that make this list worth opening in the morning.
  await expect(page.getByTestId('lead-rows')).toContainText('Unassigned');
  await expect(page.getByTestId('lead-rows')).toContainText('no reply yet');
  await shot(page, '03-prospects');

  // --- 4. an untouched enquiry ----------------------------------------------
  await page.getByRole('link', { name: 'Shreya Bhat' }).click();
  await expect(page.getByTestId('lead-name')).toContainText('Shreya Bhat');
  await expect(page.getByTestId('lead-requirement')).toContainText('branches');
  await expect(page.getByTestId('lead-owner-current')).toContainText('unassigned');
  await expect(page.getByTestId('lead-next-action')).toContainText('No follow-up is scheduled');
  await shot(page, '04-prospect-untouched');

  // --- 5. give it an owner ---------------------------------------------------
  await page.getByTestId('lead-owner-select').selectOption({ label: 'Priya Nair' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Priya Nair');

  // --- 6. score it, with no AI provider connected ----------------------------
  await page.getByTestId('qualify-rules').click();
  await expect(page.getByTestId('lead-score')).not.toContainText('Not scored yet');
  // The reasons are the point: a score nobody can interrogate is a number, not a
  // qualification.
  await expect(page.getByTestId('qualify-reasons')).toBeVisible();
  await shot(page, '05-owned-and-scored');

  // --- 7. promise a follow-up ------------------------------------------------
  const due = new Date(Date.now() + 26 * 3_600_000).toISOString().slice(0, 16);
  await page.getByLabel('Follow-up').fill('Call Shreya about the three branches');
  await page.getByLabel('Due').fill(due);
  await page.getByTestId('add-task').click();
  await expect(page.getByTestId('task-rows')).toContainText('Call Shreya');
  await expect(page.getByTestId('lead-next-action')).toContainText('Call Shreya');

  // --- 8. record what was actually said --------------------------------------
  await page.getByLabel('Subject').fill('Called Shreya about reminder handling');
  await page
    .getByLabel('Details')
    .fill(
      'Reception writes reminders in a diary. Two of three branches miss the evening list. ' +
        'Wants missed calls followed up the same day.',
    );
  await page.getByTestId('log-activity').click();
  await expect(page.getByTestId('timeline-entries')).toContainText('Called Shreya');
  await shot(page, '06-history-and-follow-up');

  // --- 9. the promise appears in the shared queue ----------------------------
  await page.getByTestId('nav-follow-ups').click();
  await expect(page.getByTestId('follow-up-rows')).toContainText('Call Shreya');
  await shot(page, '07-follow-up-queue');

  // --- 10. closing one moves the operational count ---------------------------
  await page.goto('/follow-ups?filter=overdue');
  const firstDone = page.getByTestId(/^done-/).first();
  await expect(firstDone).toBeVisible();
  await shot(page, '08-overdue-queue');
  await firstDone.click();

  await page.getByTestId('nav-today').click();
  await expect(page.getByTestId('stat-overdue')).toBeVisible();
  const overdueAfter = Number(
    (await page.getByTestId('stat-overdue').innerText()).match(/\d+/)?.[0] ?? '0',
  );
  // Closing a follow-up has to change the number the owner is judged on. If this
  // does not move, the dashboard is decoration.
  expect(overdueAfter).toBe(overdueBefore - 1);
  await shot(page, '09-today-after-closing');

  // --- 11. the pipeline ------------------------------------------------------
  await page.getByTestId('nav-deals').click();
  await expect(page.getByRole('heading', { name: /Deals|Pipeline/ })).toBeVisible();
  await shot(page, '10-pipeline');

  // --- 12. the internal status page -----------------------------------------
  await page.goto('/test-center');
  await expect(page.getByRole('heading', { name: 'Test Centre' })).toBeVisible();
  await expect(page.getByTestId('provider-rows')).toBeVisible();
  await shot(page, '11-test-centre');
});
