import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { signInAs } from './support/auth';

/**
 * The recovered prospect, seen in the founders' own workspace.
 *
 * This is the one spec that deliberately reads the real `sangam` workspace rather
 * than the browser-test tenant, because the thing being proven is about that
 * workspace: a genuine record the demo refresh destroyed is back, its surviving
 * history is attached to it, and there is exactly one of it.
 *
 * Read-only. It signs in, looks, and changes nothing - the safety of the refresh
 * itself is proven by `tests/integration/test_demo_refresh_safety.py`, which can
 * afford to delete things because it invents its own tenants.
 */

const CLAIDA = '019ff7f2-41eb-76b3-b229-68280ce353e3';

const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence/session-04b-data-safety');

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true });
}

test('the recovered prospect is back, once, with its history', async ({ page }) => {
  test.setTimeout(180_000);

  await signInAs(page, 'founder');

  // --- 1 & 5. visible again, and exactly one of it ---------------------------
  await page.getByTestId('nav-leads').click();
  await expect(page.getByTestId('lead-rows')).toContainText('Claida');
  const claidaRows = page.getByTestId('lead-rows').getByRole('row', { name: /Claida/ });
  await expect(claidaRows).toHaveCount(1);
  await shot(page, '01-claida-in-the-prospect-list');

  // --- 2. the details the source event preserved -----------------------------
  await page.goto(`/leads/${CLAIDA}`);
  // The heading is the *business*, and Claida is the person at it. That is the
  // redesign's business/contact separation (UI/UX system section 16): this
  // record was captured as company "Oxon" with contact "Claida", and a heading
  // that printed the person there is exactly the conflation the separation
  // exists to remove. Both facts are still on the page, in their own places.
  await expect(page.getByTestId('lead-name')).toContainText('Oxon');
  await expect(page.getByRole('main')).toContainText('Claida');
  await expect(page.getByTestId('lead-phone')).toContainText('919929552295');
  await expect(page.getByTestId('lead-email')).toContainText('aka.collective@gmail.com');

  // Not a sample. The recovered record must never be mistaken for demo data,
  // because that is exactly the mistake that destroyed it.
  await expect(page.getByTestId('demo-marker')).toHaveCount(0);

  // --- 3. still Kiran's, as the capture payload recorded ---------------------
  await expect(page.getByTestId('lead-owner-current')).toContainText('Kiran Deshpande');

  // --- 4. the two surviving calls are attached to it -------------------------
  await expect(page.getByTestId('timeline-entries')).toContainText('Call back later');
  const calls = page.getByTestId('timeline-entries').getByText('Call back later');
  await expect(calls).toHaveCount(2);

  // The tasks the audit could name are back too.
  await expect(page.getByTestId('task-rows')).toContainText('dealing');
  await shot(page, '02-claida-detail-with-history');
});

test('the sample businesses are still there beside it', async ({ page }) => {
  test.setTimeout(180_000);

  await signInAs(page, 'founder');

  // --- 9. the 15 samples rebuilt by the refresh, labelled as samples ---------
  await page.getByTestId('nav-leads').click();
  await expect(page.getByTestId('lead-rows')).toContainText('SmileCraft Dental Care');
  await expect(page.getByTestId('lead-rows')).toContainText('sample');

  // --- 8. and the founder's own record is not labelled that way --------------
  const claida = page.getByTestId('lead-rows').getByRole('row', { name: /Claida/ });
  await expect(claida).not.toContainText('sample');
  await shot(page, '03-samples-and-real-data-side-by-side');
});
