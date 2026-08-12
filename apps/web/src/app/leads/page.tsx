import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewLeadForm } from '@/features/leads/new-lead-form';
import { Card, EmptyState, PageHeader, StatusPill } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

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

const STATUS_TONE: Record<string, 'neutral' | 'success' | 'warning' | 'danger'> = {
  new: 'warning',
  contacted: 'neutral',
  qualified: 'success',
  nurturing: 'neutral',
  converted: 'success',
  disqualified: 'danger',
  archived: 'neutral',
};

function days(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

function minutesBetween(from: string | null, to: string | null): number | null {
  if (!from || !to) return null;
  return Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 60_000));
}

function duration(minutes: number | null): string {
  if (minutes === null) return '—';
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 60 * 48) return `${Math.round(minutes / 60)} hrs`;
  return `${Math.round(minutes / (60 * 24))} days`;
}

// Matches the metrics service. A prospect stops being "open work" once it is
// converted, disqualified or archived.
const OPEN_STATUSES = new Set(['new', 'contacted', 'qualified', 'nurturing']);

type Filter = 'all' | 'awaiting' | 'unassigned' | 'no-next-action';

const FILTER_LABEL: Record<Exclude<Filter, 'all'>, string> = {
  awaiting: 'Waiting for a first reply',
  unassigned: 'Unassigned',
  'no-next-action': 'No next action',
};

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: { filter?: string };
}): Promise<JSX.Element> {
  // One call for the follow-ups rather than one per row: a list of fifty prospects
  // must not become fifty-one requests.
  const [result, tasksResult, membersResult] = await Promise.all([
    apiFetch<{ leads: Lead[] }>('/leads?page_size=50'),
    apiFetch<{ tasks: Task[] }>('/tasks?status=open&page_size=100'),
    apiFetch<{ members: Member[] }>('/users/members'),
  ]);

  const all = result.data?.leads ?? [];
  const owners = new Map((membersResult.data?.members ?? []).map((m) => [m.id, m.full_name]));

  const nextActions = new Map<string, Task>();
  for (const task of tasksResult.data?.tasks ?? []) {
    if (task.entity_type !== 'lead' || !task.entity_id) continue;
    // The list arrives ordered by due date, so the first one seen is the next one.
    if (!nextActions.has(task.entity_id)) nextActions.set(task.entity_id, task);
  }

  // The filters exist so a count on Today leads to the rows that make it up. They
  // apply the same open-status and first-response rules the metrics service uses;
  // if these two ever drift, a tile will say 4 and show 3 rows, and the owner will
  // rightly stop believing both.
  const filter: Filter =
    searchParams.filter === 'awaiting' ||
    searchParams.filter === 'unassigned' ||
    searchParams.filter === 'no-next-action'
      ? searchParams.filter
      : 'all';

  const openLeads = all.filter((l) => OPEN_STATUSES.has(l.status));
  const leads =
    filter === 'awaiting'
      ? openLeads.filter((l) => l.first_response_at === null)
      : filter === 'unassigned'
        ? openLeads.filter((l) => l.assignee_id === null)
        : filter === 'no-next-action'
          ? openLeads.filter((l) => !nextActions.has(l.id))
          : all;

  const untouched = openLeads.filter((l) => l.first_response_at === null).length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Prospects"
        description={
          filter !== 'all'
            ? `Showing only: ${FILTER_LABEL[filter].toLowerCase()}.`
            : untouched > 0
              ? `${untouched} ${untouched === 1 ? 'enquiry has' : 'enquiries have'} had no reply yet.`
              : 'Every open enquiry here has had a first reply.'
        }
      />

      {filter !== 'all' ? (
        <p>
          <Link
            href="/leads"
            data-testid="clear-filter"
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            &larr; Show all prospects
          </Link>
        </p>
      ) : null}

      <NewLeadForm members={membersResult.data?.members ?? []} />

      <section aria-labelledby="lead-list-heading">
        <h2 id="lead-list-heading" className="sr-only">
          Prospect list
        </h2>

        {leads.length === 0 ? (
          <div data-testid="empty-state">
            <EmptyState
              title="No prospects yet"
              description="Add one above, import a spreadsheet, or publish an enquiry form and they will arrive here."
            />
          </div>
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Prospects for your organisation</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th scope="col" className="px-5 py-3">
                    Name
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Business
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Owner
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Next action
                  </th>
                  <th scope="col" className="px-5 py-3">
                    First reply
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Age
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody data-testid="lead-rows">
                {leads.map((lead) => {
                  const next = nextActions.get(lead.id) ?? null;
                  const age = days(lead.created_at);
                  const open = OPEN_STATUSES.has(lead.status);
                  const noReply = lead.first_response_at === null && open;
                  const replyMinutes = minutesBetween(lead.created_at, lead.first_response_at);
                  const settled = lead.status === 'converted' || lead.status === 'disqualified';
                  return (
                    <tr
                      key={lead.id}
                      className="border-b border-border/60 transition-colors hover:bg-surface-sunken"
                    >
                      <td className="px-5 py-3">
                        <Link
                          href={`/leads/${lead.id}`}
                          data-testid={`lead-link-${lead.id}`}
                          className="font-medium text-primary underline-offset-2 hover:underline"
                        >
                          {lead.first_name} {lead.last_name ?? ''}
                        </Link>
                        {noReply ? (
                          <span
                            data-testid={`no-reply-${lead.id}`}
                            className="ml-2 text-xs font-medium text-destructive"
                          >
                            no reply yet
                          </span>
                        ) : null}
                        {/* Invented demonstration businesses, so a founder never
                            mistakes one for somebody they should ring. */}
                        {lead.capture?.demo_data ? (
                          <span
                            data-testid={`demo-${lead.id}`}
                            className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                          >
                            sample
                          </span>
                        ) : null}
                      </td>
                      <td className="px-5 py-3 text-muted-foreground">
                        {String(lead.capture?.company ?? '—')}
                      </td>
                      <td className="px-5 py-3">
                        {lead.assignee_id ? (
                          (owners.get(lead.assignee_id) ?? 'Another colleague')
                        ) : (
                          <span
                            data-testid={`unassigned-${lead.id}`}
                            className="font-medium text-destructive"
                          >
                            Unassigned
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        {next ? (
                          <>
                            <span className="text-muted-foreground">{next.title}</span>
                            {next.is_overdue ? (
                              <span className="ml-2 text-xs font-medium text-destructive">
                                overdue
                              </span>
                            ) : null}
                          </>
                        ) : settled ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <span className="text-xs font-medium text-destructive">None set</span>
                        )}
                      </td>
                      <td className="tabular px-5 py-3" data-testid={`first-reply-${lead.id}`}>
                        {replyMinutes !== null ? (
                          <span className="text-muted-foreground">{duration(replyMinutes)}</span>
                        ) : noReply ? (
                          <span className="text-xs font-medium text-destructive">Not yet</span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="tabular px-5 py-3 text-muted-foreground">
                        {age === null ? '—' : `${age}d`}
                      </td>
                      <td className="px-5 py-3">
                        <StatusPill tone={STATUS_TONE[lead.status] ?? 'neutral'}>
                          {lead.status}
                        </StatusPill>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}
