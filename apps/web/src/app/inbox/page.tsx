import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewConversationForm } from '@/features/crm/new-conversation-form';
import { PageHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

interface Conversation {
  readonly id: string;
  readonly subject: string | null;
  readonly primary_channel: string;
  readonly status: string;
  readonly contact_name: string | null;
  readonly assignee_name: string | null;
  readonly unread_count: number;
  readonly last_message_at: string | null;
}

interface NamedContact {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
}

interface Channel { readonly channel: string; readonly ready: boolean }

export default async function InboxPage({
  searchParams,
}: {
  searchParams?: { status?: string };
}): Promise<JSX.Element> {
  const status = (searchParams?.status ?? '').trim();
  const query = status ? `&status=${encodeURIComponent(status)}` : '';

  const [inboxResult, contactResult, channelResult] = await Promise.all([
    apiFetch<{ conversations: Conversation[] }>(`/conversations?page_size=50${query}`),
    apiFetch<{ contacts: NamedContact[] }>('/contacts?page_size=200'),
    apiFetch<{ channels: Channel[] }>('/conversations/channels'),
  ]);

  const conversations = inboxResult.data?.conversations ?? [];
  const contacts = (contactResult.data?.contacts ?? []).map((c) => ({
    id: c.id,
    name: `${c.first_name} ${c.last_name ?? ''}`.trim(),
  }));
  const channels = channelResult.data?.channels ?? [];
  const unavailable = channels.filter((c) => !c.ready).map((c) => c.channel);

  return (
    <div className="space-y-8">
      <PageHeader title="Inbox" description="Conversations across every channel. Only your organisation&rsquo;s threads are visible." />

      {unavailable.length > 0 ? (
        <p data-testid="gated-channels" className="rounded border border-dashed p-3 text-sm text-muted-foreground">
          Not configured for sending: <strong>{unavailable.join(', ')}</strong>. Replies on those
          channels are recorded and held as <code>queued</code> until a provider credential exists.
        </p>
      ) : null}

      <nav aria-label="Filter" className="flex gap-2 text-sm">
        {['', 'active', 'resolved', 'archived'].map((value) => (
          <Link key={value || 'all'} href={value ? `/inbox?status=${value}` : '/inbox'}
            aria-current={status === value ? 'page' : undefined}
            className={status === value ? 'rounded border px-3 py-1 font-medium' : 'rounded border px-3 py-1 text-muted-foreground'}>
            {value || 'All'}
          </Link>
        ))}
      </nav>

      <NewConversationForm contacts={contacts} channels={channels} />

      <section aria-labelledby="inbox-list-heading">
        <h2 id="inbox-list-heading" className="sr-only">Conversations</h2>
        {conversations.length === 0 ? (
          <p data-testid="inbox-empty" className="surface border-dashed p-6 text-center text-sm text-muted-foreground">
            No conversations yet. Open one above.
          </p>
        ) : (
          <ul className="divide-y" data-testid="conversation-rows">
            {conversations.map((conversation) => (
              <li key={conversation.id} className="flex items-center justify-between gap-4 py-3 text-sm">
                <div>
                  <Link href={`/inbox/${conversation.id}`} data-testid={`conversation-link-${conversation.id}`}
                    className="font-medium underline">
                    {conversation.subject ?? '(no subject)'}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {conversation.primary_channel}
                    {conversation.contact_name ? ` · ${conversation.contact_name}` : ''}
                    {conversation.assignee_name ? ` · ${conversation.assignee_name}` : ''}
                  </p>
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  <span className="rounded bg-muted px-2 py-0.5 uppercase">{conversation.status}</span>
                  {conversation.unread_count > 0 ? (
                    <span data-testid={`unread-${conversation.id}`} className="ml-2 font-medium text-foreground">
                      {conversation.unread_count} unread
                    </span>
                  ) : null}
                  {conversation.last_message_at ? (
                    <p className="mt-1">{new Date(conversation.last_message_at).toLocaleString()}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
