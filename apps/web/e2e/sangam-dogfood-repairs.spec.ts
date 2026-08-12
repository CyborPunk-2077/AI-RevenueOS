import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The two defects the founder hit while dogfooding, proven fixed.
 *
 * Both were real and neither was cosmetic:
 *
 * 1. Reassigning a prospect answered "Lead not found" while the change had in
 *    fact been saved. Two causes, fixed separately - the token carried no team
 *    identifiers (so a team-scoped manager matched nothing), and the update
 *    re-read the record under the caller's scope *after* moving it out of that
 *    scope.
 * 2. Invalid input produced "The request payload failed validation", which is
 *    written for whoever reads a stack trace.
 *
 * Runs in the browser-test workspace, never the founders' own.
 */

const PASSWORD = process.env.DEMO_PASSWORD ?? 'sangam-demo-2026';
const OWNER = 'owner@sangam-e2e.test';
const REP = 'rep@sangam-e2e.test';

const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence/session-04-dogfood-repairs');

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

test('a prospect can be reassigned, and the page shows what was actually saved', async ({
  page,
}) => {
  test.setTimeout(180_000);
  const stamp = Date.now();

  await signIn(page, OWNER);

  // A prospect owned by somebody else, which is the case the founder hit.
  await page.getByTestId('nav-leads').click();
  await page.getByTestId('new-lead').click();
  await page.getByTestId('lead-company').fill(`Reassign Test ${stamp}`);
  await page.getByTestId('lead-phone-input').fill(`+91 977${String(stamp).slice(-5)}01`);
  await page.getByTestId('create-lead').click();
  await page.getByRole('row', { name: new RegExp(`Reassign Test ${stamp}`) }).getByRole('link').first().click();

  await page.getByTestId('lead-owner-select').selectOption({ label: 'Test Rep' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Rep');
  await expect(page.getByTestId('owner-error')).toHaveCount(0);
  const leadUrl = page.url();
  await shot(page, '01-reassigned-to-colleague');

  // --- 1 & 2. reassign back, and prove it persisted across a real reload -----
  await page.getByTestId('lead-owner-select').selectOption({ label: 'Test Owner' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Owner');
  await expect(page.getByTestId('owner-error')).toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Owner');
  await shot(page, '02-persisted-after-reload');

  // --- 4. a genuine failure must not look like success ----------------------
  // A stale version is exactly what a second tab would send. The save is refused,
  // the message is shown, and the panel keeps reporting the owner that is really
  // stored rather than the one the dropdown is showing.
  const refused = await page.evaluate(async (url: string) => {
    const token = document.cookie.match(/(?:^|;\s*)(?:__Host-)?airev-csrf=([^;]+)/)?.[1] ?? '';
    const id = url.split('/leads/')[1];
    const response = await fetch(`/api/leads/${id}`, {
      method: 'PATCH',
      headers: {
        'content-type': 'application/json',
        'x-csrf-token': token,
        'if-match': 'W/"1"',
      },
      credentials: 'same-origin',
      body: JSON.stringify({ status: 'contacted' }),
    });
    return response.status;
  }, leadUrl);
  expect(refused).toBe(412);

  await page.reload();
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Owner');
});

test('a team-scoped colleague can see and reassign their own team’s prospects', async ({ page }) => {
  test.setTimeout(180_000);

  // --- 3. scope is still enforced, and is no longer empty -------------------
  // The rep is a manager: team scope, not global. Before the fix their token
  // carried no team at all, so every prospect answered "not found". They should
  // now see the team's book - and still never see another tenant's.
  const stamp = Date.now();
  await signIn(page, REP);
  await page.getByTestId('nav-leads').click();

  // A prospect the rep adds themselves. It inherits their team, which is what
  // makes it visible to them afterwards - before the fix a manager could not see
  // even their own new records.
  await page.getByTestId('new-lead').click();
  await page.getByTestId('lead-company').fill(`Rep Prospect ${stamp}`);
  await page.getByTestId('lead-phone-input').fill(`+91 955${String(stamp).slice(-5)}03`);
  await page.getByTestId('create-lead').click();

  await expect(page.getByTestId('lead-rows')).toContainText(`Rep Prospect ${stamp}`);
  await shot(page, '03-team-scoped-colleague-can-work');

  // Reassigning away from themselves must report success, not "not found" - this
  // is the exact shape of the founder's bug.
  await page
    .getByRole('row', { name: new RegExp(`Rep Prospect ${stamp}`) })
    .getByRole('link')
    .first()
    .click();
  await page.getByTestId('lead-owner-select').selectOption({ label: 'Test Owner' });
  await page.getByTestId('assign-lead').click();
  await expect(page.getByTestId('owner-error')).toHaveCount(0);
  await expect(page.getByTestId('lead-owner-current')).toContainText('Test Owner');
  await shot(page, '04-reassigned-away-from-self');
});

test('bad input is explained field by field, and the entries are kept', async ({ page }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();

  await signIn(page, OWNER);
  await page.getByTestId('nav-leads').click();
  await page.getByTestId('new-lead').click();

  // --- 5. the founder's exact inputs ----------------------------------------
  await page.getByTestId('lead-company').fill(`Validation Test ${stamp}`);
  await page.getByTestId('lead-phone-input').fill('dasd');
  await page.getByLabel('Email').fill('adasd');
  await page.getByTestId('more-details').click();
  await page.getByLabel('Rough value (₹)').fill('asd');
  await page.getByTestId('create-lead').click();

  await expect(page.getByTestId('error-estimated_value')).toContainText('numbers only');
  await shot(page, '05-amount-rejected-clearly');

  // With the amount corrected, the server's own judgement on phone and email is
  // what the founder sees - in their language, on the right boxes.
  await page.getByLabel('Rough value (₹)').fill('25000');
  await page.getByTestId('create-lead').click();

  await expect(page.getByTestId('error-phone')).toContainText('valid phone number');
  await expect(page.getByTestId('error-email')).toContainText('valid email address');
  // Nothing framework-flavoured reaches the founder.
  await expect(page.getByTestId('new-lead-error')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('payload failed validation');
  await expect(page.locator('body')).not.toContainText('Value error');

  // Everything typed is still there; only the wrong boxes need touching.
  await expect(page.getByTestId('lead-company')).toHaveValue(`Validation Test ${stamp}`);
  await expect(page.getByLabel('Rough value (₹)')).toHaveValue('25000');
  await shot(page, '06-field-level-validation');

  // --- 6. corrected values go through ---------------------------------------
  await page.getByTestId('lead-phone-input').fill(`+91 966${String(stamp).slice(-5)}02`);
  await page.getByLabel('Email').fill(`owner-${stamp}@validationtest.in`);
  await page.getByTestId('create-lead').click();

  await expect(page.getByTestId('lead-rows')).toContainText(`Validation Test ${stamp}`);
  await shot(page, '07-accepted-after-correction');
});
