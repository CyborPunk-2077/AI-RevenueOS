import Link from 'next/link';
import { notFound } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { AutoRefresh } from '@/features/crm/auto-refresh';
import { ConversationStatus } from '@/features/crm/conversation-status';
import {
  ConversationThread,
  type ChannelReadiness,
  type ThreadMessage,
} from '@/features/crm/conversation-thread';

export const dynamic = 'force-dynamic';

/** Read from the prospect record, never stored on the conversation. */
interface LeadContext {
  readonly id: string;
  readonly name: string;
  readonly company: string | null;
  readonly phone: string | null;
  readonly email: string | null;
  readonly status: string;
  readonly owner_name: string | null;
}

interface Conversation {
  readonly id: string;
  readonly subject: string | null;
  readonly primary_channel: string;
  readonly status: string;
  readonly contact_id: string | null;
  readonly contact_name: string | null;
  readonly assignee_name: string | null;
  readonly automation_stopped: boolean;
  readonly version: number;
  readonly lead_id: string | null;
  readonly lead: LeadContext | null;
}

export default async function ConversationPage({
  params,
}: {
  params: { conversationId: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<Conversation>(`/conversations/${params.conversationId}`);
  if (!result.ok || !result.data) notFound();
  const conversation = result.data;

  const [threadResult, channelResult] = await Promise.all([
    apiFetch<{ messages: ThreadMessage[] }>(`/conversations/${params.conversationId}/messages`),
    apiFetch<{ channels: ChannelReadiness[] }>('/conversations/channels'),
  ]);
  const messages = threadResult.data?.messages ?? [];
  const channels = channelResult.data?.channels ?? [];

  return (
    <div className="space-y-8">
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/inbox" className="underline">Inbox</Link>
      </nav>

      <section className="space-y-3">
        <h1 className="text-xl font-semibold" data-testid="conversation-subject">
          {conversation.subject ?? '(no subject)'}
        </h1>
        {/* Who this actually is. Read from the matched prospect rather than from
            anything copied into the conversation, so a rename or a reassignment
            on the prospect is true here the moment it happens. */}
        <dl className="grid gap-3 text-sm sm:grid-cols-4" data-testid="conversation-identity">
          <div>
            <dt className="text-muted-foreground">Channel</dt>
            <dd>{conversation.primary_channel}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Customer</dt>
            <dd data-testid="conversation-customer">
              {conversation.lead ? (
                <Link href={`/leads/${conversation.lead.id}`} className="underline">
                  {conversation.lead.name}
                </Link>
              ) : conversation.contact_id && conversation.contact_name ? (
                <Link href={`/contacts/${conversation.contact_id}`} className="underline">
                  {conversation.contact_name}
                </Link>
              ) : (
                <span className="text-muted-foreground">Not matched to anyone yet</span>
              )}
              {conversation.lead?.company ? (
                <span className="block text-xs text-muted-foreground">
                  {conversation.lead.company}
                </span>
              ) : null}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Phone</dt>
            <dd className="tabular" data-testid="conversation-phone">
              {conversation.lead?.phone ?? '—'}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Assigned to</dt>
            <dd data-testid="conversation-owner">
              {/* The thread's own assignee if somebody set one, otherwise the
                  prospect's owner - which is who is actually responsible. */}
              {conversation.assignee_name ?? conversation.lead?.owner_name ?? 'Unassigned'}
            </dd>
          </div>
        </dl>

        <ConversationStatus conversationId={conversation.id} status={conversation.status}
          version={conversation.version} />

        {conversation.automation_stopped ? (
          <p data-testid="automation-stopped" className="text-xs text-muted-foreground">
            Automation is paused on this thread because a human replied.
          </p>
        ) : null}
      </section>

      {/* Inbound messages and status changes arrive from a provider, not from
          this browser, so the screen has to go and look. */}
      <AutoRefresh intervalMs={6000} />

      <ConversationThread conversationId={conversation.id} channel={conversation.primary_channel}
        messages={messages} channels={channels} />
    </div>
  );
}
