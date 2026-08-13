import { chromium, type FullConfig } from '@playwright/test';

import { ACCOUNTS, ensureSession, type AccountName } from './auth';

/**
 * Establish one usable session per account, before any spec runs.
 *
 * This is the only place in the browser suites that may sign in, and it does so
 * as rarely as it can: a stored session is renewed rather than replaced, and a
 * still-current one is left alone entirely. The steady-state cost of a full
 * six-suite run is nothing; a cold machine pays one sign-in per account.
 *
 * Six accounts is more than the five sign-ins the limiter allows in a window, so
 * on a cold machine the sixth is genuinely refused - and the honest response to
 * being rate limited is to wait for the window, which is what happens. Slow once,
 * free afterwards. The limiter is production behaviour and is left exactly as it
 * is.
 */

function log(message: string): void {
  process.stdout.write(`[auth] ${message}\n`);
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL =
    (config.projects[0]?.use?.baseURL as string | undefined) ??
    process.env.DEMO_URL ??
    'http://localhost:3000';
  const browser = await chromium.launch();

  try {
    for (const account of Object.keys(ACCOUNTS) as AccountName[]) {
      await ensureSession(browser, baseURL, account, log);
    }
  } finally {
    await browser.close();
  }
}
