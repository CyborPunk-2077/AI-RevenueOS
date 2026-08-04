import type { Meta, StoryObj } from '@storybook/react';

import { Timeline, type TimelineEntry } from './timeline';

const entries: TimelineEntry[] = [
  {
    kind: 'note',
    id: 'note-1',
    body: 'Asked for a revised quote excluding onboarding.',
    actor_name: 'Asha Menon',
    editable: true,
    is_pinned: true,
    version: 2,
    created_at: '2026-08-03T14:05:00+05:30',
  },
  {
    kind: 'activity',
    id: 'act-1',
    activity_type: 'call',
    subject: 'Discovery call',
    body: 'Twenty minutes. Budget approved, timeline unclear.',
    actor_name: 'Rahul Nair',
    editable: false,
    created_at: '2026-08-02T11:20:00+05:30',
  },
  {
    kind: 'activity',
    id: 'act-2',
    activity_type: 'email',
    subject: 'Intro from the website form',
    body: null,
    actor_name: null,
    editable: false,
    created_at: '2026-08-01T09:00:00+05:30',
  },
];

/**
 * Activity and note history for one record.
 *
 * `editable` is server-decided. The read-only story exists to prove the edit
 * affordance disappears rather than being disabled-but-focusable, which screen
 * reader users would otherwise land on for no reason.
 */
const meta = {
  title: 'CRM/Timeline',
  component: Timeline,
  parameters: { layout: 'padded' },
  args: { parent: 'contacts' as const, parentId: 'contact-1' },
} satisfies Meta<typeof Timeline>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Mixed: Story = {
  args: { entries },
};

export const ReadOnly: Story = {
  args: { entries: entries.map((entry) => ({ ...entry, editable: false })) },
};

export const Empty: Story = {
  args: { entries: [] },
};
