import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { Card, EmptyState, PageHeader, Stat, StatusPill } from '@/features/ui/primitives';
import { StartingBaseline, type BaselinePayload } from '@/features/leads/starting-baseline';
import { formatDateTime } from '@/lib/dates';

export const dynamic = 'force-dynamic';

/**
 * The operational view: what is slipping, right now.
 *
 * Deliberately not an analytics page. Every number here is a count of records a
 * person can open and act on, and each one links to that list. A dashboard whose
 * figures cannot be clicked through to the rows behind them is decoration, and
 * an SME owner learns very quickly not to trust it.
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
  readonly priority: string;
  readonly entity_type: string | null;
  readonly entity_id: string | null;
  readonly assignee_name: string | null;
  readonly due_at: string | null;
  readonly is_overdue: boolean;
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

/** Whole units, because "1h 47m" invites precision nobody acts on. */
function duration(minutes: number | null): string {
  if (minutes === null) return '—';
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 60 * 48) return `${Math.round(minutes / 60)} hrs`;
  return `${Math.round(minutes / (60 * 24))} days`;
}

function hoursSince(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
}

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

function rupees(minor: number): string {
  return `₹${Math.round(minor / 100).toLocaleString('en-IN')}`;
}

function taskHref(task: Task): string {
  if (task.entity_type === 'lead' && task.entity_id) return `/leads/${task.entity_id}`;
  if (task.entity_type === 'contact' && task.entity_id) return `/contacts/${task.entity_id}`;
  if (task.entity_type === 'deal' && task.entity_id) return `/deals/${task.entity_id}`;
  return '/follow-ups';
}

export default async function TodayPage(): Promise<JSX.Element> {
  const [leadsResult, tasksResult, boardResult, metricsResult, baselineResult] = await Promise.all([
    apiFetch<{ leads: Lead[] }>('/leads?page_size=100'),
    apiFetch<{ tasks: Task[] }>('/tasks?status=open&page_size=100'),
    apiFetch<{ totals: BoardTotals }>('/deals/board'),
    apiFetch<ResponseMetrics>('/leads/response-metrics'),
    apiFetch<BaselinePayload>('/leads/starting-baseline'),
  ]);

  const leads = leadsResult.data?.leads ?? [];
  const tasks = tasksResult.data?.tasks ?? [];
  // The server already excludes won and lost from these, so re-deriving them
  // here would only be a second, disagreeing definition of "open".
  const totals = boardResult.data?.totals ?? { open_count: 0, open_value_minor: 0 };
  const metrics = metricsResult.data ?? null;

  // The lists below are the rows *behind* the counts. They come from the same
  // open-status definition the metrics service uses, so the tile and the table
  // under it cannot disagree.
  const openLeads = leads.filter(
    (l) => l.status !== 'converted' && l.status !== 'disqualified' && l.status !== 'archived',
  );
  const noReply = openLeads.filter((l) => l.first_response_at === null);

  const overdue = tasks.filter((t) => t.is_overdue);
  const dueToday = tasks.filter((t) => !t.is_overdue && isToday(t.due_at));

  // "Who did I just speak to?" - the list a founder checks before picking the
  // phone back up, so they do not ring somebody twice in a week. Answered within
  // the last seven days, most recent first.
  const WEEK = 7 * 86_400_000;
  const recentlyContacted = openLeads
    .filter((l) => l.first_response_at !== null && Date.now() - new Date(l.first_response_at).getTime() < WEEK)
    .sort(
      (a, b) =>
        new Date(b.first_response_at ?? 0).getTime() - new Date(a.first_response_at ?? 0).getTime(),
    )
    .slice(0, 8);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Today"
        description="What is slipping, and what needs a call before the day ends."
      />

      <section aria-labelledby="attention-heading" className="space-y-3">
        <h2 id="attention-heading" className="text-sm font-medium text-muted-foreground">
          Needs attention
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Link href="/follow-ups?filter=overdue" className="block" data-testid="stat-overdue">
            <Stat
              label="Overdue follow-ups"
              value={String(metrics?.overdue_follow_ups ?? overdue.length)}
              hint="Promised by a date that has passed"
            />
          </Link>
          <Link href="/leads?filter=awaiting" className="block" data-testid="stat-no-reply">
            <Stat
              label="Waiting for a first reply"
              value={String(metrics?.awaiting_first_response ?? noReply.length)}
              hint="Nobody has contacted them yet"
            />
          </Link>
          <Link href="/leads?filter=unassigned" className="block" data-testid="stat-unassigned">
            <Stat
              label="Unassigned prospects"
              value={String(metrics?.unassigned ?? 0)}
              hint="No named owner"
            />
          </Link>
          <Link
            href="/leads?filter=no-next-action"
            className="block"
            data-testid="stat-no-next-action"
          >
            <Stat
              label="No next action"
              value={String(metrics?.no_next_action ?? 0)}
              hint="Open, but nothing is scheduled"
            />
          </Link>
        </div>
      </section>

      {/* Response speed, kept separate from the backlog above: these describe how
          the team is doing, not what is on fire right now. Both are derived from
          logged outbound contact, so each one is answerable by opening a
          prospect and reading its timeline. */}
      <section aria-labelledby="speed-heading" className="space-y-3">
        <h2 id="speed-heading" className="text-sm font-medium text-muted-foreground">
          How quickly enquiries are answered
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <div data-testid="stat-median-response">
            <Stat
              label="Typical time to first reply"
              value={duration(metrics?.median_first_response_minutes ?? null)}
              hint={
                metrics && metrics.answered_total > 0
                  ? `Middle value across ${metrics.answered_total} answered ${
                      metrics.answered_total === 1 ? 'enquiry' : 'enquiries'
                    }`
                  : 'No enquiry has been answered yet'
              }
            />
          </div>
          <div data-testid="stat-longest-wait">
            <Stat
              label="Longest anyone is waiting"
              value={duration(metrics?.longest_wait_minutes ?? null)}
              hint="Oldest enquiry with no reply yet"
            />
          </div>
          <div data-testid="stat-answered">
            <Stat
              label="Enquiries answered"
              value={
                metrics ? `${metrics.answered_total} of ${metrics.answered_total + metrics.awaiting_first_response}` : '—'
              }
              hint="Counted from logged calls, emails and messages"
            />
          </div>
        </div>
      </section>

      {/* The pilot's "before" picture, next to the live figures it mirrors so the
          two can never be read as different measurements of the same thing. */}
      <StartingBaseline payload={baselineResult.data ?? null} />

      <section aria-labelledby="queue-heading" className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 id="queue-heading" className="text-sm font-medium text-muted-foreground">
            Overdue and due today
          </h2>
          <Link href="/follow-ups" className="text-sm text-primary underline-offset-2 hover:underline">
            All follow-ups
          </Link>
        </div>

        {overdue.length + dueToday.length === 0 ? (
          <EmptyState
            title="Nothing is overdue"
            description="Every scheduled follow-up is still in the future. Open Prospects to pick up new enquiries."
          />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Follow-ups that are overdue or due today</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th scope="col" className="px-5 py-3">
                    Follow-up
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Owner
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Due
                  </th>
                  <th scope="col" className="px-5 py-3">
                    When
                  </th>
                </tr>
              </thead>
              <tbody data-testid="today-queue">
                {[...overdue, ...dueToday].map((task) => (
                  <tr key={task.id} className="border-b border-border/60 hover:bg-surface-sunken">
                    <td className="px-5 py-3">
                      <Link
                        href={taskHref(task)}
                        className="font-medium text-primary underline-offset-2 hover:underline"
                      >
                        {task.title}
                      </Link>
                    </td>
                    <td className="px-5 py-3 text-muted-foreground">
                      {task.assignee_name ?? 'Unassigned'}
                    </td>
                    <td className="px-5 py-3">
                      <StatusPill tone={task.is_overdue ? 'danger' : 'warning'}>
                        {task.is_overdue ? 'overdue' : 'today'}
                      </StatusPill>
                    </td>
                    <td className="tabular px-5 py-3 text-muted-foreground">
                      {formatDateTime(task.due_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>

      <section aria-labelledby="fresh-heading" className="space-y-3">
        <h2 id="fresh-heading" className="text-sm font-medium text-muted-foreground">
          Enquiries waiting for a first reply
        </h2>
        {noReply.length === 0 ? (
          <EmptyState
            title="Everyone has been replied to"
            description="No open enquiry is sitting without a first response."
          />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Enquiries with no first response</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th scope="col" className="px-5 py-3">
                    Who
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Business
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Came from
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Waiting
                  </th>
                </tr>
              </thead>
              <tbody data-testid="no-reply-rows">
                {noReply.map((lead) => {
                  const waited = hoursSince(lead.created_at);
                  return (
                    <tr key={lead.id} className="border-b border-border/60 hover:bg-surface-sunken">
                      <td className="px-5 py-3">
                        <Link
                          href={`/leads/${lead.id}`}
                          className="font-medium text-primary underline-offset-2 hover:underline"
                        >
                          {lead.first_name} {lead.last_name ?? ''}
                        </Link>
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        {String(lead.capture?.company ?? '—')}
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">{lead.source}</td>
                      <td className="tabular px-5 py-3">
                        {waited === null ? (
                          '—'
                        ) : (
                          <StatusPill tone={waited > 24 ? 'danger' : 'warning'}>
                            {waited < 48 ? `${waited}h` : `${Math.floor(waited / 24)}d`}
                          </StatusPill>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}
      </section>

      {/* Answers "who have I already spoken to this week", so the founder does
          not ring the same business twice. */}
      {recentlyContacted.length > 0 ? (
        <section aria-labelledby="recent-heading" className="space-y-3">
          <h2 id="recent-heading" className="text-sm font-medium text-muted-foreground">
            Contacted in the last week
          </h2>
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Prospects contacted in the last seven days</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th scope="col" className="px-5 py-3">
                    Who
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Business
                  </th>
                  <th scope="col" className="px-5 py-3">
                    First reply
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody data-testid="recently-contacted">
                {recentlyContacted.map((lead) => (
                  <tr key={lead.id} className="border-b border-border/60 hover:bg-surface-sunken">
                    <td className="px-5 py-3">
                      <Link
                        href={`/leads/${lead.id}`}
                        className="font-medium text-primary underline-offset-2 hover:underline"
                      >
                        {lead.first_name} {lead.last_name ?? ''}
                      </Link>
                    </td>
                    <td className="px-5 py-3 text-muted-foreground">
                      {String(lead.capture?.company ?? '—')}
                    </td>
                    <td className="tabular px-5 py-3 text-muted-foreground">
                      {formatDateTime(lead.first_response_at)}
                    </td>
                    <td className="px-5 py-3">
                      <StatusPill tone="neutral">{lead.status}</StatusPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </section>
      ) : null}

      <section aria-labelledby="pipeline-heading" className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 id="pipeline-heading" className="text-sm font-medium text-muted-foreground">
            Open pipeline
          </h2>
          <Link href="/deals" className="text-sm text-primary underline-offset-2 hover:underline">
            Open the board
          </Link>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Stat label="Open deals" value={String(totals.open_count)} hint="Not yet won or lost" />
          <Stat
            label="Value in play"
            value={rupees(totals.open_value_minor)}
            hint="Total of open deals, not a forecast"
          />
        </div>
      </section>
    </div>
  );
}
