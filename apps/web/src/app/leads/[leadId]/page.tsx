import { notFound } from 'next/navigation';
import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { EditLeadForm } from '@/features/leads/edit-lead-form';
import { DuplicateReview, type Candidate } from '@/features/leads/duplicate-review';
import { LeadOwner, type Member } from '@/features/leads/lead-owner';
import { LeadQualification } from '@/features/leads/lead-qualification';
import { Timeline, type TimelineEntry } from '@/features/crm/timeline';
import { TaskPanel, type TaskEntry } from '@/features/crm/task-panel';
import { Card, StatusPill } from '@/features/ui/primitives';
import { formatDate } from '@/lib/dates';

export const dynamic = 'force-dynamic';

interface Lead {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly phone: string | null;
  readonly status: string;
  readonly source: string;
  readonly version: number;
  readonly qualification_score: number | null;
  readonly category: string | null;
  readonly assignee_id: string | null;
  readonly capture: Record<string, unknown> | null;
  readonly created_at: string | null;
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

function field(capture: Record<string, unknown> | null, key: string): string | null {
  const value = capture?.[key];
  return value === undefined || value === null || value === '' ? null : String(value);
}

function ageInDays(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

export default async function LeadDetailPage({
  params,
}: {
  params: { leadId: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<Lead>(`/leads/${params.leadId}`);

  // A record belonging to another tenant is indistinguishable from one that does
  // not exist -- the server decides, not the page.
  if (!result.ok || !result.data) notFound();
  const lead = result.data;

  // Everything below the header is independent, so it is fetched in one round of
  // parallel calls rather than a waterfall of four.
  //
  // Recorded duplicate candidates, not a fresh scan: scanning on every page view
  // would run a 500-row comparison for a screen nobody asked to deduplicate. The
  // button in the panel triggers the scan.
  const [duplicates, timelineResult, tasksResult, membersResult] = await Promise.all([
    apiFetch<{ candidates: Candidate[] }>(`/leads/${params.leadId}/duplicates`),
    apiFetch<{ timeline: TimelineEntry[] }>(`/leads/${params.leadId}/timeline`),
    apiFetch<{ tasks: TaskEntry[] }>(`/leads/${params.leadId}/tasks`),
    apiFetch<{ members: Member[] }>('/users/members'),
  ]);

  const capture = lead.capture ?? {};
  const company = field(capture, 'company');
  const tasks = tasksResult.data?.tasks ?? [];
  const openTasks = tasks.filter((t) => t.status === 'open' || t.status === 'in_progress');
  const nextAction = openTasks[0] ?? null;
  const age = ageInDays(lead.created_at);

  return (
    <div className="space-y-8">
      <Link
        href="/leads"
        className="text-sm text-muted-foreground underline-offset-2 hover:underline"
      >
        &larr; All prospects
      </Link>

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 data-testid="lead-name" className="heading text-2xl">
            {lead.first_name} {lead.last_name ?? ''}
          </h1>
          <StatusPill tone={STATUS_TONE[lead.status] ?? 'neutral'}>{lead.status}</StatusPill>
        </div>
        <p className="text-sm text-muted-foreground">
          {company ? <span className="font-medium text-foreground">{company}</span> : null}
          {company ? ' · ' : ''}
          {field(capture, 'industry') ?? 'Industry not recorded'}
          {field(capture, 'location') ? ` · ${field(capture, 'location')}` : ''}
        </p>
        <p className="text-sm text-muted-foreground">
          Came in via {lead.source}
          {age === null ? '' : age === 0 ? ' today' : ` ${age} day${age === 1 ? '' : 's'} ago`}
        </p>
      </header>

      {/* What somebody picking this record up needs before they call. */}
      <Card>
        <h2 className="font-medium">What they asked for</h2>
        <p data-testid="lead-requirement" className="mt-2 text-sm">
          {field(capture, 'requirement') ?? 'Nothing was recorded with this enquiry.'}
        </p>
        <dl className="mt-4 grid gap-4 sm:grid-cols-3">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Phone</dt>
            <dd data-testid="lead-phone" className="tabular mt-1 text-sm">
              {lead.phone ?? '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Email</dt>
            <dd data-testid="lead-email" className="mt-1 break-all text-sm">
              {lead.email ?? '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Team size</dt>
            <dd className="tabular mt-1 text-sm">{field(capture, 'employees') ?? '—'}</dd>
          </div>
        </dl>
      </Card>

      {/* Ownership and the next action are the two questions this product exists
          to answer, so they sit together and above everything else. */}
      <Card>
        <h2 className="font-medium">Ownership and next action</h2>
        <div className="mt-3">
          <LeadOwner
            leadId={lead.id}
            version={lead.version}
            assigneeId={lead.assignee_id}
            members={membersResult.data?.members ?? []}
          />
        </div>
        <p data-testid="lead-next-action" className="mt-4 text-sm">
          {nextAction ? (
            <>
              <span className="text-muted-foreground">Next action: </span>
              {nextAction.title}
              {nextAction.is_overdue ? (
                <span className="ml-2 text-xs font-medium text-destructive">overdue</span>
              ) : nextAction.due_at ? (
                <span className="ml-2 text-xs text-muted-foreground">
                  due {formatDate(nextAction.due_at)}
                </span>
              ) : null}
            </>
          ) : (
            <span className="text-destructive">
              No follow-up is scheduled. This is how prospects go quiet &mdash; add one below.
            </span>
          )}
        </p>
      </Card>

      <Card>
        <LeadQualification
          leadId={lead.id}
          score={lead.qualification_score}
          category={lead.category}
        />
      </Card>

      <Card>
        <TaskPanel parent="leads" parentId={lead.id} tasks={tasks} />
      </Card>

      <Card>
        <Timeline parent="leads" parentId={lead.id} entries={timelineResult.data?.timeline ?? []} />
      </Card>

      <Card>
        <EditLeadForm lead={lead} />
      </Card>

      <Card>
        <DuplicateReview lead={lead} candidates={duplicates.data?.candidates ?? []} />
      </Card>
    </div>
  );
}
