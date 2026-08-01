import { expect, test } from '@playwright/test';

/**
 * The full visible flow: sign in, create, list, open, edit, refresh, and confirm
 * a second tenant cannot see the first tenant's record.
 *
 * Requires the demo stack to be running and seeded:
 *   .\scripts\demo.ps1 -Password 'your-local-passphrase'      (terminal 1)
 *   $env:DEMO_PASSWORD='your-local-passphrase'
 *   pnpm --filter @airevenueos/web test:e2e                    (terminal 2)
 */
const PASSWORD = process.env.DEMO_PASSWORD ?? 'demo-local-passphrase-2026';
const ACME = 'asha@acme.test';
const GLOBEX = 'ravi@globex.test';

async function signIn(page: import('@playwright/test').Page, email: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('sign-in').click();
  await page.waitForURL('**/leads');
}

test('sign in, create, open, edit and persist across a refresh', async ({ page }) => {
  const surname = `Slice${Date.now()}`;

  await signIn(page, ACME);
  await expect(page.getByTestId('tenant-badge')).toContainText('acme');

  // Seeded records are visible.
  await expect(page.getByTestId('lead-rows')).toContainText('Meera');

  // Create.
  await page.getByTestId('new-lead').click();
  await page.getByLabel('First name').fill('Browser');
  await page.getByLabel('Last name').fill(surname);
  await page.getByLabel('Email').fill(`browser-${Date.now()}@example.in`);
  await page.getByTestId('create-lead').click();

  // It appears in the list.
  const row = page.getByRole('link', { name: new RegExp(`Browser ${surname}`) });
  await expect(row).toBeVisible();

  // Open it.
  await row.click();
  await expect(page.getByTestId('lead-name')).toContainText('Browser');

  // Edit it.
  await page.getByLabel('Last name').fill(`${surname}Edited`);
  await page.getByTestId('save-lead').click();
  await expect(page.getByTestId('saved')).toBeVisible();

  // Refresh: the value came from PostgreSQL, not client state.
  await page.reload();
  await expect(page.getByTestId('lead-name')).toContainText(`${surname}Edited`);
});

test('a second tenant cannot see the first tenant\'s record', async ({ page, context }) => {
  await signIn(page, ACME);
  await page.getByTestId('new-lead').click();
  await page.getByLabel('First name').fill('AcmePrivate');
  await page.getByLabel('Email').fill(`private-${Date.now()}@example.in`);
  await page.getByTestId('create-lead').click();

  const link = page.getByRole('link', { name: /AcmePrivate/ });
  await expect(link).toBeVisible();
  const href = await link.getAttribute('href');
  expect(href).toBeTruthy();

  // Sign out and in as the other tenant.
  await page.getByTestId('sign-out').click();
  await page.waitForURL('**/login');
  await context.clearCookies();
  await signIn(page, GLOBEX);

  // The other tenant's list does not contain it.
  await expect(page.locator('body')).not.toContainText('AcmePrivate');

  // Nor can the record be reached by its URL.
  await page.goto(href!);
  await expect(page.locator('body')).toContainText('Not found');
});
