import { defineConfig } from '@playwright/test';

/**
 * Assumes the stack is already running. On Windows that is `RUN_DEMO.cmd`.
 *
 * Playwright deliberately does not start the API, the database or the workers: a
 * browser test that boots its own backend proves the backend it booted works, not
 * the one the launcher produces, and hides exactly the integration problems this
 * suite exists to catch.
 *
 * Two things must be supplied by the caller:
 *   DEMO_PASSWORD  the password the launcher printed. Start the stack with an
 *                  explicit one (`.\scripts\demo.ps1 -Password '...'`) so both
 *                  halves agree; the launcher otherwise generates a fresh one
 *                  each run and stores it nowhere.
 *   browsers       `pnpm --filter @airevenueos/web exec playwright install chromium`
 */
export default defineConfig({
  testDir: './e2e',
  // A cold Next dev server compiles the route on first request.
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.DEMO_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: process.env.PLAYWRIGHT_START_WEB
    ? { command: 'npm run dev', url: 'http://localhost:3000', reuseExistingServer: true }
    : undefined,
});
