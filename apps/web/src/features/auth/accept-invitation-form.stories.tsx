import type { Meta, StoryObj } from '@storybook/react';

import { AcceptInvitationForm } from './accept-invitation-form';

/**
 * The email is displayed rather than editable: the link was issued to one
 * address, and letting a recipient change it turns a forwarded invitation into
 * an account for whoever received the forward.
 */
const meta = {
  title: 'Auth/AcceptInvitationForm',
  component: AcceptInvitationForm,
  parameters: { layout: 'centered' },
  args: {
    token: 'demo-token',
    preview: {
      email: 'asha@example.in',
      role: 'manager',
      organisation: 'Sharma Textiles',
      tenant_slug: 'sharma-textiles',
      expires_at: '2026-08-11T09:00:00+05:30',
    },
  },
} satisfies Meta<typeof AcceptInvitationForm>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Invited: Story = {};

export const WithoutAnOrganisationName: Story = {
  args: {
    preview: {
      email: 'asha@example.in',
      role: null,
      organisation: null,
      tenant_slug: null,
      expires_at: '2026-08-11T09:00:00+05:30',
    },
  },
};
