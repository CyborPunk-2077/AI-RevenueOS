import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { signInAs } from './support/auth';

/**
 * The redesign, photographed on every screen, in both themes.
 *
 * This is the visual gate for the UI/UX system in `docs/SANGAM-UI-UX-SYSTEM.md`.
 * It asserts almost nothing about behaviour - the six behavioural suites do that -
 * and instead exists so a project head can look at the whole product at once and
 * so a regression in one theme cannot hide behind a green run in the other.
 *
 * **It only reads.** It signs in to the founders' workspace because that is where
 * the realistic Bengaluru prospect data lives - a business, a different contact
 * person and a different internal owner on each row, which is exactly what the
 * layout has to survive - and it navigates and screenshots. It creates nothing,
 * edits nothing and completes nothing. Every suite that writes runs in
 * `sangam-e2e`.
 *
 *   .\RUN_DEMO.cmd
 *   $env:DEMO_PASSWORD='sangam-demo-2026'
 *   pnpm --filter @airevenueos/web exec playwright test sangam-ui-evidence
 */

const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence/session-06-ui-redesign');

/** A realistic laptop, which is what this product is used on. */
const LAPTOP = { width: 1440, height: 900 };

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function setTheme(page: Page, theme: 'light' | 'dark'): Promise<void> {
  // Written the way the product writes it, then reloaded so the pre-paint script
  // in the root layout is the thing that applies it. Toggling the class by hand
  // would photograph a state the real theme contract cannot produce.
  await page.evaluate((value) => window.localStorage.setItem('airev-theme', value), theme);
  await page.reload();
  await expect(page.locator('html')).toHaveClass(theme === 'dark' ? /dark/ : /^(?!.*dark).*$/);
}

/**
 * Viewport-sized, not full-page.
 *
 * A design review asks "what does somebody see when they open this on a laptop",
 * and that is the viewport. Full-page capture also lies about this layout in two
 * specific ways: a sticky table header is stitched in at its sticky offset and
 * paints over the first group heading, and the sidebar's viewport-height panel
 * leaves the rest of its column blank. Neither happens in a real browser.
 */
async function shoot(page: Page, path: string, name: string): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${EVIDENCE}/${name}.png` });
}

/** The rest of a long page, for the screens where length is the design problem. */
async function shootBelowTheFold(page: Page, name: string): Promise<void> {
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(150);
  await page.screenshot({ path: `${EVIDENCE}/${name}.png` });
  await page.evaluate(() => window.scrollTo(0, 0));
}

/** Every screen worth looking at, in the order the working day runs. */
const SCREENS: ReadonlyArray<{ path: string; name: string }> = [
  { path: '/today', name: '01-today' },
  { path: '/leads', name: '02-prospects' },
  { path: '/leads?filter=awaiting', name: '03-prospects-filtered' },
  { path: '/follow-ups', name: '05-follow-ups' },
  { path: '/follow-ups?filter=overdue', name: '06-follow-ups-overdue' },
  { path: '/inbox', name: '07-inbox' },
  { path: '/deals', name: '09-deals' },
  { path: '/contacts', name: '10-contacts' },
  { path: '/accounts', name: '11-accounts' },
  { path: '/appointments', name: '12-appointments' },
  { path: '/sangam/imports', name: '13-import' },
  { path: '/analytics', name: '14-analytics' },
  { path: '/settings/integrations', name: '15-settings-integrations' },
];

for (const theme of ['light', 'dark'] as const) {
  test(`every screen reads correctly in ${theme} mode`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(LAPTOP);
    await signInAs(page, 'founder');
    await setTheme(page, theme);

    for (const screen of SCREENS) {
      await shoot(page, screen.path, `${theme}-${screen.name}`);
      // Today and Analytics are the two screens whose whole design problem is
      // length, so the bottom of each is photographed as well.
      if (screen.name === '01-today' || screen.name === '14-analytics') {
        await shootBelowTheFold(page, `${theme}-${screen.name}-lower`);
      }
    }

    // The one drawer in the product, over the list it writes into.
    await page.goto('/leads');
    await page.getByTestId('new-lead').click();
    await expect(page.getByTestId('lead-company')).toBeVisible();
    await page.getByTestId('more-details').click();
    await page.screenshot({ path: `${EVIDENCE}/${theme}-02b-add-business-drawer.png` });
    await page.keyboard.press('Escape');

    // A record, which is a different layout problem from a list: one dominant
    // subject, a lot of metadata, and a timeline that has to stay readable.
    await page.goto('/leads');
    const first = page.getByTestId('lead-rows').getByRole('link').first();
    await expect(first).toBeVisible();
    await first.click();
    await expect(page.getByTestId('lead-name')).toBeVisible();
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `${EVIDENCE}/${theme}-04-prospect-detail.png` });
    await shootBelowTheFold(page, `${theme}-04-prospect-detail-lower`);

    // A conversation, if this workspace has one. The Inbox is the most bespoke
    // layout in the product and the one most likely to break in a single theme.
    await page.goto('/inbox');
    const conversation = page.getByTestId('conversation-rows').getByRole('link').first();
    if (await conversation.isVisible().catch(() => false)) {
      await conversation.click();
      await page.waitForLoadState('networkidle');
      await page.screenshot({ path: `${EVIDENCE}/${theme}-08-inbox-thread.png` });
    }
  });
}

/**
 * The Review step, which is the whole product on the Import screen and the only
 * one the static route cannot show.
 *
 * Run in `sangam-e2e` and stopped before the confirm, so nothing is written
 * anywhere - which is also the property the screen is claiming.
 */
test('the import review step shows what would happen, and writes nothing', async ({ page }) => {
  test.setTimeout(120_000);
  const stamp = Date.now();
  await page.setViewportSize(LAPTOP);
  await signInAs(page, 'e2e-owner');

  const csv = [
    'Business name,Contact person,Phone,Email,City,Industry,Why we are approaching them',
    `Evidence Sweets ${stamp},Ramesh Rao,98450${String(stamp).slice(-5)},ramesh${stamp}@sweets.in,Basavanagudi,Food,Counter orders on paper`,
    `Evidence Tailors ${stamp},,98451${String(stamp).slice(-5)},,Malleshwaram,Tailoring,Measurements in a diary`,
    `Evidence Broken ${stamp},,,,Hebbal,Unknown,No way to contact them`,
  ].join('\n');
  const csvPath = join(tmpdir(), `sangam-ui-evidence-${stamp}.csv`);
  writeFileSync(csvPath, csv, 'utf-8');

  for (const theme of ['light', 'dark'] as const) {
    await page.goto('/sangam-e2e/imports');
    await setTheme(page, theme);
    await page.setInputFiles('#csv', csvPath);
    await expect(page.getByTestId('normalised-sample')).toBeVisible();
    await expect(page.getByTestId('rejection-rows')).toBeVisible();
    await page.screenshot({ path: `${EVIDENCE}/${theme}-13b-import-review.png` });
    await shootBelowTheFold(page, `${theme}-13c-import-review-lower`);
  }
  // Deliberately never committed.
});

test('the shell holds together as the desktop narrows', async ({ page }) => {
  test.setTimeout(180_000);
  await signInAs(page, 'founder');

  // The widths the responsiveness table names: a wide desktop where Today's
  // observations sit beside the table, a laptop where they stack beneath it, and
  // the width at which the sidebar becomes a 64px icon rail.
  for (const width of [1680, 1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await shoot(page, '/today', `narrow-${width}-today`);
    await shoot(page, '/leads', `narrow-${width}-prospects`);
  }
});
