import { apiFetch } from '@/lib/session';
import { AutoRefresh } from '@/features/crm/auto-refresh';
import {
  ConversationFilters,
  ConversationList,
  type ConversationSummary,
} from '@/features/crm/conversation-list';
import { NewConversationForm } from '@/features/crm/new-conversation-form';
import { PageHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

interface NamedContact {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
}

interface Channel {
  readonly channel: string;
  readonly ready: boolean;
}

/**
 * Communications operations, not a messaging app.
 *
 * Two panes above 1100px: the conversation list on the left and the transcript
 * on the right, which is the shape somebody works a queue in. Below that they
 * are separate routes, as they always were.
 */
export default async function InboxPage({
  searchParams,
}: {
  searchParams?: { status?: string };
}): Promise<JSX.Element> {
  const status = (searchParams?.status ?? '').trim();
  const query = status ? `&status=${encodeURIComponent(status)}` : '';

  const [inboxResult, contactResult, channelResult] = await Promise.all([
    apiFetch<{ conversations: ConversationSummary[]; status_counts: Record<string, number> }>(
      `/conversations?page_size=50${query}`,
    ),
    apiFetch<{ contacts: NamedContact[] }>('/contacts?page_size=200'),
    apiFetch<{ channels: Channel[] }>('/conversations/channels'),
  ]);

  const conversations = inboxResult.data?.conversations ?? [];
  const counts = inboxResult.data?.status_counts ?? {};
  const totalEverywhere = counts.all ?? 0;
  const contacts = (contactResult.data?.contacts ?? []).map((c) => ({
    id: c.id,
    name: `${c.first_name} ${c.last_name ?? ''}`.trim(),
  }));
  const channels = channelResult.data?.channels ?? [];
  const unavailable = channels.filter((c) => !c.ready).map((c) => c.channel);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Inbox"
        description="Conversations across every channel. Only your organisation’s threads are visible."
        actions={<NewConversationForm contacts={contacts} channels={channels} />}
      />

      {/*
        Which channels genuinely cannot send. Stated once, at the top, rather
        than discovered when a reply silently fails to arrive.
      */}
      {unavailable.length > 0 ? (
        <p data-testid="gated-channels" className="max-w-reading text-[13px] text-muted-foreground">
          Not configured for sending: <strong className="text-foreground">{unavailable.join(', ')}</strong>.
          Replies on those channels are recorded and held as <code>queued</code> until a provider
          credential exists.
        </p>
      ) : null}

      {/* New threads arrive from providers, so the list has to go and look. */}
      <AutoRefresh intervalMs={10000} />

      <section aria-labelledby="inbox-list-heading">
        <h2 id="inbox-list-heading" className="sr-only">
          Conversations
        </h2>

        <div className="overflow-hidden rounded-lg border border-border bg-surface min-[1100px]:flex min-[1100px]:items-stretch">
          <div className="min-[1100px]:w-[22.5rem] min-[1100px]:shrink-0 min-[1100px]:border-r min-[1100px]:border-border">
            <div className="border-b border-border bg-surface-sunken px-4 py-1.5">
              <ConversationFilters status={status} counts={counts} />
            </div>
            <ConversationList
              conversations={conversations}
              totalEverywhere={totalEverywhere}
              status={status}
            />
          </div>

          {/*
            The transcript pane, empty until a conversation is chosen. Above
            1100px the shape of the screen stays the same whether or not one is
            open, which is what makes working down a queue feel continuous.
          */}
          <div className="hidden flex-1 items-center justify-center p-10 text-center min-[1100px]:flex">
            <p className="max-w-reading text-sm text-muted-foreground">
              {conversations.length > 0
                ? 'Choose a conversation to read it and reply.'
                : 'Conversations opened by a customer, or by you, appear here.'}
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
