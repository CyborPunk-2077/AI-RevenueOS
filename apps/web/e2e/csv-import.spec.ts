import path from 'node:path';

import { expect, test } from '@playwright/test';

/**
 * The import fixture has a known answer: 1648 accepted, 352 rejected. Those
 * numbers come from running the domain planner over the same file, so a change
 * that silently loosens validation shows up here as a count mismatch rather than
 * as a support ticket six weeks later.
 */
const FIXTURE = path.join(
  __dirname,
  '..',
  '..',
  '..',
  'backend',
  'tests',
  'fixtures',
  'leads_messy_2000.csv',
);

test('preview reports the rejections before anything is written', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'asha@acme.test');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'demo-passphrase-2026');
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).toHaveURL(/leads/);

  await page.getByTestId('nav-imports').click();
  await page.getByLabel(/csv file/i).setInputFiles(FIXTURE);

  await expect(page.getByText(/1648 will be imported/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/352 will be skipped/i)).toBeVisible();

  // The per-row reasons are the point of the preview; a summary alone is not
  // actionable.
  await expect(page.getByRole('table', { name: /rejected rows/i })).toBeVisible();
  await expect(page.getByText(/duplicate of row/i).first()).toBeVisible();
});

test('committing imports exactly the accepted rows', async ({ page }) => {
  test.slow();
  await page.goto('/login');
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'asha@acme.test');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'demo-passphrase-2026');
  await page.getByRole('button', { name: /sign in/i }).click();

  await page.getByTestId('nav-imports').click();
  await page.getByLabel(/csv file/i).setInputFiles(FIXTURE);
  await page.getByRole('button', { name: /import 1648 leads/i }).click();

  await expect(page.getByText(/1648 imported/i)).toBeVisible({ timeout: 120_000 });
});
