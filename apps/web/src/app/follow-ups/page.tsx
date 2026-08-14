import { apiFetch } from '@/lib/session';
import { FollowUpList, type AboutRecord, type FollowUp } from '@/features/crm/follow-up-list';
import { identifyLead } from '@/features/leads/identity';
import { PageHeader } from '@/features/ui/primitives';
import { FilterLinks, Toolbar, type FilterLink } from '@/features/ui/toolbar';

export const dynamic = 'force-dynamic';

/**
 * The work queue: everything somebody promised to do, in the order it is due.
 *
 * "Overdue" is decided by the server and arrives as a flag on each row. The
 * filter is a server query parameter rather than a client-side array filter, so
 * the page and the API cannot disagree about which rows are late.
 */

interface Lead {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly capture: Record<string, unknown> | null;
}

type Filter = 'all' | 'overdue' | 'mine';

const PAGE_SIZE = 100;

const FILTERS: readonly { key: Filter; label: string; query: string; href: string }[] = [
  {
    key: 'all',
    label: 'Everything open',
    query: `/tasks?status=open&page_size=${PAGE_SIZE}`,
    href: '/follow-ups',
  },
  {
    key: 'overdue',
    label: 'Overdue',
    query: `/tasks?overdue=true&page_size=${PAGE_SIZE}`,
    href: '/follow-ups?filter=overdue',
  },
  {
    key: 'mine',
    label: 'Mine',
    query: `/tasks?status=open&mine=true&page_size=${PAGE_SIZE}`,
    href: '/follow-ups?filter=mine',
  },
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
  const chosen = FILTERS.find((f) => f.key === active) ?? FILTERS[0]!;

  /*
   * The prospects are fetched alongside so a row can say which *business* it is
   * about rather than only which kind of record. The tasks endpoint returns
   * `entity_type` and `entity_id` and no name, and "Prospect" in every row is a
   * column that costs width and answers nothing.
   *
   * Counts for the other two filters come from the same open-task list rather
   * than from three requests: `mine` is the only one that cannot be derived,
   * and a count nobody can compute honestly is better left off than guessed.
   */
  const [result, openResult, leadsResult] = await Promise.all([
    apiFetch<{ tasks: FollowUp[] }>(chosen.query),
    apiFetch<{ tasks: FollowUp[] }>(`/tasks?status=open&page_size=${PAGE_SIZE}`),
    apiFetch<{ leads: Lead[] }>('/leads?page_size=100'),
  ]);

  const tasks = result.data?.tasks ?? [];
  const allOpen = openResult.data?.tasks ?? [];
  const overdueCount = allOpen.filter((t) => t.is_overdue).length;

  const businesses: Record<string, AboutRecord> = {};
  for (const lead of leadsResult.data?.leads ?? []) {
    businesses[lead.id] = {
      label: identifyLead(lead).business,
      href: `/leads/${lead.id}`,
    };
  }

  const links: FilterLink[] = [
    { ...FILTERS[0]!, count: allOpen.length, testId: 'filter-all' },
    { ...FILTERS[1]!, count: overdueCount, testId: 'filter-overdue' },
    // No count: "mine" is scoped to the caller by the server and cannot be
    // derived from the list above without re-implementing that scope here.
    { ...FILTERS[2]!, testId: 'filter-mine' },
  ];

  const overdueHere = tasks.filter((t) => t.is_overdue).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Follow-ups"
        description={
          overdueHere > 0
            ? overdueHere === 1
              ? 'One of these is already past its due date.'
              : `${overdueHere} of these are already past their due date.`
            : 'Nothing in this view is overdue.'
        }
      />

      <Toolbar>
        <FilterLinks links={links} active={active} aria-label="Filter follow-ups" />
      </Toolbar>

      <FollowUpList
        tasks={tasks}
        businesses={businesses}
        truncated={tasks.length >= PAGE_SIZE}
      />
    </div>
  );
}
