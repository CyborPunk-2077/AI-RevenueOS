import type { Meta, StoryObj } from '@storybook/react';

import { InvitationList, type InvitationRow } from './invitation-list';

const invitations: InvitationRow[] = [
  {
    id: '1',
    email: 'asha@example.in',
    role: 'manager',
    expires_at: '2026-08-11T09:00:00+05:30',
    status: 'pending',
  },
  {
    id: '2',
    email: 'rahul@example.in',
    role: 'member',
    expires_at: '2026-08-02T09:00:00+05:30',
    status: 'expired',
  },
  {
    id: '3',
    email: 'priya@example.in',
    role: 'viewer',
    expires_at: '2026-08-09T09:00:00+05:30',
    status: 'accepted',
  },
];

/**
 * Status is text, not colour. "Expired" in red and "Pending" in amber read
 * identically to someone who cannot tell them apart.
 */
const meta = {
  title: 'Tenants/InvitationList',
  component: InvitationList,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof InvitationList>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Mixed: Story = { args: { invitations } };

export const OnlyPending: Story = {
  args: { invitations: invitations.filter((row) => row.status === 'pending') },
};

export const Empty: Story = { args: { invitations: [] } };
