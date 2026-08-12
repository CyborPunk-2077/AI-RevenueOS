import { expect, test } from '@playwright/test';

/**
 * Contacts and accounts through the browser.
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
  await page.waitForURL('**/today');
}

test('create an account, create a contact against it, edit and persist', async ({ page }) => {
  const stamp = Date.now();
  const accountName = `Sharma Motors ${stamp}`;
  const surname = `Contact${stamp}`;

  await signIn(page, ACME);

  // Accounts first: the contact form offers them in a select.
  await page.getByTestId('nav-accounts').click();
  await page.getByTestId('new-account').click();
  await page.getByLabel('Name').fill(accountName);
  await page.getByLabel('Industry').fill('Automotive');
  await page.getByTestId('create-account').click();
  await expect(page.getByRole('link', { name: accountName })).toBeVisible();

  // Contact linked to that account.
  await page.getByTestId('nav-contacts').click();
  await page.getByTestId('new-contact').click();
  await page.getByLabel('First name').fill('Kavita');
  await page.getByLabel('Last name').fill(surname);
  await page.getByLabel('Email').fill(`kavita-${stamp}@example.in`);
  await page.getByLabel('Account').selectOption({ label: accountName });
  await page.getByTestId('create-contact').click();

  const row = page.getByRole('link', { name: new RegExp(`Kavita ${surname}`) });
  await expect(row).toBeVisible();

  // Open it: the account link is shown.
  await row.click();
  await expect(page.getByTestId('contact-name')).toContainText('Kavita');
  await expect(page.getByTestId('contact-account-name')).toContainText(accountName);

  // Edit it.
  await page.getByLabel('Job title').nth(1).fill('Head of Sales');
  await page.getByTestId('save-contact').click();
  await expect(page.getByTestId('saved')).toBeVisible();

  // Refresh: the value came from PostgreSQL, not client state.
  await page.reload();
  await expect(page.getByText('Head of Sales').first()).toBeVisible();

  // And the account now lists the contact.
  await page.getByTestId('contact-account-name').getByRole('link').click();
  await expect(page.getByTestId('account-contact-rows')).toContainText(surname);
});

test('search narrows the contact list', async ({ page }) => {
  const stamp = Date.now();
  await signIn(page, ACME);
  await page.getByTestId('nav-contacts').click();

  await page.getByTestId('new-contact').click();
  await page.getByLabel('First name').fill(`Findme${stamp}`);
  await page.getByLabel('Email').fill(`findme-${stamp}@example.in`);
  await page.getByTestId('create-contact').click();
  await expect(page.getByRole('link', { name: new RegExp(`Findme${stamp}`) })).toBeVisible();

  await page.getByTestId('contact-search').fill(`Findme${stamp}`);
  await page.getByRole('button', { name: 'Search' }).click();
  await expect(page.getByTestId('contact-rows').getByRole('row')).toHaveCount(1);

  await page.getByTestId('contact-search').fill('nobodyhasthisname');
  await page.getByRole('button', { name: 'Search' }).click();
  await expect(page.getByTestId('contacts-empty')).toBeVisible();
});

test("a second tenant cannot see the first tenant's contact or account", async ({
  page,
  context,
}) => {
  const stamp = Date.now();
  await signIn(page, ACME);

  await page.getByTestId('nav-accounts').click();
  await page.getByTestId('new-account').click();
  await page.getByLabel('Name').fill(`AcmePrivateAccount${stamp}`);
  await page.getByTestId('create-account').click();
  const accountLink = page.getByRole('link', { name: `AcmePrivateAccount${stamp}` });
  await expect(accountLink).toBeVisible();
  const accountHref = await accountLink.getAttribute('href');

  await page.getByTestId('nav-contacts').click();
  await page.getByTestId('new-contact').click();
  await page.getByLabel('First name').fill(`AcmePrivateContact${stamp}`);
  await page.getByLabel('Email').fill(`private-${stamp}@example.in`);
  await page.getByTestId('create-contact').click();
  const contactLink = page.getByRole('link', {
    name: new RegExp(`AcmePrivateContact${stamp}`),
  });
  await expect(contactLink).toBeVisible();
  const contactHref = await contactLink.getAttribute('href');

  // Switch tenants.
  await page.getByTestId('sign-out').click();
  await page.waitForURL('**/login');
  await context.clearCookies();
  await signIn(page, GLOBEX);

  // Neither listing contains them.
  await page.getByTestId('nav-contacts').click();
  await expect(page.locator('body')).not.toContainText(`AcmePrivateContact${stamp}`);
  await page.getByTestId('nav-accounts').click();
  await expect(page.locator('body')).not.toContainText(`AcmePrivateAccount${stamp}`);

  // Nor can either be reached by its URL.
  await page.goto(contactHref!);
  await expect(page.locator('body')).toContainText('Not found');
  await page.goto(accountHref!);
  await expect(page.locator('body')).toContainText('Not found');
});
