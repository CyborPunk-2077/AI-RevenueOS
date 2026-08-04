import type { Meta, StoryObj } from '@storybook/react';

import { DegradedState } from './degraded-state';

/**
 * The AI degradation notice. ADR 0005 requires every AI surface to offer a manual
 * path when the model is unavailable, so the interesting states here are the
 * failure ones, not the happy one.
 */
const meta = {
  title: 'AI/DegradedState',
  component: DegradedState,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof DegradedState>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ProviderUnavailable: Story = {
  args: {
    reason: 'provider_unavailable',
    manualPath: 'Score this lead yourself using the qualification checklist.',
  },
};

export const WithManualAction: Story = {
  args: {
    reason: 'budget_exhausted',
    manualPath: 'The monthly AI budget is spent. Qualification continues by rule.',
    manualActionLabel: 'Qualify manually',
    onManualAction: () => undefined,
  },
};

export const NoReasonRendersNothing: Story = {
  args: { reason: null, manualPath: null },
};
