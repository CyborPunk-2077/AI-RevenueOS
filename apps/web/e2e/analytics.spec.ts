import { expect, test } from '@playwright/test';

const PASSWORD = process.env.DEMO_PASSWORD ?? 'demo-local-passphrase-2026';

async function signIn(page: import('@playwright/test').Page, email: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('sign-in').click();
  await page.waitForURL('**/today');
}

test('analytics is tenant scoped and exports stay honestly disabled', async ({ page }) => {
  await signIn(page, 'asha@acme.test');
  await page.getByTestId('nav-analytics').click();
  await expect(page.getByRole('heading', { name: 'Analytics' })).toBeVisible();
  await expect(page.getByTestId('analytics-totals')).toBeVisible();
  await expect(page.getByTestId('daily-trend')).toBeVisible();
  await expect(page.getByTestId('exports-disabled')).toContainText('unavailable');
  await expect(page.getByRole('button', { name: 'Export CSV' })).toBeDisabled();
  await expect(page.getByTestId('tenant-badge')).toContainText('acme');
});
