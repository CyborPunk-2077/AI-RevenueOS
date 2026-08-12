import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { Card, EmptyState, PageHeader, Stat, StatusPill } from '@/features/ui/primitives';
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
  const [leadsResult, tasksResult, boardResult] = await Promise.all([
    apiFetch<{ leads: Lead[] }>('/leads?page_size=100'),
    apiFetch<{ tasks: Task[] }>('/tasks?status=open&page_size=100'),
    apiFetch<{ totals: BoardTotals }>('/deals/board'),
  ]);

  const leads = leadsResult.data?.leads ?? [];
  const tasks = tasksResult.data?.tasks ?? [];
  // The server already excludes won and lost from these, so re-deriving them
  // here would only be a second, disagreeing definition of "open".
  const totals = boardResult.data?.totals ?? { open_count: 0, open_value_minor: 0 };

  const openLeads = leads.filter(
    (l) => l.status !== 'converted' && l.status !== 'disqualified' && l.status !== 'archived',
  );
  const noReply = openLeads.filter((l) => l.first_response_at === null);
  const unassigned = openLeads.filter((l) => l.assignee_id === null);
  const withFollowUp = new Set(
    tasks.filter((t) => t.entity_type === 'lead' && t.entity_id).map((t) => t.entity_id as string),
  );
  const noNextAction = openLeads.filter((l) => !withFollowUp.has(l.id));

  const overdue = tasks.filter((t) => t.is_overdue);
  const dueToday = tasks.filter((t) => !t.is_overdue && isToday(t.due_at));

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
              value={String(overdue.length)}
              hint="Promised by a date that has passed"
            />
          </Link>
          <Link href="/leads" className="block" data-testid="stat-no-reply">
            <Stat
              label="Enquiries with no reply"
              value={String(noReply.length)}
              hint="Nobody has responded yet"
            />
          </Link>
          <Link href="/leads" className="block" data-testid="stat-unassigned">
            <Stat
              label="Unassigned prospects"
              value={String(unassigned.length)}
              hint="No named owner"
            />
          </Link>
          <Link href="/leads" className="block" data-testid="stat-no-next-action">
            <Stat
              label="No next action"
              value={String(noNextAction.length)}
              hint="Open, but nothing is scheduled"
            />
          </Link>
        </div>
      </section>

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
