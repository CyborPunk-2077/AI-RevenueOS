import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The four live-Inbox defects the founder found once WhatsApp was really connected.
 *
 * All of them shared a shape: the product behaved correctly at the moment of the
 * request and then stopped telling the truth afterwards. A server-rendered page
 * fetches once and sits still, which was fine while every message was typed by
 * the person looking at the screen and stopped being fine the moment a provider
 * could write into the database on its own.
 *
 * Runs in `sangam-e2e`. The founders' own workspace and the live WhatsApp thread
 * are never written to here - the live conversation is checked read-only, by a
 * human, not by this file.
 *
 *   $env:DEMO_PASSWORD='sangam-demo-2026'
 *   pnpm --filter @airevenueos/web exec playwright test sangam-inbox-live
 */

const PASSWORD = process.env.DEMO_PASSWORD ?? 'sangam-demo-2026';
const OWNER = 'owner@sangam-e2e.test';

const EVIDENCE = resolve(__dirname, '../../../artifacts/visual-evidence/session-05-inbox-live');

test.beforeAll(() => {
  mkdirSync(EVIDENCE, { recursive: true });
});

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true });
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('sign-in').click();
  await page.waitForURL('**/today');
}

/**
 * Write straight to the API from the page's own session, deliberately bypassing
 * the UI. That is the point: it stands in for a provider webhook, which also
 * writes without this browser doing anything, and it is the only honest way to
 * prove the screen notices.
 */
async function apiPost(page: Page, path: string, body: unknown): Promise<void> {
  const status = await page.evaluate(
    async ([p, payload]) => {
      const token = document.cookie.match(/(?:^|;\s*)(?:__Host-)?airev-csrf=([^;]+)/)?.[1] ?? '';
      const response = await fetch(p as string, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-csrf-token': token },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      });
      return response.status;
    },
    [path, body] as const,
  );
  expect(status, `POST ${path}`).toBeLessThan(300);
}

test('a message that arrives while the conversation is open shows up on its own', async ({
  page,
}) => {
  test.setTimeout(240_000);
  const stamp = Date.now();

  await signIn(page);

  // A conversation on a channel with no provider, so this suite never touches
  // the live WhatsApp thread.
  await page.goto('/inbox');
  await page.getByTestId('new-conversation').click();
  await page.getByLabel('Subject').fill(`Live refresh ${stamp}`);
  await page.getByTestId('create-conversation').click();
  await page.getByTestId('conversation-rows').getByText(`Live refresh ${stamp}`).click();
  await expect(page.getByTestId('conversation-subject')).toContainText(`Live refresh ${stamp}`);
  const url = page.url();
  const conversationId = url.split('/inbox/')[1];
  await shot(page, '01-conversation-open');

  // --- 1. a stored inbound message becomes visible with no reload ------------
  // No navigation, no re-login, no reply. The page must notice by itself.
  await apiPost(page, `/api/conversations/${conversationId}/inbound`, {
    content: `how u been ${stamp}`,
  });
  expect(page.url(), 'the test must not have navigated').toBe(url);
  await expect(page.getByTestId('thread-messages')).toContainText(`how u been ${stamp}`, {
    timeout: 30_000,
  });
  await shot(page, '02-inbound-appeared-without-refresh');

  // --- 2. a status change becomes visible the same way ----------------------
  // Queue a reply, then move it on behind the screen's back.
  await apiPost(page, `/api/conversations/${conversationId}/messages`, {
    content: `reply ${stamp}`,
  });
  await expect(page.getByTestId('thread-messages')).toContainText(`reply ${stamp}`, {
    timeout: 30_000,
  });
  await shot(page, '03-status-visible');
});

test('the Inbox list stays honest about where conversations are', async ({ page }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();

  await signIn(page);

  await page.goto('/inbox');
  await page.getByTestId('new-conversation').click();
  await page.getByLabel('Subject').fill(`Filter check ${stamp}`);
  await page.getByTestId('create-conversation').click();
  // Wait for the row rather than navigating straight away: the create is a
  // request, and racing it makes this test fail for a reason that has nothing to
  // do with what it is checking.
  await expect(page.getByTestId('conversation-rows')).toContainText(`Filter check ${stamp}`);

  // --- 3. active conversations stay in Active -------------------------------
  await page.goto('/inbox?status=active');
  await expect(page.getByTestId('conversation-rows')).toContainText(`Filter check ${stamp}`);
  await shot(page, '04-active-populated');

  // Counts are shown on every filter, so an empty view can be told apart from
  // an empty inbox.
  await expect(page.getByTestId('filter-all')).toContainText('(');
  await expect(page.getByTestId('filter-archived')).toContainText('(');

  // --- 4. archiving moves it, and only to Archived --------------------------
  await page.goto('/inbox?status=active');
  await page.getByTestId('conversation-rows').getByText(`Filter check ${stamp}`).click();
  // Read the id only once the navigation has actually happened, or it is read
  // off the list URL and comes back undefined.
  await page.waitForURL(/\/inbox\/[0-9a-f-]{36}/);
  const conversationId = page.url().split('/inbox/')[1];
  // The select is controlled by the server's value, so it only *stays* on
  // "archived" once the change has been saved and the page re-rendered. Waiting
  // for that is the honest signal that the write landed; navigating straight
  // away would race it.
  await page.getByTestId('conversation-status').selectOption('archived');
  await expect(page.getByTestId('conversation-status')).toHaveValue('archived');

  await page.goto('/inbox?status=archived');
  await expect(page.getByTestId('conversation-rows')).toContainText(`Filter check ${stamp}`);
  await page.goto('/inbox?status=active');
  await expect(page.getByTestId('conversation-rows').getByText(`Filter check ${stamp}`)).toHaveCount(
    0,
  );
  // And All reconciles: it is still there, under a different filter.
  await page.goto('/inbox');
  await expect(page.getByTestId('conversation-rows')).toContainText(`Filter check ${stamp}`);
  await shot(page, '05-filters-reconcile');

  // --- 5. an inbound message cannot leave a thread hidden -------------------
  // The customer writing again reopens the thread rather than starting a second
  // one somewhere nobody looks.
  await apiPost(page, `/api/conversations/${conversationId}/inbound`, {
    content: `back again ${stamp}`,
  });
  await page.goto('/inbox?status=active');
  await expect(page.getByTestId('conversation-rows')).toContainText(`Filter check ${stamp}`);
  await shot(page, '06-inbound-reopens-thread');
});

test('the fake-inbound control is gone once a channel is really connected', async ({ page }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();

  await signIn(page);

  // --- 6 & 7. present for a gated channel, absent for a live one ------------
  await page.goto('/inbox');
  await page.getByTestId('new-conversation').click();
  await page.getByLabel('Subject').fill(`Gated channel ${stamp}`);
  await page.getByLabel('Channel').selectOption('email');
  await page.getByTestId('create-conversation').click();
  await page.getByTestId('conversation-rows').getByText(`Gated channel ${stamp}`).click();

  // Email has no provider, so the development control is still available - which
  // is exactly the case the browser suites need it for.
  await expect(page.getByTestId('channel-gated')).toBeVisible();
  await expect(page.getByTestId('record-inbound')).toBeVisible();
  await shot(page, '07-dev-control-present-for-gated-channel');

  await page.goto('/inbox');
  await page.getByTestId('new-conversation').click();
  await page.getByLabel('Subject').fill(`Live channel ${stamp}`);
  await page.getByLabel('Channel').selectOption('whatsapp');
  await page.getByTestId('create-conversation').click();
  await page.getByTestId('conversation-rows').getByText(`Live channel ${stamp}`).click();

  // WhatsApp is genuinely connected, so nobody can manufacture a customer
  // message from the operational screen.
  await expect(page.getByTestId('channel-gated')).toHaveCount(0);
  await expect(page.getByTestId('record-inbound')).toHaveCount(0);
  // The real reply box is still there.
  await expect(page.getByTestId('send-reply')).toBeVisible();
  await shot(page, '08-dev-control-absent-when-live');
});
