import Link from 'next/link';
import { Avatar } from '@/features/ui/avatar';
import { ChannelIcon } from '@/features/ui/channel-icon';
import { cn } from '@/features/ui/cn';
import { FilterLinks, type FilterLink } from '@/features/ui/toolbar';
import { formatDateTime } from '@/lib/dates';

/**
 * The conversation list, shared by the Inbox route and the thread route.
 *
 * One component, because at desktop width the thread page shows the list beside
 * the transcript, and a second copy of these rows is how the two would end up
 * disagreeing about which conversation is selected.
 *
 * **Not a WhatsApp clone.** No wallpaper, no balloons, no brand colours on the
 * channel glyph. A row has to make seven facts separable at a glance - business,
 * contact, channel, owner, unread, subject and time - and that is a density
 * problem, not a styling one.
 *
 * There is deliberately no message preview. The conversations endpoint returns
 * no last-message text, and inventing one by fetching every thread would be
 * fifty requests to draw a list.
 */

export interface LeadContext {
  readonly id: string;
  readonly name: string;
  readonly company: string | null;
  readonly phone: string | null;
  readonly owner_name: string | null;
}

export interface ConversationSummary {
  readonly id: string;
  readonly subject: string | null;
  readonly primary_channel: string;
  readonly status: string;
  readonly contact_name: string | null;
  readonly assignee_name: string | null;
  readonly unread_count: number;
  readonly last_message_at: string | null;
  readonly lead: LeadContext | null;
}

/**
 * Who the conversation is with.
 *
 * Same rule as everywhere else: the business leads, the person at it is a
 * separate fact, and neither is ever printed twice. `lead.name` is the prospect
 * record's name, which for a business captured without a named contact is the
 * company itself - so it is only shown as the contact when a distinct company
 * name exists.
 */
function identify(conversation: ConversationSummary): { business: string; contact: string | null } {
  const lead = conversation.lead;
  if (lead) {
    if (lead.company) {
      return { business: lead.company, contact: lead.name && lead.name !== lead.company ? lead.name : null };
    }
    return { business: lead.name, contact: null };
  }
  if (conversation.contact_name) return { business: conversation.contact_name, contact: null };
  return { business: 'Not matched to a customer yet', contact: null };
}

export function ConversationFilters({
  status,
  counts,
}: {
  status: string;
  counts: Record<string, number>;
}): JSX.Element {
  const links: FilterLink[] = ['', 'active', 'resolved', 'archived'].map((value) => ({
    key: value || 'all',
    href: value ? `/inbox?status=${value}` : '/inbox',
    label: value ? value.charAt(0).toUpperCase() + value.slice(1) : 'All',
    count: counts[value || 'all'] ?? 0,
    testId: `filter-${value || 'all'}`,
  }));
  return <FilterLinks links={links} active={status || 'all'} aria-label="Conversation filters" />;
}

export function ConversationList({
  conversations,
  activeId,
  totalEverywhere,
  status,
}: {
  conversations: ConversationSummary[];
  activeId?: string;
  totalEverywhere: number;
  status: string;
}): JSX.Element {
  if (conversations.length === 0) {
    return (
      <p data-testid="inbox-empty" className="px-4 py-10 text-center text-sm text-muted-foreground">
        {totalEverywhere > 0 ? (
          <>
            Nothing under <strong className="text-foreground">{status || 'All'}</strong>. This
            workspace has {totalEverywhere} conversation{totalEverywhere === 1 ? '' : 's'} under the
            other filters &mdash; nothing has been lost.{' '}
            <Link href="/inbox" className="text-accent underline-offset-2 hover:underline">
              Show all
            </Link>
          </>
        ) : (
          'No conversations yet. Open one above.'
        )}
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border" data-testid="conversation-rows">
      {conversations.map((conversation) => {
        const { business, contact } = identify(conversation);
        const owner =
          conversation.assignee_name ?? conversation.lead?.owner_name ?? null;
        const unread = conversation.unread_count > 0;
        const selected = conversation.id === activeId;

        return (
          <li key={conversation.id} className="relative">
            {selected ? (
              <span aria-hidden="true" className="absolute inset-y-0 left-0 w-0.5 bg-accent" />
            ) : null}
            <Link
              href={`/inbox/${conversation.id}`}
              data-testid={`conversation-link-${conversation.id}`}
              aria-current={selected ? 'page' : undefined}
              className={cn(
                'block px-4 py-3 transition-colors',
                selected ? 'bg-accent-soft' : 'hover:bg-surface-hover',
              )}
            >
              <span className="flex items-start gap-2.5">
                <Avatar name={business} size="md" className="mt-0.5" />

                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-2">
                    <span
                      className={cn(
                        'truncate text-sm text-foreground',
                        unread ? 'font-semibold' : 'font-medium',
                      )}
                      title={business}
                    >
                      {business}
                    </span>
                    <span className="shrink-0 text-xs tabular text-muted-foreground">
                      {conversation.last_message_at
                        ? formatDateTime(conversation.last_message_at)
                        : ''}
                    </span>
                  </span>

                  <span className="mt-0.5 flex items-baseline justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5 text-[13px] text-muted-foreground">
                      <ChannelIcon channel={conversation.primary_channel} size={13} />
                      {/*
                        Contact and owner, or the fact that nobody owns it.
                        Falling back to the channel name would repeat what the
                        glyph beside it already says and waste the only line
                        that can carry who is responsible.
                      */}
                      <span className="truncate">
                        {[contact, owner].filter(Boolean).join(' · ') || 'Unassigned'}
                      </span>
                    </span>
                    {unread ? (
                      <span
                        data-testid={`unread-${conversation.id}`}
                        className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent"
                      >
                        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent" />
                        {conversation.unread_count}
                        <span className="sr-only">unread</span>
                      </span>
                    ) : null}
                  </span>

                  {/*
                    The subject, not a message preview: the conversations endpoint
                    returns no last-message text and fetching fifty threads to
                    draw a list would be fifty requests.
                  */}
                  <span className="mt-0.5 block truncate text-[13px] text-secondary-foreground">
                    {conversation.subject ?? 'No subject'}
                  </span>
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
