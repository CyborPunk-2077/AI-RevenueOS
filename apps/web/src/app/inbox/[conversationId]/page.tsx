import Link from 'next/link';
import { notFound } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { ConversationStatus } from '@/features/crm/conversation-status';
import {
  ConversationThread,
  type ChannelReadiness,
  type ThreadMessage,
} from '@/features/crm/conversation-thread';

export const dynamic = 'force-dynamic';

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
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">Channel</dt>
            <dd>{conversation.primary_channel}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Contact</dt>
            <dd>
              {conversation.contact_id && conversation.contact_name ? (
                <Link href={`/contacts/${conversation.contact_id}`} className="underline">
                  {conversation.contact_name}
                </Link>
              ) : ('—')}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Assigned to</dt>
            <dd>{conversation.assignee_name ?? 'Unassigned'}</dd>
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

      <ConversationThread conversationId={conversation.id} channel={conversation.primary_channel}
        messages={messages} channels={channels} />
    </div>
  );
}
