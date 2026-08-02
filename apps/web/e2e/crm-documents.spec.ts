import { expect, test } from '@playwright/test';

/**
 * Documents and files through the browser.
 *
 * Requires the demo stack to be running and seeded:
 *   .\scripts\demo.ps1 -Password 'your-local-passphrase'      (terminal 1)
 *   $env:DEMO_PASSWORD='your-local-passphrase'
 *   pnpm --filter @airevenueos/web test:e2e                    (terminal 2)
 *
 * The most important assertion is the negative one: with no AWS account the page
 * must say so plainly. A build that quietly showed an upload button would pass
 * every other check here and mislead the operator at the worst moment.
 */
const PASSWORD = process.env.DEMO_PASSWORD ?? 'demo-local-passphrase-2026';
const ACME = 'asha@acme.test';

async function signIn(page: import('@playwright/test').Page, email: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('sign-in').click();
  await page.waitForURL('**/leads');
}

test('attach a document to a contact and move it through its states', async ({ page }) => {
  const stamp = Date.now();
  const surname = `Docs${stamp}`;
  const title = `Quotation ${stamp}`;

  await signIn(page, ACME);

  await page.getByTestId('nav-contacts').click();
  await page.getByTestId('new-contact').click();
  await page.getByLabel('First name').fill('Meera');
  await page.getByLabel('Last name').fill(surname);
  await page.getByLabel('Email').fill(`meera-${stamp}@example.in`);
  await page.getByTestId('create-contact').click();

  await page.getByRole('link', { name: new RegExp(`Meera ${surname}`) }).click();
  await expect(page.getByTestId('contact-name')).toContainText('Meera');

  // Object storage is not configured, and the page says so rather than
  // offering an upload control that could not work.
  await expect(page.getByTestId('storage-unavailable')).toBeVisible();
  await expect(page.getByTestId('storage-unavailable')).toContainText('unavailable');
  await expect(page.getByTestId('files-empty')).toBeVisible();

  await expect(page.getByTestId('documents-empty')).toBeVisible();
  await page.getByLabel('Document title').fill(title);
  await page.getByTestId('add-document').click();

  const rows = page.getByTestId('document-rows');
  await expect(rows).toContainText(title);

  // Draft -> sent -> signed, each transition persisted server side.
  await page.getByTestId(/^advance-document-/).first().click();
  await expect(rows).toContainText('sent');
  await page.getByTestId(/^advance-document-/).first().click();
  await expect(rows).toContainText('signed');

  // Reload: the state came from PostgreSQL, not from client state.
  await page.reload();
  await expect(page.getByTestId('document-rows')).toContainText('signed');
});
