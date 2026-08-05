import type { Meta, StoryObj } from '@storybook/react';

import { AssignmentRules, type AssignmentRule } from './assignment-rules';

const rules: AssignmentRule[] = [
  {
    id: 'r1',
    name: 'Website leads to the inbound pod',
    strategy: 'round_robin',
    conditions: { all: [{ field: 'source', operator: 'equals', value: 'web_form' }] },
    targets: ['a', 'b'],
    position: 0,
    is_active: true,
    version: 1,
  },
  {
    id: 'r2',
    name: 'Everything else',
    strategy: 'load_balanced',
    conditions: {},
    targets: ['c'],
    position: 1,
    is_active: false,
    version: 1,
  },
];

const meta = {
  title: 'Leads/AssignmentRules',
  component: AssignmentRules,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof AssignmentRules>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Ordered: Story = { args: { rules } };

export const NoRules: Story = { args: { rules: [] } };
