import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

import { signInAs } from './support/auth';

/**
 * The founders' actual working day, end to end.
 *
 * A short list of Bengaluru businesses is imported, one row is deliberately
 * unusable, and one row is deliberately a business already in Sangam. Then a
 * single newly imported business is taken from "nobody has touched this" to
 * "owned, contacted, and with a promise on the calendar".
 *
 * This runs in `sangam-e2e`, a separate workspace that exists only for the browser
 * tests. The founders are about to keep their real prospecting in `sangam`, and a
 * suite that invented three businesses per run would fill their list with rubbish
 * within a week. Tenancy already draws that boundary and enforces it down to
 * row-level security, so nothing here can reach their data. Identities are still
 * run-unique, because the test tenant accumulates across runs and phone numbers
 * are the strongest duplicate signal.
 *
 *   .\RUN_DEMO.cmd
 *   $env:DEMO_PASSWORD='sangam-demo-2026'
 *   pnpm --filter @airevenueos/web exec playwright test sangam-founder-prospecting
 */

const EVIDENCE = resolve(
  __dirname,
  '../../../artifacts/visual-evidence/session-03-founder-dogfood',
);

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true });
}

async function awaitingCount(page: Page): Promise<number> {
  await page.goto('/today');
  const text = await page.getByTestId('stat-no-reply').innerText();
  return Number(text.match(/\d+/)?.[0] ?? '-1');
}

test('a founder imports a prospect list, then works one business through the day', async ({
  page,
}) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  // Phone numbers have to be run-unique as well as names. They are the strongest
  // dedupe signal, so a fixed number would make every run after the first collide
  // with the previous run's data - which is the feature working, but it makes the
  // test lie about which row it caught.
  const tail = String(stamp).slice(-5);
  const xeroxPhone = `+91 988${tail}67`;
  const tiffinsPhone = `984${tail}01`;
  const tailorsPhone = `984${tail}02`;

  // Signed in once per machine, in `support/global-setup.ts`, and adopted here.
  await signInAs(page, 'e2e-owner');

  const baseline = await awaitingCount(page);
  await shot(page, '01-today-work-queue');

  // --- 1. a business added by hand, the way one is noticed in passing --------
  await page.getByTestId('nav-leads').click();
  await page.getByTestId('new-lead').click();
  await page.getByTestId('lead-company').fill(`Anand Xerox ${stamp}`);
  await page.getByTestId('lead-phone-input').fill(xeroxPhone);
  await page.getByTestId('more-details').click();
  await page.getByLabel('What they do').fill('Print and stationery');
  await page.getByLabel('Area or city').fill('Jayanagar, Bengaluru');
  await page.getByLabel('Why we think they need us').fill('Takes bulk orders on WhatsApp, loses track of repeat customers');
  await shot(page, '02-quick-add-business');
  await page.getByTestId('create-lead').click();
  await expect(page.getByTestId('lead-rows')).toContainText(`Anand Xerox ${stamp}`);

  // --- 2. import a small list -----------------------------------------------
  // Row 3 has no way to contact the business; row 4 repeats the phone number of
  // the business just added by hand.
  const csv = [
    'Business name,Contact person,Phone,Email,City,Industry,Why we are approaching them',
    `Kumar Tiffins ${stamp},Suresh Kumar,${tiffinsPhone},suresh${stamp}@kumartiffins.in,Basavanagudi,Food,Counter orders written on paper`,
    `Vani Tailors ${stamp},,${tailorsPhone},,Malleshwaram,Tailoring,Measurements kept in a diary`,
    `Broken Row ${stamp},,,,Hebbal,Unknown,No way to contact them`,
    `Anand Xerox Again ${stamp},,${xeroxPhone},,Jayanagar,Print,Same shop from another list`,
  ].join('\n');

  const csvPath = join(tmpdir(), `sangam-prospects-${stamp}.csv`);
  writeFileSync(csvPath, csv, 'utf-8');

  await page.goto('/sangam-e2e/imports');
  await expect(page.getByTestId('download-template')).toBeVisible();
  await page.setInputFiles('#csv', csvPath);

  // The preview must show all three judgements before anything is written.
  await expect(page.getByTestId('normalised-sample')).toBeVisible();
  await expect(page.getByTestId('duplicate-rows')).toContainText('Same phone number');
  // The unusable row is named by its row number and the reason, which is what a
  // founder needs in order to go and fix the sheet.
  await expect(page.getByTestId('rejection-rows')).toContainText('could not be contacted');
  await shot(page, '03-import-preview-and-duplicates');

  await page.getByTestId('commit-import').click();
  await expect(page.getByTestId('import-summary')).toBeVisible();
  // Two created, one already held, one unusable.
  await expect(page.getByTestId('import-summary')).toContainText('2 added');
  await expect(page.getByTestId('import-summary')).toContainText('1 already had');
  await expect(page.getByTestId('import-summary')).toContainText('1 unusable');
  await shot(page, '04-import-summary');

  // --- 3. the imported businesses are real records, the bad row is not ------
  await page.goto('/leads');
  await expect(page.getByTestId('lead-rows')).toContainText(`Kumar Tiffins ${stamp}`);
  await expect(page.getByTestId('lead-rows')).toContainText(`Vani Tailors ${stamp}`);
  await expect(page.getByTestId('lead-rows')).not.toContainText(`Broken Row ${stamp}`);
  // The duplicate was not created a second time.
  await expect(page.getByTestId('lead-rows')).not.toContainText(`Anand Xerox Again ${stamp}`);

  // --- 4. untouched imports land in the queue that says so ------------------
  await page.goto('/leads?filter=awaiting');
  await expect(page.getByTestId('lead-rows')).toContainText(`Kumar Tiffins ${stamp}`);

  // --- 5. take ownership -----------------------------------------------------
  // Located by its row rather than by link text: this row's *name* is the contact
  // person the sheet supplied ("Suresh Kumar"), while the business name sits in
  // the next column. That is correct behaviour, and worth pinning down here.
  await page
    .getByRole('row', { name: new RegExp(`Kumar Tiffins ${stamp}`) })
    .getByRole('link')
    .first()
    .click();
  await expect(page.getByTestId('lead-awaiting-response')).toBeVisible();
  await page.getByTestId('lead-owner-select').selectOption({ label: 'Test Rep' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Rep');

  // --- 6 & 8. record the call actually made, and the promise made on it ------
  await page.getByLabel('Type').selectOption('call');
  await page.getByTestId('activity-direction').selectOption('outbound');
  // A structured outcome now, not decorative text on the subject line. "spoke" is
  // what makes this count as answering the enquiry; "no_answer" would not.
  await page.getByTestId('activity-outcome').selectOption('spoke');
  await page.getByLabel('Subject').fill('Called Suresh about the counter orders');
  await page.getByLabel('Details').fill('Writes every order in a notebook. Interested, wants to see it working.');
  await page.getByTestId('next-action-input').fill('Send Suresh the one-page summary');
  const due = new Date(Date.now() + 26 * 3_600_000).toISOString().slice(0, 16);
  await page.getByTestId('next-action-due').fill(due);
  await page.getByTestId('log-activity').click();

  // --- 7. first response is measured from that call --------------------------
  await expect(page.getByTestId('lead-awaiting-response')).toHaveCount(0);
  await expect(page.getByTestId('lead-response-time')).toBeVisible();
  // --- 8. and the promise became a real follow-up ---------------------------
  await expect(page.getByTestId('task-rows')).toContainText('Send Suresh the one-page summary');
  await expect(page.getByTestId('lead-next-action')).toContainText('Send Suresh');
  await shot(page, '05-prospect-after-outreach');

  // --- 9. it has left the leakage queue -------------------------------------
  await page.goto('/leads?filter=awaiting');
  await expect(page.getByTestId('lead-rows')).not.toContainText(`Kumar Tiffins ${stamp}`);

  // --- 10. and the promise is on the work queue -----------------------------
  await page.goto('/follow-ups');
  await expect(page.getByTestId('follow-up-rows')).toContainText('Send Suresh the one-page summary');
  await shot(page, '06-follow-up-queue');

  // The imported business that nobody has touched is still counted as waiting,
  // and the one just answered is not: net zero against the baseline, plus the
  // two still-untouched new businesses (Anand Xerox and Vani Tailors).
  expect(await awaitingCount(page)).toBe(baseline + 2);
  await shot(page, '07-today-after-the-round');

  // No cleanup step. The records stay in the test workspace, which is exactly
  // what it is for - and deleting them would mean deleting append-only activity
  // history, which the database rightly refuses.
});
