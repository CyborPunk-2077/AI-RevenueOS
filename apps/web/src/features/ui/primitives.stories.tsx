import type { Meta, StoryObj } from '@storybook/react';

import { Card, EmptyState, ListSkeleton, PageHeader, Stat, StatusPill } from './primitives';

/**
 * The design system, on one page. If a contrast or labelling regression lands,
 * it fails here first rather than in whichever feature happened to import it.
 */
const meta = {
  title: 'Design System/Primitives',
  parameters: { layout: 'padded' },
} satisfies Meta;

export default meta;
type Story = StoryObj;

export const Statuses: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <StatusPill tone="neutral">Draft</StatusPill>
      <StatusPill tone="success">Won</StatusPill>
      <StatusPill tone="warning">At risk</StatusPill>
      <StatusPill tone="danger">Overdue</StatusPill>
    </div>
  ),
};

export const Metrics: Story = {
  render: () => (
    <div className="grid gap-4 sm:grid-cols-3">
      <Stat label="Pipeline" value="₹1.45 Cr" delta={{ value: '+12%', direction: 'up' }} />
      <Stat label="Won this month" value="₹22.8 L" delta={{ value: '-4%', direction: 'down' }} />
      <Stat label="Open leads" value="318" hint="42 unassigned" />
    </div>
  ),
};

export const Surfaces: Story = {
  render: () => (
    <div className="grid gap-4 sm:grid-cols-2">
      <Card>
        <p className="heading text-sm">Static panel</p>
        <p className="mt-1 text-sm text-muted-foreground">No hover affordance.</p>
      </Card>
      <Card interactive>
        <p className="heading text-sm">Interactive panel</p>
        <p className="mt-1 text-sm text-muted-foreground">Lifts on hover, settles on press.</p>
      </Card>
    </div>
  ),
};

export const Loading: Story = { render: () => <ListSkeleton rows={4} /> };

export const Empty: Story = {
  render: () => (
    <EmptyState
      title="No leads yet"
      description="Import a CSV or publish a capture form, and new leads will appear here."
    />
  ),
};

export const Header: Story = {
  render: () => (
    <PageHeader
      title="Leads"
      description="Only your organisation's records are visible here."
      actions={
        <button type="button" className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
          New lead
        </button>
      }
    />
  ),
};
