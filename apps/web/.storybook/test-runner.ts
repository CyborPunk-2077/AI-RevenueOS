import { injectAxe, checkA11y } from 'axe-playwright';
import type { TestRunnerConfig } from '@storybook/test-runner';

/**
 * The automated accessibility gate: every story is rendered in a real browser and
 * scanned with axe. This is what `pnpm --filter @airevenueos/web a11y` runs, and
 * what CI runs.
 *
 * A story that must legitimately skip the scan sets
 * `parameters: { a11y: { disable: true } }` and has to say why in a comment - the
 * escape hatch stays visible in review rather than living in a config file.
 */
const config: TestRunnerConfig = {
  async preVisit(page) {
    await injectAxe(page);
  },
  async postVisit(page, context) {
    const storyContext = await (
      await import('@storybook/test-runner')
    ).getStoryContext(page, context);

    if (storyContext.parameters?.a11y?.disable) return;

    await checkA11y(page, '#storybook-root', {
      detailedReport: true,
      detailedReportOptions: { html: true },
      axeOptions: storyContext.parameters?.a11y?.options,
    });
  },
};

export default config;
