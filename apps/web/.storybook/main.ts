import { fileURLToPath } from 'node:url';

import type { StorybookConfig } from '@storybook/nextjs';

/**
 * The component surface P2-8 requires. `@storybook/nextjs` is used rather than the
 * plain React builder because these components import `next/navigation`,
 * `next/link` and the App Router's font and image handling; the React builder
 * would need those stubbed by hand in every story.
 */
const config: StorybookConfig = {
  stories: ['../src/**/*.mdx', '../src/**/*.stories.@(ts|tsx)'],
  addons: [
    '@storybook/addon-essentials',
    '@storybook/addon-interactions',
    // Runs axe in the browser for the focused story and reports violations in the
    // addon panel. The CI gate is the test runner in `.storybook/test-runner.ts`;
    // this panel is what makes a violation cheap to reproduce and fix.
    '@storybook/addon-a11y',
  ],
  framework: {
    name: '@storybook/nextjs',
    options: {},
  },
  typescript: {
    // The project already type-checks with `tsc --noEmit` under `strict`. Repeating
    // it in the Storybook build only slows the build and duplicates failures.
    check: false,
    reactDocgen: 'react-docgen-typescript',
  },
  docs: {
    autodocs: 'tag',
  },
  webpackFinal: async (webpackConfig) => {
    webpackConfig.resolve = webpackConfig.resolve ?? {};
    webpackConfig.resolve.alias = {
      ...(webpackConfig.resolve.alias ?? {}),
      '@': fileURLToPath(new URL('../src', import.meta.url)),
    };
    return webpackConfig;
  },
};

export default config;
