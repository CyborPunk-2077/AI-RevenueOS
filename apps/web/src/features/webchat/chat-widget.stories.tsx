import type { Meta, StoryObj } from '@storybook/react';

import { ChatWidget, type ChatMessage } from './chat-widget';

const messages: ChatMessage[] = [
  {
    id: '1',
    author: 'you',
    content: 'Do you ship to Pune?',
    created_at: '2026-08-04T10:00:00+05:30',
  },
  {
    id: '2',
    author: 'agent',
    content: 'We do - next-day for orders before 4pm.',
    created_at: '2026-08-04T10:01:00+05:30',
  },
];

/**
 * The visitor-facing panel. The states worth reviewing are the ones a happy-path
 * demo skips: an empty conversation, a consent prompt nobody has ticked, and a
 * session that has ended under the visitor.
 */
const meta = {
  title: 'Webchat/ChatWidget',
  component: ChatWidget,
  parameters: { layout: 'centered' },
  args: {
    greeting: 'How can we help?',
    consentCopy: 'We store this chat to answer your question.',
    messages,
    onSend: async () => undefined,
    onConsent: () => undefined,
  },
} satisfies Meta<typeof ChatWidget>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Conversation: Story = {};

export const Empty: Story = { args: { messages: [] } };

export const AwaitingConsent: Story = { args: { messages: [], consentGranted: false } };

export const Connecting: Story = { args: { messages: [], state: 'connecting' } };

export const Ended: Story = { args: { state: 'ended' } };

export const Unavailable: Story = { args: { state: 'unavailable', messages: [] } };
