import { defineConfig } from '@playwright/test';

/**
 * Assumes the stack is already running (`make demo` in one terminal).
 * Playwright does not start the API or the database; a browser test that boots
 * its own backend hides integration problems rather than catching them.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.DEMO_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: process.env.PLAYWRIGHT_START_WEB
    ? { command: 'npm run dev', url: 'http://localhost:3000', reuseExistingServer: true }
    : undefined,
});
