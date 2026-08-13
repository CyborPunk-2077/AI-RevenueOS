import { expect, type Browser, type Page } from '@playwright/test';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * One sign-in per account per machine, not one per test.
 *
 * Two production limiters govern this, and neither is disabled, raised or
 * bypassed. Both are keyed on the caller's IP address, and every browser request
 * arrives from the same place - the BFF container - so the whole suite shares one
 * budget with anybody else using the app:
 *
 *   sign in   5 per 15 minutes   the six suites need six accounts, which is
 *                                already more than one window allows
 *   refresh  10 per 60 seconds   rotating a session is not free either
 *
 * So sessions are established once, in `global-setup.ts`, kept in `e2e/.auth/`,
 * and afterwards **adopted rather than renewed**. An access token lives fifteen
 * minutes; while the stored one is still good it is simply used, exactly as a
 * browser would. Only when it has gone stale is a rotation spent - roughly one
 * per account per quarter of an hour, which sits far inside both budgets.
 *
 * Forcing a rotation per test instead of this looked tidier and cost the suite
 * every test after the tenth: `/auth/refresh` answered 429, the proxy passed the
 * request on with no credential, and the API answered 401. The failure named the
 * session rather than the limiter, which is why it is written down here.
 *
 * Rotation is single use: presenting an already-rotated refresh token is replay
 * and correctly kills the whole family. So whenever one is spent, the new pair is
 * written straight back to the state file.
 */

const AUTH_DIR = resolve(__dirname, '../.auth');

/** Accounts the browser suites sign in as. */
export const ACCOUNTS = {
  'e2e-owner': 'owner@sangam-e2e.test',
  'e2e-rep': 'rep@sangam-e2e.test',
  'pilot-owner': 'owner@pilot-e2e.test',
  'pilot-manager': 'manager@pilot-e2e.test',
  'pilot-sales': 'sales@pilot-e2e.test',
  founder: 'abhishek@sangam.co.in',
} as const;

export type AccountName = keyof typeof ACCOUNTS;

export const PASSWORD = process.env.DEMO_PASSWORD ?? 'sangam-demo-2026';

/** Renew with this much of the access token's life left, rather than at zero. */
const RENEW_WITHIN_SECONDS = 120;

interface StoredCookie {
  name: string;
  expires: number;
}

export function statePath(account: AccountName): string {
  mkdirSync(AUTH_DIR, { recursive: true });
  return resolve(AUTH_DIR, `${account}.json`);
}

function readStored(account: AccountName): { cookies: StoredCookie[] } | null {
  const path = statePath(account);
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf8')) as { cookies: StoredCookie[] };
  } catch {
    return null;
  }
}

const isAccessCookie = (cookie: StoredCookie): boolean => cookie.name.endsWith('airev-access');

/** Has the stored access token got enough life left to be used as it is? */
function accessTokenIsFresh(cookies: StoredCookie[]): boolean {
  const access = cookies.find(isAccessCookie);
  if (!access || access.expires <= 0) return false;
  return access.expires - Date.now() / 1000 > RENEW_WITHIN_SECONDS;
}

/**
 * Adopt an account's stored session and land on Today.
 *
 * A drop-in replacement for signing in through the form: it leaves the page in
 * exactly the state the old `signIn()` helper did, and normally spends nothing at
 * all.
 */
export async function signInAs(page: Page, account: AccountName): Promise<void> {
  const stored = readStored(account);
  expect(
    stored,
    `no stored session for ${ACCOUNTS[account]}. Global setup establishes them, so ` +
      `this means it did not run - check the playwright config.`,
  ).not.toBeNull();

  const context = page.context();
  await context.clearCookies();

  if (accessTokenIsFresh(stored!.cookies)) {
    await context.addCookies(stored!.cookies as never);
  } else {
    // Without the access cookie the proxy is obliged to rotate, which is the one
    // path that mints a new one. Spent deliberately and only when needed.
    await context.addCookies(stored!.cookies.filter((c) => !isAccessCookie(c)) as never);
    const renewed = await page.goto('/api/leads?page_size=1');
    expect(
      renewed?.status(),
      `could not renew the stored session for ${ACCOUNTS[account]}. If this is a 401 ` +
        `the session has genuinely expired: delete apps/web/e2e/.auth and run again ` +
        `to sign in once more. If the API was restarting - it reloads on any edit ` +
        `under backend/ - simply run again.`,
    ).toBe(200);
    await context.storageState({ path: statePath(account) });
  }

  await page.goto('/today');
  await expect(page).toHaveURL(/\/today/);
}

/**
 * Sign in through the form, waiting out the rate limiter rather than evading it.
 *
 * The only place in the browser suites that spends a login attempt. Used by
 * global setup, on a cold machine or once a stored session is seven days old.
 */
export async function signInFresh(
  browser: Browser,
  baseURL: string,
  account: AccountName,
  log: (message: string) => void,
): Promise<void> {
  const email = ACCOUNTS[account];
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();
  const deadline = Date.now() + 16 * 60_000;

  try {
    for (;;) {
      await page.goto('/login');
      await page.getByLabel('Email').fill(email);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByTestId('sign-in').click();

      const signedIn = await page
        .waitForURL('**/today', { timeout: 60_000 })
        .then(() => true)
        .catch(() => false);

      if (signedIn) {
        await context.storageState({ path: statePath(account) });
        log(`signed in as ${email}`);
        return;
      }

      // Whatever the form is showing instead. Read rather than raced against the
      // navigation: racing let an empty alert win instantly and reported "never
      // reached /today" for every cause alike.
      const message = await page
        .getByRole('alert')
        .first()
        .innerText()
        .catch(() => '');

      if (/too many attempts/i.test(message)) {
        if (Date.now() > deadline) {
          throw new Error(
            `the login limiter refused ${email} for a full window. Nothing is wrong ` +
              `with the suite; something else is signing in from this machine.`,
          );
        }
        log(
          `rate limited signing in as ${email} (5 per IP per 15 minutes, deliberately ` +
            `left in place). Waiting 30s and trying again.`,
        );
        await page.waitForTimeout(30_000);
        continue;
      }

      throw new Error(
        `could not sign in as ${email}: ${message || 'the page never reached /today'}. ` +
          `Check that the stack is running and that DEMO_PASSWORD matches the one it ` +
          `was started with.`,
      );
    }
  } finally {
    await context.close();
  }
}

/**
 * Make sure this account has a usable session, spending as little as possible.
 *
 * A stored session whose access token is still fresh is taken at its word: proving
 * it works would cost a rotation, and six accounts proving themselves at once is
 * most of the per-minute refresh budget for no benefit.
 */
export async function ensureSession(
  browser: Browser,
  baseURL: string,
  account: AccountName,
  log: (message: string) => void,
): Promise<void> {
  const stored = readStored(account);

  if (stored && accessTokenIsFresh(stored.cookies)) {
    log(`stored session for ${ACCOUNTS[account]} is still current - nothing spent`);
    return;
  }

  if (stored) {
    const context = await browser.newContext({
      baseURL,
      storageState: { cookies: stored.cookies.filter((c) => !isAccessCookie(c)), origins: [] } as never,
    });
    try {
      const page = await context.newPage();
      const renewed = await page.goto('/api/leads?page_size=1');
      if (renewed?.status() === 200) {
        await context.storageState({ path: statePath(account) });
        log(`renewed the stored session for ${ACCOUNTS[account]} - no login attempt spent`);
        return;
      }
    } catch {
      // Fall through to a real sign-in.
    } finally {
      await context.close();
    }
  }

  await signInFresh(browser, baseURL, account, log);
}
