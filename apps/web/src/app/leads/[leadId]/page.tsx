import { notFound } from 'next/navigation';
import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { EditLeadForm } from '@/features/leads/edit-lead-form';
import { DuplicateReview, type Candidate } from '@/features/leads/duplicate-review';
import { captureText, identifyLead } from '@/features/leads/identity';
import { LeadOwner, type Member } from '@/features/leads/lead-owner';
import { LeadQualification } from '@/features/leads/lead-qualification';
import { Timeline, type TimelineEntry } from '@/features/crm/timeline';
import { TaskPanel, type TaskEntry } from '@/features/crm/task-panel';
import { WhatsAppReplyBox } from '@/features/crm/whatsapp-reply-box';
import { duration, minutesBetween } from '@/features/ui/format';
import { SectionHeader } from '@/features/ui/primitives';
import { RecordHeader, type MetaFact } from '@/features/ui/record-header';
import { LabelChip, MissingValue, StatusText } from '@/features/ui/status';
import { formatDate } from '@/lib/dates';

export const dynamic = 'force-dynamic';

/**
 * One prospect, as a desktop workbench.
 *
 * What this replaces was eight stacked `Card`s in a single column: a person had
 * to scroll past ownership, qualification and a reply box to reach the history
 * that tells them what to say. Now the left column carries the narrative - what
 * they asked for, whether anybody has answered them, everything that has
 * happened, and the controls that add to it - and the right column carries the
 * metadata somebody sets once and then glances at.
 *
 * The header is the part that matters most. **The business is the `h1`**; the
 * person, the phone, the email and the internal owner are separate labelled
 * facts beneath it. Those are four different things and the old header conflated
 * the first two - it printed `first_name` as the heading, which for a business
 * captured with no named contact is the company, sitting where a person's name
 * should be.
 */

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
  readonly first_response_at: string | null;
  readonly capture: Record<string, unknown> | null;
  readonly created_at: string | null;
}

const OPEN_STATUSES = new Set(['new', 'contacted', 'qualified', 'nurturing']);

const STATUS_LABEL: Record<string, string> = {
  new: 'New',
  contacted: 'Contacted',
  qualified: 'Qualified',
  nurturing: 'Nurturing',
  converted: 'Converted',
  disqualified: 'Disqualified',
  archived: 'Archived',
};

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
  const { business, contact } = identifyLead(lead);
  const members = membersResult.data?.members ?? [];
  const owner = members.find((m) => m.id === lead.assignee_id) ?? null;
  const tasks = tasksResult.data?.tasks ?? [];
  const openTasks = tasks.filter((t) => t.status === 'open' || t.status === 'in_progress');
  const nextAction = openTasks[0] ?? null;
  const age = ageInDays(lead.created_at);
  const replyMinutes = minutesBetween(lead.created_at, lead.first_response_at);
  const isOpen = OPEN_STATUSES.has(lead.status);

  /*
   * Business, primary contact and owner are three different facts, listed as
   * three labelled facts. Where there is no contact person the value is an em
   * dash: a business captured without one has no human to name, and filling the
   * gap with the company name is exactly the confusion `identifyLead` exists to
   * prevent.
   */
  const facts: MetaFact[] = [
    {
      key: 'contact',
      label: 'Primary contact',
      value: contact ?? <span className="text-muted-foreground">Not provided</span>,
    },
    {
      key: 'phone',
      label: 'Phone',
      testId: 'lead-phone',
      value: lead.phone ? <span className="tabular">{lead.phone}</span> : <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'email',
      label: 'Email',
      testId: 'lead-email',
      value: lead.email ?? <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'owner',
      label: 'Owner',
      value: owner ? (
        owner.full_name
      ) : (
        <MissingValue>Unassigned</MissingValue>
      ),
    },
    { key: 'source', label: 'Source', value: lead.source.replace(/_/g, ' ') },
    { key: 'status', label: 'Status', value: STATUS_LABEL[lead.status] ?? lead.status },
  ];

  return (
    <div className="space-y-6">
      <p>
        <Link
          href="/leads"
          className="text-[13px] text-muted-foreground underline-offset-2 hover:underline"
        >
          &larr; All prospects
        </Link>
      </p>

      <RecordHeader
        subject={business}
        subjectTestId="lead-name"
        marker={
          capture.demo_data ? (
            <LabelChip data-testid="demo-marker" title="An invented business, not a real prospect">
              sample
            </LabelChip>
          ) : null
        }
        facts={facts}
      />

      <div className="flex flex-col gap-8 min-[1100px]:flex-row min-[1100px]:items-start">
        {/* The narrative: what they want, whether anybody answered, what happened. */}
        <div className="min-w-0 flex-1 space-y-8">
          {/*
            The most important sentence on the page. Not a card and not a metric:
            it is the one fact that decides whether this prospect is being
            neglected, and it is the same fact the Today figure counts.
          */}
          <section className="space-y-1.5 border-b border-border pb-5">
            <p data-testid="lead-first-response" className="text-sm">
              {lead.first_response_at ? (
                <>
                  <span className="text-muted-foreground">First reply: </span>
                  {replyMinutes === null ? (
                    'recorded'
                  ) : (
                    <>
                      <span className="font-medium text-foreground" data-testid="lead-response-time">
                        {duration(replyMinutes)}
                      </span>
                      <span className="text-muted-foreground">
                        {' '}
                        after the enquiry arrived, on {formatDate(lead.first_response_at)}
                      </span>
                    </>
                  )}
                </>
              ) : isOpen ? (
                // The state is emphasised; the explanation of it is not.
                //
                // The sentence after it is kept, shortened, because it is the one
                // piece of instruction on this page that prevents a wrong action:
                // people assume assigning or scoring a prospect counts as
                // answering them, and it does not. Everything else that merely
                // described the interface has gone.
                <span data-testid="lead-awaiting-response">
                  <span className="font-medium text-critical">Waiting for a first reply.</span>
                  <span className="text-muted-foreground">
                    {' '}
                    Only contact that actually reached them counts &mdash; assigning or scoring does
                    not.
                  </span>
                </span>
              ) : (
                <span className="text-muted-foreground">No first reply was ever recorded.</span>
              )}
            </p>

            <p data-testid="lead-next-action" className="text-sm">
              {nextAction ? (
                <>
                  <span className="text-muted-foreground">Next action: </span>
                  <span className="text-foreground">{nextAction.title}</span>
                  {nextAction.is_overdue ? (
                    <StatusText tone="critical" className="ml-2">
                      overdue
                    </StatusText>
                  ) : nextAction.due_at ? (
                    <span className="ml-2 text-muted-foreground">
                      due {formatDate(nextAction.due_at)}
                    </span>
                  ) : null}
                </>
              ) : (
                // "add one on the right" was both a lecture and a lie below
                // 1100px, where the rail is underneath rather than beside.
                <span className="font-medium text-critical">No follow-up is scheduled.</span>
              )}
            </p>

            <p className="text-[13px] text-muted-foreground">
              Came in via {lead.source.replace(/_/g, ' ')}
              {age === null ? '' : age === 0 ? ' today' : `, ${age} day${age === 1 ? '' : 's'} ago`}.
            </p>
          </section>

          <section aria-labelledby="requirement-heading" className="space-y-2">
            <SectionHeader id="requirement-heading" title="What they asked for" />
            <p data-testid="lead-requirement" className="max-w-reading text-sm text-foreground">
              {captureText(capture, 'requirement') ?? 'Nothing was recorded with this enquiry.'}
            </p>
            <dl className="flex flex-wrap gap-x-8 gap-y-1 pt-1 text-[13px]">
              {[
                { label: 'What they do', value: captureText(capture, 'industry') },
                { label: 'Area', value: captureText(capture, 'city') ?? captureText(capture, 'location') },
                { label: 'Website', value: captureText(capture, 'website') },
                { label: 'Team size', value: captureText(capture, 'employees') },
                { label: 'Rough value', value: captureText(capture, 'estimated_value_inr') },
              ]
                .filter((item) => item.value)
                .map((item) => (
                  <div key={item.label} className="flex items-baseline gap-1.5">
                    <dt className="text-muted-foreground">{item.label}</dt>
                    <dd className="text-foreground">{item.value}</dd>
                  </div>
                ))}
            </dl>
          </section>

          {/*
            The only control in Sangam that sends anything to a customer. Placed
            above the timeline it writes into, so the reply and its record read as
            one thing rather than two.
          */}
          <section className="border-t border-border pt-6">
            <WhatsAppReplyBox leadId={lead.id} phone={lead.phone} />
          </section>

          <section className="border-t border-border pt-6">
            <Timeline
              parent="leads"
              parentId={lead.id}
              entries={timelineResult.data?.timeline ?? []}
            />
          </section>
        </div>

        {/*
          The rail: the three things somebody changes while working this customer.

          It used to carry five sections at equal weight, and two of them were
          maintenance - a duplicate panel that said "Nothing flagged" on almost
          every record, and a form for correcting the contact's name. Both sat at
          the same visual weight as "who owns this" and "what happens next",
          which is how a rail stops being read at all.

          What is left is ordered by how often it is touched: the next action
          first, because that is the answer to "what do I do about this one".
        */}
        <aside className="w-full shrink-0 space-y-6 min-[1100px]:w-[20rem] min-[1100px]:border-l min-[1100px]:border-border min-[1100px]:pl-8 min-[1500px]:w-[22rem]">
          <section>
            <TaskPanel parent="leads" parentId={lead.id} tasks={tasks} />
          </section>

          <section aria-labelledby="ownership-heading" className="space-y-3 border-t border-border pt-6">
            <SectionHeader id="ownership-heading" title="Ownership" />
            <LeadOwner
              leadId={lead.id}
              version={lead.version}
              assigneeId={lead.assignee_id}
              members={members}
            />
          </section>

          <section className="border-t border-border pt-6">
            <LeadQualification
              leadId={lead.id}
              score={lead.qualification_score}
              category={lead.category}
            />
          </section>
        </aside>
      </div>

      {/*
        Record maintenance: correcting the contact's name, and merging a
        duplicate. Real capabilities, rarely the reason anybody opened this page.

        Below the workbench rather than hidden behind a click - both are one
        scroll away and neither has grown an extra step - but no longer competing
        with the conversation and the timeline for the same eye. The heading says
        what they are, so nobody has to guess why the page continues.
      */}
      <section
        aria-labelledby="maintenance-heading"
        className="space-y-5 border-t border-border pt-6"
      >
        <SectionHeader
          id="maintenance-heading"
          title="Record maintenance"
          description="Corrections and duplicate handling. Nothing here contacts the customer."
        />
        <div className="grid gap-8 min-[1100px]:grid-cols-2">
          <EditLeadForm lead={lead} />
          <DuplicateReview lead={lead} candidates={duplicates.data?.candidates ?? []} />
        </div>
      </section>
    </div>
  );
}
