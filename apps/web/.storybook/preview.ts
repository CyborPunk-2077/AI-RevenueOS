import type { Preview } from '@storybook/react';

import '../src/app/globals.css';

/**
 * Accessibility is configured to fail rather than warn.
 *
 * `element: '#storybook-root'` scopes axe to the rendered story: the Storybook
 * chrome is not the product and its violations would drown out real ones. The
 * WCAG 2.1 AA tag set matches the level the specification commits to.
 */
const preview: Preview = {
  parameters: {
    controls: { expanded: true },
    a11y: {
      element: '#storybook-root',
      config: {
        rules: [
          // Colour contrast needs real layout and computed styles, which the
          // browser gives us here. Left on deliberately - it is the check most
          // often disabled and the one users notice most.
          { id: 'color-contrast', enabled: true },
        ],
      },
      options: {
        runOnly: {
          type: 'tag',
          values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
        },
      },
    },
    nextjs: {
      appDirectory: true,
    },
  },
  tags: ['autodocs'],
};

export default preview;
