import type { Meta, StoryObj } from '@storybook/react';

import { WidgetSettingsForm } from './widget-settings-form';

/**
 * The unconfigured state is the one that matters: it is what every tenant sees
 * first, and it has to explain why the activation checkbox is disabled rather
 * than just disabling it.
 */
const meta = {
  title: 'Webchat/WidgetSettingsForm',
  component: WidgetSettingsForm,
  parameters: { layout: 'padded' },
} satisfies Meta<typeof WidgetSettingsForm>;

export default meta;
type Story = StoryObj<typeof meta>;

export const NotConfigured: Story = { args: { widget: null } };

export const Configured: Story = {
  args: {
    widget: {
      public_key: 'wck_2f8a1c4e9b7d3a6f5e2c8b1d4a7f0e3c',
      allowed_origins: ['https://sharma-textiles.in'],
      greeting: 'How can we help?',
      consent_copy: 'We store this chat to answer your question.',
      handoff_enabled: true,
      is_active: true,
    },
  },
};

export const SavedButNotLive: Story = {
  args: {
    widget: {
      public_key: 'wck_2f8a1c4e9b7d3a6f5e2c8b1d4a7f0e3c',
      allowed_origins: [],
      greeting: 'How can we help?',
      consent_copy: '',
      handoff_enabled: true,
      is_active: false,
    },
  },
};
