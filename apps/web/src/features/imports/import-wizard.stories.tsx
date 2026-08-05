import type { Meta, StoryObj } from '@storybook/react';

import { ImportWizard } from './import-wizard';

/**
 * The wizard drives itself from the API, so these stories cover the shell and
 * the first step. The states that matter most - mapping and rejection review -
 * are exercised end to end by the Playwright spec against
 * backend/tests/fixtures/leads_messy_2000.csv, where the expected answer is
 * exactly 1648 accepted and 352 rejected.
 */
const meta = {
  title: 'Imports/ImportWizard',
  component: ImportWizard,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof ImportWizard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ChooseFile: Story = {};
