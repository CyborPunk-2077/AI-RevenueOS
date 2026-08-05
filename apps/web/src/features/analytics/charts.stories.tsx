import type { Meta, StoryObj } from '@storybook/react';

import { LeadSourceMix, PipelineByStage, WonOverTime } from './charts';

/**
 * Each story is checked in both modes by the a11y gate. The one that matters is
 * Empty: a chart with no data must say so rather than rendering an axis with
 * nothing on it, which reads as a broken page.
 */
const meta = {
  title: 'Analytics/Charts',
  parameters: { layout: 'padded' },
} satisfies Meta;

export default meta;
type Story = StoryObj;

const sources = [
  { label: 'Web form', value: 412 },
  { label: 'Referral', value: 188 },
  { label: 'Trade show', value: 96 },
  { label: 'Google ads', value: 61 },
];

const daily = Array.from({ length: 14 }, (_, index) => ({
  label: `08-${String(index + 1).padStart(2, '0')}`,
  value: Math.round(200000 + Math.sin(index / 2) * 120000 + index * 9000),
}));

export const Sources: Story = { render: () => <LeadSourceMix rows={sources} /> };

export const Pipeline: Story = {
  render: () => (
    <PipelineByStage
      rows={[
        { label: 'Open pipeline', value: 14500000 },
        { label: 'Won', value: 2280000 },
        { label: 'Captured', value: 1910000 },
      ]}
    />
  ),
};

export const Trend: Story = { render: () => <WonOverTime rows={daily} /> };

export const Empty: Story = { render: () => <LeadSourceMix rows={[]} /> };
