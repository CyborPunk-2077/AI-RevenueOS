import Link from 'next/link';
import { notFound } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { AutoRefresh } from '@/features/crm/auto-refresh';
import {
  ConversationFilters,
  ConversationList,
  type ConversationSummary,
} from '@/features/crm/conversation-list';
import { ConversationStatus } from '@/features/crm/conversation-status';
import {
  ConversationThread,
  type ChannelReadiness,
  type ThreadMessage,
} from '@/features/crm/conversation-thread';
import { Avatar } from '@/features/ui/avatar';
import { ChannelIcon, channelLabel } from '@/features/ui/channel-icon';
import { StatusText } from '@/features/ui/status';

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

  const [threadResult, channelResult, listResult] = await Promise.all([
    apiFetch<{ messages: ThreadMessage[] }>(`/conversations/${params.conversationId}/messages`),
    apiFetch<{ channels: ChannelReadiness[] }>('/conversations/channels'),
    // The list beside the transcript, so working a queue does not mean going
    // back to a different page between every conversation.
    apiFetch<{ conversations: ConversationSummary[]; status_counts: Record<string, number> }>(
      '/conversations?page_size=50',
    ),
  ]);
  const messages = threadResult.data?.messages ?? [];
  const channels = channelResult.data?.channels ?? [];
  const conversations = listResult.data?.conversations ?? [];
  const counts = listResult.data?.status_counts ?? {};

  const lead = conversation.lead;
  const business = lead?.company ?? lead?.name ?? conversation.contact_name ?? null;
  const contact = lead?.company && lead.name !== lead.company ? lead.name : null;
  // The thread's own assignee if somebody set one, otherwise the prospect's
  // owner - which is who is actually responsible.
  const owner = conversation.assignee_name ?? lead?.owner_name ?? null;

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="text-[13px]">
        <Link href="/inbox" className="text-muted-foreground underline-offset-2 hover:underline">
          &larr; Inbox
        </Link>
      </nav>

      {/* Inbound messages and status changes arrive from a provider, not from
          this browser, so the screen has to go and look. */}
      <AutoRefresh intervalMs={6000} />

      {/*
        A workspace, not a document.

        The transcript scrolls inside its own pane and the composer sits at the
        bottom of it, which is only true if the panel has a height of its own -
        so on a desktop it takes the viewport minus the chrome above it. Left as
        an ordinary block the page scrolled instead: the composer sat below the
        fold on any conversation longer than a screen, and answering a customer
        began by scrolling past their entire history to find the box.

        Below 1100px it flows normally again, because a 700px-tall pane inside a
        720px window is worse than a page that simply scrolls.
      */}
      <div className="overflow-hidden rounded-lg border border-border bg-surface min-[1100px]:flex min-[1100px]:h-[calc(100vh-var(--utility-bar-height)-7.5rem)] min-[1100px]:items-stretch">
        <div className="hidden min-[1100px]:flex min-[1100px]:w-[21rem] min-[1100px]:shrink-0 min-[1100px]:flex-col min-[1100px]:border-r min-[1100px]:border-border min-[1400px]:w-[24rem]">
          <div className="shrink-0 border-b border-border bg-surface-sunken px-4 py-1.5">
            <ConversationFilters status="" counts={counts} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ConversationList
              conversations={conversations}
              activeId={conversation.id}
              totalEverywhere={counts.all ?? 0}
              status=""
            />
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          {/*
            The customer, above the transcript. Read from the matched prospect
            rather than from anything copied onto the conversation, so a rename
            or a reassignment on the prospect is true here the moment it happens.
          */}
          <header className="shrink-0 border-b border-border px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-2.5">
                <Avatar name={business ?? 'Unmatched'} size="lg" className="mt-0.5" />
                <div className="min-w-0">
                  <h1
                    className="truncate text-lg font-semibold text-foreground"
                    data-testid="conversation-subject"
                  >
                    {conversation.subject ?? '(no subject)'}
                  </h1>
                  <dl
                    className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[13px]"
                    data-testid="conversation-identity"
                  >
                    <div className="flex items-baseline gap-1.5">
                      <dt className="text-muted-foreground">Customer</dt>
                      <dd data-testid="conversation-customer" className="text-foreground">
                        {lead ? (
                          <Link
                            href={`/leads/${lead.id}`}
                            className="text-accent underline-offset-2 hover:underline"
                          >
                            {business}
                          </Link>
                        ) : conversation.contact_id && conversation.contact_name ? (
                          <Link
                            href={`/contacts/${conversation.contact_id}`}
                            className="text-accent underline-offset-2 hover:underline"
                          >
                            {conversation.contact_name}
                          </Link>
                        ) : (
                          <span className="text-muted-foreground">Not matched to anyone yet</span>
                        )}
                      </dd>
                    </div>
                    {contact ? (
                      <div className="flex items-baseline gap-1.5">
                        <dt className="text-muted-foreground">Contact</dt>
                        <dd className="text-foreground">{contact}</dd>
                      </div>
                    ) : null}
                    <div className="flex items-baseline gap-1.5">
                      <dt className="text-muted-foreground">Phone</dt>
                      <dd className="tabular text-foreground" data-testid="conversation-phone">
                        {lead?.phone ?? '—'}
                      </dd>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <dt className="text-muted-foreground">Assigned to</dt>
                      <dd data-testid="conversation-owner" className="text-foreground">
                        {owner ?? <StatusText tone="critical">Unassigned</StatusText>}
                      </dd>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <dt className="text-muted-foreground">Channel</dt>
                      <dd className="flex items-center gap-1.5 text-foreground">
                        <ChannelIcon channel={conversation.primary_channel} size={14} />
                        {channelLabel(conversation.primary_channel)}
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>

              <ConversationStatus
                conversationId={conversation.id}
                status={conversation.status}
                version={conversation.version}
              />
            </div>

            {conversation.automation_stopped ? (
              <p data-testid="automation-stopped" className="mt-2 text-[13px] text-muted-foreground">
                Automation is paused on this thread because a human replied.
              </p>
            ) : null}
          </header>

          <ConversationThread
            conversationId={conversation.id}
            channel={conversation.primary_channel}
            messages={messages}
            channels={channels}
          />
        </div>
      </div>
    </div>
  );
}
