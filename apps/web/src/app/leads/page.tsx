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

export default async function LeadsPage(): Promise<JSX.Element> {
  // One call for the follow-ups rather than one per row: a list of fifty prospects
  // must not become fifty-one requests.
  const [result, tasksResult, membersResult] = await Promise.all([
    apiFetch<{ leads: Lead[] }>('/leads?page_size=50'),
    apiFetch<{ tasks: Task[] }>('/tasks?status=open&page_size=100'),
    apiFetch<{ members: Member[] }>('/users/members'),
  ]);

  const leads = result.data?.leads ?? [];
  const owners = new Map((membersResult.data?.members ?? []).map((m) => [m.id, m.full_name]));

  const nextActions = new Map<string, Task>();
  for (const task of tasksResult.data?.tasks ?? []) {
    if (task.entity_type !== 'lead' || !task.entity_id) continue;
    // The list arrives ordered by due date, so the first one seen is the next one.
    if (!nextActions.has(task.entity_id)) nextActions.set(task.entity_id, task);
  }

  const untouched = leads.filter((l) => l.first_response_at === null && l.status === 'new').length;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Prospects"
        description={
          untouched > 0
            ? `${untouched} ${untouched === 1 ? 'enquiry has' : 'enquiries have'} had no reply yet.`
            : 'Every enquiry here has had a first reply.'
        }
      />

      <NewLeadForm />

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
                  const noReply = lead.first_response_at === null && lead.status === 'new';
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
