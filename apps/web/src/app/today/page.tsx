import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { identifyLead } from '@/features/leads/identity';
import { StartingBaseline, type BaselinePayload } from '@/features/leads/starting-baseline';
import { Avatar } from '@/features/ui/avatar';
import { DataTable, TableEmpty, type Column, type RowGroup } from '@/features/ui/data-table';
import { duration, elapsedSince, minutesBetween, RelativeTime } from '@/features/ui/format';
import { MetricStrip, type Metric } from '@/features/ui/metric-strip';
import { PageHeader, SectionHeader } from '@/features/ui/primitives';
import { MissingValue, StatusText } from '@/features/ui/status';
import { money } from '@/lib/money';

export const dynamic = 'force-dynamic';

/**
 * The daily command centre.
 *
 * It answers one question - **what requires attention right now?** - and it is
 * deliberately not an analytics page. Every number is a count of records a person
 * can open and act on, and each one links to that list. A dashboard whose figures
 * cannot be clicked through to the rows behind them is decoration, and an SME
 * owner learns very quickly not to trust it.
 *
 * What changed from the version this replaces: it showed seven metrics plus a
 * pipeline pair, in nine bordered cards, above four separate tables that each
 * put the owner in a different column. It read as a report. Now there is one
 * five-figure strip and **one** operational table whose groups are headings
 * inside it, so the columns stay aligned across groups and the eye reads one
 * grid.
 */

interface Lead {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
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
  readonly assignee_name: string | null;
  readonly due_at: string | null;
  readonly is_overdue: boolean;
}

interface Member {
  readonly id: string;
  readonly full_name: string;
}

interface BoardTotals {
  readonly open_count: number;
  readonly open_value_minor: number;
}

/**
 * Computed server-side over the caller's own scope, so a salesperson sees the
 * leakage in their own book. Counting these in the page would mean re-deriving
 * "open" a second time, in a second place, from one page of results.
 */
interface ResponseMetrics {
  readonly open_total: number;
  readonly awaiting_first_response: number;
  readonly unassigned: number;
  readonly no_next_action: number;
  readonly answered_total: number;
  readonly median_first_response_minutes: number | null;
  readonly longest_wait_minutes: number | null;
  readonly overdue_follow_ups: number;
}

const OPEN_STATUSES = new Set(['new', 'contacted', 'qualified', 'nurturing']);
const WEEK = 7 * 86_400_000;
/** A prospect answered this long ago with nothing scheduled has gone quiet. */
const STALLED_DAYS = 14;

function isToday(iso: string | null): boolean {
  if (!iso) return false;
  const due = new Date(iso);
  const now = new Date();
  return (
    due.getFullYear() === now.getFullYear() &&
    due.getMonth() === now.getMonth() &&
    due.getDate() === now.getDate()
  );
}

/** One row of the attention table, whatever produced it. */
interface AttentionRow {
  key: string;
  href: string;
  business: string;
  contact: string | null;
  source: string;
  owner: string | null;
  /** "3 days" waiting, or the due date. Right-aligned and tabular. */
  when: string;
  whenTone: 'plain' | 'critical';
  lastTouch: string | null;
  nextAction: { title: string; overdue: boolean } | null;
  overdue: boolean;
}

const COLUMNS: Array<Column<AttentionRow>> = [
  {
    key: 'business',
    header: 'Business',
    width: '24%',
    cell: (row) => (
      <span className="flex items-center gap-2">
        <Avatar name={row.business} />
        <Link
          href={row.href}
          className="truncate font-medium text-foreground underline-offset-2 hover:underline"
          title={row.business}
        >
          {row.business}
        </Link>
      </span>
    ),
  },
  {
    key: 'contact',
    header: 'Primary contact',
    dropAt: 900,
    width: '15%',
    cell: (row) =>
      row.contact ? (
        <span className="block truncate text-secondary-foreground">{row.contact}</span>
      ) : (
        <span className="text-muted-foreground">&mdash;</span>
      ),
  },
  {
    key: 'source',
    header: 'Source',
    dropAt: 1100,
    width: '9%',
    cell: (row) => (
      <span className="block truncate text-muted-foreground">{row.source.replace(/_/g, ' ')}</span>
    ),
  },
  {
    key: 'owner',
    header: 'Owner',
    width: '13%',
    cell: (row) =>
      row.owner ? (
        <span className="block truncate text-secondary-foreground">{row.owner}</span>
      ) : (
        <MissingValue>Unassigned</MissingValue>
      ),
  },
  {
    key: 'when',
    header: 'Waiting',
    align: 'right',
    width: '9%',
    cell: (row) =>
      row.whenTone === 'critical' ? (
        <StatusText tone="critical">{row.when}</StatusText>
      ) : (
        <span className="text-secondary-foreground">{row.when}</span>
      ),
  },
  {
    key: 'last-touch',
    header: 'Last touch',
    align: 'right',
    dropAt: 1100,
    width: '12%',
    cell: (row) =>
      row.lastTouch ? (
        <RelativeTime iso={row.lastTouch} mode="date" className="text-muted-foreground" />
      ) : (
        <span className="text-muted-foreground">&mdash;</span>
      ),
  },
  {
    key: 'next-action',
    header: 'Next action',
    dropAt: 900,
    width: '18%',
    cell: (row) => {
      if (!row.nextAction) return <MissingValue>None set</MissingValue>;
      /*
       * One red word per row, not three.
       *
       * An overdue row already carries a critical severity rule down its left
       * edge; when the wait itself is overdue the Waiting column says so in red
       * as well. Repeating it here made a single fact shout from three places
       * across one row, which is the "everything is red" problem in miniature -
       * and the rows where the *task* is overdue but the wait is not, which are
       * the ones this column exists to surface, were no louder than the rest.
       *
       * So the marker stays wherever it is the only textual signal, and steps
       * back to muted where the Waiting column has already said it. Nothing is
       * removed: every overdue row still reads "Overdue" in words, and the rule
       * and the sr-only label are untouched.
       */
      const alreadySaidInWaiting = row.whenTone === 'critical';
      return (
        <span className="flex items-baseline gap-2">
          <span className="truncate text-secondary-foreground" title={row.nextAction.title}>
            {row.nextAction.title}
          </span>
          {row.nextAction.overdue ? (
            alreadySaidInWaiting ? (
              <span className="shrink-0 text-xs text-muted-foreground">overdue</span>
            ) : (
              <StatusText tone="critical" className="shrink-0">
                Overdue
              </StatusText>
            )
          ) : null}
        </span>
      );
    },
  },
];

export default async function TodayPage(): Promise<JSX.Element> {
  const [leadsResult, tasksResult, boardResult, metricsResult, baselineResult, membersResult] =
    await Promise.all([
      apiFetch<{ leads: Lead[] }>('/leads?page_size=100'),
      apiFetch<{ tasks: Task[] }>('/tasks?status=open&page_size=100'),
      apiFetch<{ totals: BoardTotals }>('/deals/board'),
      apiFetch<ResponseMetrics>('/leads/response-metrics'),
      apiFetch<BaselinePayload>('/leads/starting-baseline'),
      apiFetch<{ members: Member[] }>('/users/members'),
    ]);

  const leads = leadsResult.data?.leads ?? [];
  const tasks = tasksResult.data?.tasks ?? [];
  // The server already excludes won and lost from these, so re-deriving them
  // here would only be a second, disagreeing definition of "open".
  const totals = boardResult.data?.totals ?? { open_count: 0, open_value_minor: 0 };
  const metrics = metricsResult.data ?? null;
  const owners = new Map((membersResult.data?.members ?? []).map((m) => [m.id, m.full_name]));

  const openLeads = leads.filter((l) => OPEN_STATUSES.has(l.status));

  // The next action per prospect. One pass, because a list of fifty prospects
  // must not become fifty-one requests.
  const nextActions = new Map<string, Task>();
  for (const task of tasks) {
    if (task.entity_type !== 'lead' || !task.entity_id) continue;
    // The list arrives ordered by due date, so the first one seen is the next.
    if (!nextActions.has(task.entity_id)) nextActions.set(task.entity_id, task);
  }

  const toRow = (lead: Lead, when: string, whenTone: 'plain' | 'critical'): AttentionRow => {
    const { business, contact } = identifyLead(lead);
    const next = nextActions.get(lead.id) ?? null;
    return {
      key: lead.id,
      href: `/leads/${lead.id}`,
      business,
      contact,
      source: lead.source,
      owner: lead.assignee_id ? (owners.get(lead.assignee_id) ?? 'Another colleague') : null,
      when,
      whenTone,
      lastTouch: lead.first_response_at,
      nextAction: next ? { title: next.title, overdue: next.is_overdue } : null,
      overdue: next?.is_overdue ?? false,
    };
  };

  // --- group 1: nobody has replied to these. Oldest first, always. ----------
  const waiting = openLeads
    .filter((l) => l.first_response_at === null)
    .sort((a, b) => new Date(a.created_at ?? 0).getTime() - new Date(b.created_at ?? 0).getTime())
    .map((lead) => toRow(lead, duration(elapsedSince(lead.created_at)), 'plain'));

  // --- group 2: a promise that is due or already broken ---------------------
  const byId = new Map(openLeads.map((l) => [l.id, l]));
  const seenBusiness = new Set<string>();
  const dueOrOverdue = tasks
    .filter((t) => t.entity_type === 'lead' && t.entity_id && byId.has(t.entity_id))
    .filter((t) => t.is_overdue || isToday(t.due_at))
    .sort((a, b) => new Date(a.due_at ?? 0).getTime() - new Date(b.due_at ?? 0).getTime())
    // One row per business, carrying its most pressing promise. Two rows for the
    // same shop reads as a duplicate rather than as two jobs, and every row in
    // this table is meant to be a business somebody opens. The individual
    // promises are the Follow-ups queue's subject, not this one's.
    .filter((t) => {
      if (seenBusiness.has(t.entity_id!)) return false;
      seenBusiness.add(t.entity_id!);
      return true;
    })
    .map((task) => {
      const lead = byId.get(task.entity_id!)!;
      // Everything in this group is either overdue or due today, so the date
      // itself adds nothing and costs a column width.
      const row = toRow(
        lead,
        task.is_overdue ? 'Overdue' : 'Today',
        task.is_overdue ? 'critical' : 'plain',
      );
      // The task that put this row here, not merely the first open one.
      return { ...row, key: task.id, nextAction: { title: task.title, overdue: task.is_overdue } };
    });

  /**
   * Overdue follow-ups that hang off a deal or a contact rather than a prospect.
   *
   * They are inside the `Overdue follow-ups` figure - the server counts every
   * open task - but this table identifies each row by its business and the tasks
   * API returns no name for a deal or a contact. Stating the remainder is what
   * makes the strip reconcile; silently dropping them would make the count look
   * wrong, and putting a task title in the Business column would make the table
   * lie about what its first column means.
   */
  const overdueElsewhere = tasks.filter(
    (t) => t.is_overdue && (t.entity_type !== 'lead' || !t.entity_id || !byId.has(t.entity_id)),
  ).length;

  // --- group 3: who have I already spoken to this week -----------------------
  const recentlyContacted = openLeads
    .filter(
      (l) =>
        l.first_response_at !== null && Date.now() - new Date(l.first_response_at).getTime() < WEEK,
    )
    .sort(
      (a, b) =>
        new Date(b.first_response_at ?? 0).getTime() - new Date(a.first_response_at ?? 0).getTime(),
    )
    .slice(0, 8)
    .map((lead) =>
      toRow(lead, duration(minutesBetween(lead.created_at, lead.first_response_at)), 'plain'),
    );

  /**
   * --- group 4: stalled ----------------------------------------------------
   *
   * A stated rule, not a prediction: answered more than a fortnight ago, and
   * nothing scheduled since. Rendered only when it is non-empty, because an
   * empty "Stalled" heading on a healthy day is noise.
   */
  const stalled = openLeads
    .filter((l) => l.first_response_at !== null && !nextActions.has(l.id))
    .filter((l) => Date.now() - new Date(l.first_response_at!).getTime() > STALLED_DAYS * 86_400_000)
    .sort(
      (a, b) =>
        new Date(a.first_response_at ?? 0).getTime() - new Date(b.first_response_at ?? 0).getTime(),
    )
    .map((lead) => toRow(lead, duration(elapsedSince(lead.first_response_at)), 'plain'));

  const groups: Array<RowGroup<AttentionRow>> = [];
  if (waiting.length > 0) {
    groups.push({
      key: 'waiting',
      testId: 'no-reply-rows',
      label: 'Waiting for a first reply',
      count: waiting.length,
      hint: 'oldest first',
      rows: waiting,
    });
  }
  if (dueOrOverdue.length > 0) {
    groups.push({
      key: 'due',
      testId: 'today-queue',
      label: 'Follow-ups due today or overdue',
      count: dueOrOverdue.length,
      rows: dueOrOverdue,
    });
  }
  if (recentlyContacted.length > 0) {
    groups.push({
      key: 'recent',
      testId: 'recently-contacted',
      label: 'Contacted in the last week',
      count: recentlyContacted.length,
      rows: recentlyContacted,
    });
  }
  if (stalled.length > 0) {
    groups.push({
      key: 'stalled',
      testId: 'stalled-rows',
      label: 'Stalled',
      count: stalled.length,
      hint: `answered over ${STALLED_DAYS} days ago with nothing scheduled since`,
      rows: stalled,
    });
  }

  const summary: Metric[] = [
    {
      key: 'median',
      testId: 'stat-median-response',
      label: 'First response, typically',
      value: duration(metrics?.median_first_response_minutes ?? null),
      hint:
        metrics && metrics.answered_total > 0
          ? `middle value across ${metrics.answered_total} answered`
          : 'nothing answered yet',
    },
    {
      key: 'waiting',
      testId: 'stat-no-reply',
      label: 'Waiting for a reply',
      value: String(metrics?.awaiting_first_response ?? waiting.length),
      hint: 'nobody has contacted them',
      href: '/leads?filter=awaiting',
    },
    {
      key: 'answered',
      testId: 'stat-answered',
      label: 'Enquiries answered',
      // Not "today". The server holds a running total, not a daily one, and
      // inventing a day boundary here would put a number on the screen that no
      // record could be opened to justify.
      value: metrics
        ? `${metrics.answered_total} of ${metrics.answered_total + metrics.awaiting_first_response}`
        : '—',
      hint: 'from logged calls and messages',
    },
    {
      key: 'overdue',
      testId: 'stat-overdue',
      label: 'Overdue follow-ups',
      value: String(metrics?.overdue_follow_ups ?? 0),
      hint: 'promised by a date that has passed',
      href: '/follow-ups?filter=overdue',
      ...((metrics?.overdue_follow_ups ?? 0) > 0 ? { emphasis: 'critical' as const } : {}),
    },
    {
      key: 'pipeline',
      testId: 'stat-pipeline',
      label: 'Open pipeline',
      value: money(totals.open_value_minor),
      hint: `${totals.open_count} open ${totals.open_count === 1 ? 'deal' : 'deals'}, not a forecast`,
      href: '/deals',
    },
  ];

  // Open prospects per owner, from the records themselves. Not a chart.
  const load = new Map<string, number>();
  for (const lead of openLeads) {
    const name = lead.assignee_id ? (owners.get(lead.assignee_id) ?? 'Another colleague') : 'Unassigned';
    load.set(name, (load.get(name) ?? 0) + 1);
  }
  const teamLoad = [...load.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Today"
        description="What is slipping, and what needs a call before the day ends."
      />

      <MetricStrip metrics={summary} aria-label="How the workspace stands today" />

      {/*
        The observations sit beside the table only where there is genuinely room
        for both. A 264px rail at 1440px leaves the table 848px for seven
        columns, which truncates the business name - and the business name is the
        whole point of the row. Below that width the same panel stacks under the
        table instead, which is one DOM node either way rather than two copies.
      */}
      <div className="flex flex-col gap-6 min-[1600px]:flex-row min-[1600px]:items-start">
        <section aria-labelledby="attention-heading" className="min-w-0 flex-1 space-y-3">
          <SectionHeader
            id="attention-heading"
            title="Needs attention now"
            description="Grouped by what is wrong with it. Every row is a business you can open."
          />
          <DataTable
            caption="Prospects needing attention, grouped by why"
            columns={COLUMNS}
            groups={groups}
            rowKey={(row) => row.key}
            severity={(row) => (row.overdue ? { tone: 'critical', label: 'Overdue' } : null)}
            empty={
              <TableEmpty
                title="Nothing needs attention"
                description="Every open enquiry has had a reply and no follow-up is overdue. Open Prospects to pick up new work."
                action={
                  <Link
                    href="/leads"
                    className="text-sm text-accent underline-offset-2 hover:underline"
                  >
                    Open Prospects
                  </Link>
                }
              />
            }
          />
        </section>

        {/*
          Observations, not advice. Every line below is a rule already visible in
          the data - the longest wait, a count of records with no owner - and it
          is worded as what it is. There is no suggestion engine behind this and
          it must never pretend there is one.
        */}
        <aside
          aria-label="Derived observations"
          className="grid gap-x-10 gap-y-5 border-t border-border pt-5 sm:grid-cols-2 min-[1600px]:w-[264px] min-[1600px]:shrink-0 min-[1600px]:grid-cols-1 min-[1600px]:border-t-0 min-[1600px]:pt-0"
        >
          <div className="space-y-2">
            <h2 className="text-[13px] font-semibold text-foreground">At risk</h2>
            <dl className="space-y-1.5 text-[13px]">
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">Longest anyone is waiting</dt>
                <dd data-testid="stat-longest-wait" className="tabular font-medium text-foreground">
                  {duration(metrics?.longest_wait_minutes ?? null)}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">
                  <Link href="/leads?filter=unassigned" className="underline-offset-2 hover:underline">
                    With no owner
                  </Link>
                </dt>
                <dd data-testid="stat-unassigned" className="tabular font-medium text-foreground">
                  {metrics?.unassigned ?? 0}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">
                  <Link
                    href="/leads?filter=no-next-action"
                    className="underline-offset-2 hover:underline"
                  >
                    Nothing scheduled next
                  </Link>
                </dt>
                <dd
                  data-testid="stat-no-next-action"
                  className="tabular font-medium text-foreground"
                >
                  {metrics?.no_next_action ?? 0}
                </dd>
              </div>
              {overdueElsewhere > 0 ? (
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-muted-foreground">
                    <Link
                      href="/follow-ups?filter=overdue"
                      className="underline-offset-2 hover:underline"
                    >
                      Overdue on a deal or contact
                    </Link>
                  </dt>
                  <dd className="tabular font-medium text-foreground">{overdueElsewhere}</dd>
                </div>
              ) : null}
            </dl>
          </div>

          {teamLoad.length > 0 ? (
            <div className="space-y-2 min-[1600px]:border-t min-[1600px]:border-border min-[1600px]:pt-4">
              <h2 className="text-[13px] font-semibold text-foreground">Open prospects by owner</h2>
              <dl className="space-y-1.5 text-[13px]">
                {teamLoad.map(([name, count]) => (
                  <div key={name} className="flex items-baseline justify-between gap-3">
                    <dt className="truncate text-muted-foreground">
                      {name === 'Unassigned' ? (
                        <MissingValue>Unassigned</MissingValue>
                      ) : (
                        name
                      )}
                    </dt>
                    <dd className="tabular font-medium text-foreground">{count}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </aside>
      </div>

      {/*
        The workspace's "before" picture. Kept below the day's work rather than
        above it: it is a record of where this workspace started, not something
        anybody acts on at 9:40am.
      */}
      <div className="border-t border-border pt-6">
        <StartingBaseline payload={baselineResult.data ?? null} />
      </div>
    </div>
  );
}
