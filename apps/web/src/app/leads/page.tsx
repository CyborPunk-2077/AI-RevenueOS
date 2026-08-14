import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { identifyLead } from '@/features/leads/identity';
import { NewLeadForm } from '@/features/leads/new-lead-form';
import { Avatar } from '@/features/ui/avatar';
import { DataTable, TableEmpty, type Column } from '@/features/ui/data-table';
import { duration, minutesBetween } from '@/features/ui/format';
import { PageHeader } from '@/features/ui/primitives';
import { LabelChip, MissingValue, StatusText } from '@/features/ui/status';
import { FilterLinks, Toolbar, type FilterLink } from '@/features/ui/toolbar';

export const dynamic = 'force-dynamic';

/**
 * The working list.
 *
 * **Business-first.** `new-lead-form` writes the company name into `first_name`
 * when a business is added with no named contact - which is the common case for
 * a prospecting list - and marks it with `capture.name_is_business`. A list that
 * leads with `first_name` therefore shows a shop where a person should be, and a
 * list that prints both columns from the same field teaches somebody that the
 * business *is* the person. Business, primary contact and owner are three
 * different facts and never interchangeable.
 */

interface Lead {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly phone: string | null;
  readonly status: string;
  readonly source: string;
  readonly assignee_id: string | null;
  readonly first_response_at: string | null;
  readonly capture: Record<string, unknown> | null;
  readonly created_at: string | null;
}

interface Task {
  readonly id: string;
  readonly title: string;
  readonly status: string;
  readonly entity_type: string | null;
  readonly entity_id: string | null;
  readonly due_at: string | null;
  readonly is_overdue: boolean;
}

interface Member {
  readonly id: string;
  readonly full_name: string;
  readonly is_active: boolean;
}

/**
 * Sentence case, and quiet. The pill this replaces made every row shout equally,
 * which meant a disqualified prospect and a new enquiry looked like the same
 * kind of event.
 */
const STATUS_LABEL: Record<string, string> = {
  new: 'New',
  contacted: 'Contacted',
  qualified: 'Qualified',
  nurturing: 'Nurturing',
  converted: 'Converted',
  disqualified: 'Disqualified',
  archived: 'Archived',
};

// Matches the metrics service. A prospect stops being open work once it is
// converted, disqualified or archived.
const OPEN_STATUSES = new Set(['new', 'contacted', 'qualified', 'nurturing']);
const SETTLED = new Set(['converted', 'disqualified', 'archived']);

const PAGE_SIZE = 50;

type Filter = 'all' | 'awaiting' | 'unassigned' | 'no-next-action';

const FILTER_LABEL: Record<Exclude<Filter, 'all'>, string> = {
  awaiting: 'Waiting for a first reply',
  unassigned: 'Unassigned',
  'no-next-action': 'No next action',
};

function days(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

interface Row {
  lead: Lead;
  business: string;
  contact: string | null;
  owner: string | null;
  next: Task | null;
  open: boolean;
  settled: boolean;
  noReply: boolean;
  replyMinutes: number | null;
  age: number | null;
}

const COLUMNS: Array<Column<Row>> = [
  {
    key: 'business',
    header: 'Business',
    width: '29%',
    cell: (row) => (
      // Deliberately not wrapping. A marker that drops to a second line makes the
      // row 55px tall, and one such row in ten turns a scannable list into a
      // ragged one. The name truncates instead; the markers are short and fixed.
      <span className="flex items-center gap-2">
        <Avatar name={row.business} />
        <span className="flex min-w-0 items-center gap-x-2">
          <Link
            href={`/leads/${row.lead.id}`}
            data-testid={`lead-link-${row.lead.id}`}
            title={row.business}
            className="truncate font-medium text-foreground underline-offset-2 hover:underline"
          >
            {row.business}
          </Link>
          {row.noReply ? (
            <StatusText
              tone="critical"
              className="shrink-0 whitespace-nowrap"
              data-testid={`no-reply-${row.lead.id}`}
            >
              no reply yet
            </StatusText>
          ) : null}
          {/*
            Invented demonstration businesses, so nobody rings one. This earns a
            chip where almost nothing else does: mistaking demo data for a real
            prospect is exactly the error that cost a founder record once.
          */}
          {row.lead.capture?.demo_data ? (
            <LabelChip className="shrink-0" data-testid={`demo-${row.lead.id}`}>
              sample
            </LabelChip>
          ) : null}
        </span>
      </span>
    ),
  },
  {
    key: 'contact',
    header: 'Primary contact',
    dropAt: 900,
    width: '13%',
    cell: (row) =>
      row.contact ? (
        <span className="block truncate text-secondary-foreground" title={row.contact}>
          {row.contact}
        </span>
      ) : (
        <span className="text-muted-foreground">&mdash;</span>
      ),
  },
  {
    key: 'owner',
    header: 'Owner',
    width: '13%',
    cell: (row) =>
      row.owner ? (
        <span className="block truncate text-secondary-foreground" title={row.owner}>
          {row.owner}
        </span>
      ) : (
        <StatusText tone="critical" data-testid={`unassigned-${row.lead.id}`}>
          Unassigned
        </StatusText>
      ),
  },
  {
    key: 'next-action',
    header: 'Next action',
    width: '18%',
    cell: (row) =>
      row.next ? (
        <span className="flex items-baseline gap-2">
          <span className="truncate text-secondary-foreground" title={row.next.title}>
            {row.next.title}
          </span>
          {row.next.is_overdue ? (
            <StatusText tone="critical" className="shrink-0">
              overdue
            </StatusText>
          ) : null}
        </span>
      ) : row.settled ? (
        <span className="text-muted-foreground">&mdash;</span>
      ) : (
        <MissingValue>None set</MissingValue>
      ),
  },
  {
    key: 'first-reply',
    header: 'First reply',
    align: 'right',
    width: '10%',
    cell: (row) => (
      <span data-testid={`first-reply-${row.lead.id}`}>
        {row.replyMinutes !== null ? (
          <span className="text-secondary-foreground">{duration(row.replyMinutes)}</span>
        ) : row.noReply ? (
          <MissingValue>Not yet</MissingValue>
        ) : (
          <span className="text-muted-foreground">&mdash;</span>
        )}
      </span>
    ),
  },
  {
    key: 'age',
    header: 'Age',
    align: 'right',
    dropAt: 1100,
    width: '6%',
    cell: (row) => (
      <span className="text-muted-foreground">{row.age === null ? '—' : `${row.age}d`}</span>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    width: '11%',
    cell: (row) => (
      <span className={row.settled ? 'text-muted-foreground' : 'text-secondary-foreground'}>
        {STATUS_LABEL[row.lead.status] ?? row.lead.status}
      </span>
    ),
  },
];

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: { filter?: string };
}): Promise<JSX.Element> {
  // One call for the follow-ups rather than one per row: a list of fifty
  // prospects must not become fifty-one requests.
  const [result, tasksResult, membersResult] = await Promise.all([
    apiFetch<{ leads: Lead[] }>(`/leads?page_size=${PAGE_SIZE}`),
    apiFetch<{ tasks: Task[] }>('/tasks?status=open&page_size=100'),
    apiFetch<{ members: Member[] }>('/users/members'),
  ]);

  const all = result.data?.leads ?? [];
  const members = membersResult.data?.members ?? [];
  const owners = new Map(members.map((m) => [m.id, m.full_name]));

  const nextActions = new Map<string, Task>();
  for (const task of tasksResult.data?.tasks ?? []) {
    if (task.entity_type !== 'lead' || !task.entity_id) continue;
    // The list arrives ordered by due date, so the first one seen is the next.
    if (!nextActions.has(task.entity_id)) nextActions.set(task.entity_id, task);
  }

  /*
   * The filters exist so a count on Today leads to the rows that make it up.
   * They apply the same open-status and first-response rules the metrics service
   * uses; if the two ever drift, a figure will say 4 and show 3 rows, and the
   * owner will rightly stop believing both.
   */
  const filter: Filter =
    searchParams.filter === 'awaiting' ||
    searchParams.filter === 'unassigned' ||
    searchParams.filter === 'no-next-action'
      ? searchParams.filter
      : 'all';

  const openLeads = all.filter((l) => OPEN_STATUSES.has(l.status));
  const awaiting = openLeads.filter((l) => l.first_response_at === null);
  const unassigned = openLeads.filter((l) => l.assignee_id === null);
  const noNextAction = openLeads.filter((l) => !nextActions.has(l.id));

  const leads =
    filter === 'awaiting'
      ? awaiting
      : filter === 'unassigned'
        ? unassigned
        : filter === 'no-next-action'
          ? noNextAction
          : all;

  const rows: Row[] = leads.map((lead) => {
    const { business, contact } = identifyLead(lead);
    const open = OPEN_STATUSES.has(lead.status);
    return {
      lead,
      business,
      contact,
      owner: lead.assignee_id ? (owners.get(lead.assignee_id) ?? 'Another colleague') : null,
      next: nextActions.get(lead.id) ?? null,
      open,
      settled: SETTLED.has(lead.status),
      noReply: lead.first_response_at === null && open,
      replyMinutes: minutesBetween(lead.created_at, lead.first_response_at),
      age: days(lead.created_at),
    };
  });

  const links: FilterLink[] = [
    { key: 'all', href: '/leads', label: 'All', count: all.length },
    {
      key: 'awaiting',
      href: '/leads?filter=awaiting',
      label: FILTER_LABEL.awaiting,
      count: awaiting.length,
    },
    {
      key: 'unassigned',
      href: '/leads?filter=unassigned',
      label: FILTER_LABEL.unassigned,
      count: unassigned.length,
    },
    {
      key: 'no-next-action',
      href: '/leads?filter=no-next-action',
      label: FILTER_LABEL['no-next-action'],
      count: noNextAction.length,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Prospects"
        description={
          filter !== 'all'
            ? `Showing only: ${FILTER_LABEL[filter].toLowerCase()}.`
            : awaiting.length > 0
              ? `${awaiting.length} ${awaiting.length === 1 ? 'enquiry has' : 'enquiries have'} had no reply yet.`
              : 'Every open enquiry here has had a first reply.'
        }
        actions={<NewLeadForm members={members} />}
      />

      <Toolbar>
        <FilterLinks links={links} active={filter} aria-label="Prospect filters" />
      </Toolbar>

      {/*
        The way back out of a filtered view. `All` above does the same thing, but
        this one is the marker Today's figures and the browser suites expect to
        find, and it reads as a sentence rather than as a tab.
      */}
      {filter !== 'all' ? (
        <p>
          <Link
            href="/leads"
            data-testid="clear-filter"
            className="text-[13px] text-accent underline-offset-2 hover:underline"
          >
            &larr; Show all prospects
          </Link>
        </p>
      ) : null}

      <section aria-labelledby="lead-list-heading">
        <h2 id="lead-list-heading" className="sr-only">
          Prospect list
        </h2>
        <DataTable
          caption="Prospects for your organisation"
          columns={COLUMNS}
          rows={rows}
          rowKey={(row) => row.lead.id}
          bodyTestId="lead-rows"
          severity={(row) =>
            row.next?.is_overdue ? { tone: 'critical', label: 'Follow-up overdue' } : null
          }
          empty={
            <TableEmpty
              data-testid="empty-state"
              title={filter === 'all' ? 'No prospects yet' : 'Nothing matches this filter'}
              description={
                filter === 'all'
                  ? 'Add a business, import a spreadsheet, or publish an enquiry form and they will arrive here.'
                  : 'Every prospect has been dealt with on this measure. Show all prospects to see the rest.'
              }
            />
          }
        />
        {/*
          Said out loud rather than drawn as a pager. The API returns a fixed page
          and cannot page, so a pager would be a control that does nothing.
        */}
        {all.length >= PAGE_SIZE ? (
          <p className="mt-2 text-[13px] text-muted-foreground">
            Showing the {PAGE_SIZE} most recent prospects. Older ones are not listed here yet.
          </p>
        ) : null}
      </section>
    </div>
  );
}
