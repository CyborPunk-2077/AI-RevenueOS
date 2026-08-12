import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { FollowUpList, type FollowUp } from '@/features/crm/follow-up-list';
import { Card, EmptyState, PageHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

/**
 * The work queue: everything somebody promised to do, in the order it is due.
 *
 * "Overdue" is decided by the server and arrives as a flag on each row. The
 * filter is a server query parameter rather than a client-side array filter, so
 * the page and the API cannot disagree about which rows are late.
 */

type Filter = 'all' | 'overdue' | 'mine';

const FILTERS: readonly { key: Filter; label: string; query: string }[] = [
  { key: 'all', label: 'Everything open', query: '/tasks?status=open&page_size=100' },
  { key: 'overdue', label: 'Overdue', query: '/tasks?overdue=true&page_size=100' },
  { key: 'mine', label: 'Mine', query: '/tasks?status=open&mine=true&page_size=100' },
];

export default async function FollowUpsPage({
  searchParams,
}: {
  searchParams: { filter?: string };
}): Promise<JSX.Element> {
  const active: Filter =
    searchParams.filter === 'overdue' || searchParams.filter === 'mine'
      ? searchParams.filter
      : 'all';
  const chosen = FILTERS.find((f) => f.key === active) ?? FILTERS[0];

  const result = await apiFetch<{ tasks: FollowUp[] }>(chosen.query);
  const tasks = result.data?.tasks ?? [];
  const overdueCount = tasks.filter((t) => t.is_overdue).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Follow-ups"
        description={
          overdueCount > 0
            ? overdueCount === 1
              ? 'One of these is already past its due date.'
              : `${overdueCount} of these are already past their due date.`
            : 'Nothing in this view is overdue.'
        }
      />

      <nav aria-label="Filter follow-ups" className="flex flex-wrap gap-2">
        {FILTERS.map((filter) => (
          <Link
            key={filter.key}
            href={filter.key === 'all' ? '/follow-ups' : `/follow-ups?filter=${filter.key}`}
            data-testid={`filter-${filter.key}`}
            aria-current={active === filter.key ? 'page' : undefined}
            className={
              active === filter.key
                ? 'rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground'
                : 'rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground'
            }
          >
            {filter.label}
          </Link>
        ))}
      </nav>

      {tasks.length === 0 ? (
        <EmptyState
          title={active === 'overdue' ? 'Nothing is overdue' : 'No follow-ups here'}
          description="Follow-ups are created on a prospect or a deal. Open one and add the next action."
        />
      ) : (
        <Card className="p-0">
          <FollowUpList tasks={tasks} />
        </Card>
      )}
    </div>
  );
}
