import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { Card, PageHeader, StatusPill } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

/**
 * The Test Centre: what is real, what is half-built, and what needs an account
 * somebody has to go and open.
 *
 * Two rules keep this honest. Nothing here is hand-written optimism about a
 * module - the provider rows are probed live against the API on every page load,
 * so a channel that claims to be off really is off. And nothing links to a screen
 * that does not exist, because a Test button leading to a 404 teaches the owner
 * to distrust the whole page.
 */

type Status = 'usable' | 'partial' | 'gated' | 'backend-only' | 'not-built';

const STATUS_LABEL: Record<Status, string> = {
  usable: 'Usable',
  partial: 'Partly built',
  gated: 'Needs an account',
  'backend-only': 'No screen yet',
  'not-built': 'Not built',
};

const STATUS_TONE: Record<Status, 'success' | 'warning' | 'neutral' | 'danger'> = {
  usable: 'success',
  partial: 'warning',
  gated: 'neutral',
  'backend-only': 'neutral',
  'not-built': 'danger',
};

interface Feature {
  readonly name: string;
  readonly status: Status;
  readonly what: string;
  readonly href?: string;
}

const CORE: readonly Feature[] = [
  {
    name: 'Signing in',
    status: 'usable',
    what: 'Each business has its own workspace and cannot see anyone else’s records.',
    href: '/today',
  },
  {
    name: 'Today',
    status: 'usable',
    what: 'Counts what is slipping: no reply, no owner, no next action, overdue.',
    href: '/today',
  },
  {
    name: 'Prospects',
    status: 'usable',
    what: 'Every enquiry as a record, with who owns it and what happens next.',
    href: '/leads',
  },
  {
    name: 'Ownership',
    status: 'usable',
    what: 'Assign a prospect to a named person so nobody assumes somebody else called.',
    href: '/leads',
  },
  {
    name: 'Qualification',
    status: 'usable',
    what: 'Scores a prospect from what was captured, using rules. No AI needed.',
    href: '/leads',
  },
  {
    name: 'Follow-ups',
    status: 'usable',
    what: 'The promise queue, with overdue decided by the server, not the browser.',
    href: '/follow-ups',
  },
  {
    name: 'Customer history',
    status: 'usable',
    what: 'Calls, meetings and notes on the record, kept when a prospect becomes a customer.',
    href: '/leads',
  },
  {
    name: 'Contacts and companies',
    status: 'usable',
    what: 'The people and businesses behind the enquiries.',
    href: '/contacts',
  },
  {
    name: 'Deals',
    status: 'usable',
    what: 'The pipeline board, stage moves, and won/lost with a reason.',
    href: '/deals',
  },
  {
    name: 'Duplicate businesses',
    status: 'usable',
    what: 'An import matches on phone and email against what you already have, shows the evidence, and leaves the existing record untouched. Merging by hand is not finished.',
    href: '/leads',
  },
  {
    name: 'Team and invitations',
    status: 'partial',
    what: 'Colleagues can be invited; the invitation email cannot be delivered yet.',
  },
  {
    name: 'Adding a business by hand',
    status: 'usable',
    what: 'Name, phone and one line is enough; the rest is optional and can wait.',
    href: '/leads',
  },
  {
    name: 'Importing a prospect list',
    status: 'usable',
    what: 'CSV only. Preview, column mapping, cleaned-up values, duplicate and unusable rows all shown before anything is saved.',
    href: '/leads',
  },
  {
    name: 'Recording outreach you made yourself',
    status: 'usable',
    what: 'Log the call or message you made outside Sangam, with the outcome and the next action, in one go.',
    href: '/leads',
  },
  {
    name: 'Reports',
    status: 'partial',
    what: 'Charts render, but the numbers have not been checked against the records yet.',
    href: '/analytics',
  },
  {
    name: 'Appointments',
    status: 'partial',
    what: 'Bookings can be recorded. No calendar is connected, so nothing syncs.',
    href: '/appointments',
  },
  {
    name: 'Documents and files',
    status: 'gated',
    what: 'Needs cloud file storage, which is not set up.',
  },
  {
    name: 'Payments',
    status: 'gated',
    what: 'Needs a Razorpay account and their approval.',
  },
  {
    name: 'Automations',
    status: 'backend-only',
    what: 'The rules engine runs, but there is no screen to build a rule.',
  },
  {
    name: 'AI assistant',
    status: 'gated',
    what: 'Needs a paid model provider. Everything above works without it, on purpose.',
  },
];

const MEASUREMENTS: readonly { name: string; source: string; trusted: boolean }[] = [
  {
    name: 'Waiting for a first reply',
    source: 'Prospects with no outbound call, email or message logged against them.',
    trusted: true,
  },
  {
    name: 'Time to first reply',
    source: 'The gap between the enquiry arriving and that first outbound contact.',
    trusted: true,
  },
  {
    name: 'Typical time to first reply',
    source: 'The middle value across every answered enquiry you can see.',
    trusted: true,
  },
  {
    name: 'Overdue follow-ups',
    source: 'Follow-ups past their due date, judged by the server clock, not the browser.',
    trusted: true,
  },
  {
    name: 'Unassigned prospects',
    source: 'Open prospects with nobody’s name against them.',
    trusted: true,
  },
  {
    name: 'No next action',
    source: 'Open prospects with no follow-up scheduled.',
    trusted: true,
  },
  {
    name: 'Open pipeline value',
    source: 'The total of deals not yet won or lost. A total, not a forecast.',
    trusted: true,
  },
  {
    name: 'Charts on the Reports page',
    source: 'Not yet reconciled against the underlying records. Do not quote these.',
    trusted: false,
  },
];

const SCENARIOS: readonly { title: string; steps: string; href: string }[] = [
  {
    title: 'A new enquiry arrives and gets picked up',
    steps: 'Open Prospects, add one, give it an owner, score it, and set the next action.',
    href: '/leads',
  },
  {
    title: 'Nobody has replied to these enquiries',
    steps: 'Today shows them with how long they have waited. Open one and log the call.',
    href: '/leads?filter=awaiting',
  },
  {
    title: 'Prove the waiting count cannot be gamed',
    steps:
      'Open a waiting prospect. Assign it, score it, add a follow-up and a note — it still says waiting. Only logging a real call, email or message clears it.',
    href: '/leads?filter=awaiting',
  },
  {
    title: 'A promise was missed',
    steps: 'Follow-ups, filtered to Overdue. Close one and watch the Today count drop.',
    href: '/follow-ups?filter=overdue',
  },
  {
    title: 'The same person enquired twice',
    steps: 'Open Farhan Qureshi. The website chat enquiry is flagged as a likely duplicate.',
    href: '/leads',
  },
  {
    title: 'Import a list of businesses to approach',
    steps:
      'Import: download the template, put three businesses in it, upload. Anything you already have is shown before it saves, and is left alone.',
    href: '/sangam/imports',
  },
  {
    title: 'A deal was won, and one was lost',
    steps: 'The board shows both, and the lost one records why.',
    href: '/deals',
  },
];

interface ChannelRow {
  readonly channel: string;
  readonly ready: boolean;
  readonly flag: string;
}

/**
 * Probed on the server, never hand-written. `manual` is a first-class answer:
 * during a shadow pilot the calls and messages really are made by a person, and
 * dressing that up as a gap would misdescribe how the pilot works.
 */
interface ReadinessCheck {
  readonly key: string;
  readonly label: string;
  readonly state: 'ready' | 'attention' | 'manual';
  readonly detail: string;
}

interface ReadinessReport {
  readonly workspace: { readonly name: string | null; readonly kind: string | null };
  readonly checks: ReadinessCheck[];
  readonly summary: { readonly ready: number; readonly attention: number; readonly manual: number };
}

const READINESS_TONE: Record<ReadinessCheck['state'], 'success' | 'warning' | 'neutral'> = {
  ready: 'success',
  attention: 'warning',
  manual: 'neutral',
};

const READINESS_LABEL: Record<ReadinessCheck['state'], string> = {
  ready: 'Proven here',
  attention: 'Not yet',
  manual: 'Done by a person',
};

export default async function TestCenterPage(): Promise<JSX.Element> {
  // Probed, not asserted. If one of these calls fails the row says so rather than
  // quietly rendering a reassuring default.
  const [channelsResult, storageResult, calendarResult, readinessResult] = await Promise.all([
    apiFetch<{ channels: ChannelRow[] }>('/conversations/channels'),
    apiFetch<{ configured: boolean; blocker?: string | null }>('/files/storage-status'),
    apiFetch<{ enabled: boolean; blocker?: string | null }>('/appointments/calendar-sync'),
    apiFetch<ReadinessReport>('/tenant/pilot-readiness'),
  ]);

  const readiness = readinessResult.data ?? null;
  const channels = channelsResult.data?.channels ?? [];
  const storageOk = storageResult.data?.configured === true;
  const calendarOk = calendarResult.data?.enabled === true;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Test Centre"
        description="An internal page for the founders. It says what is genuinely usable, what is half-built, and what needs an outside account. It is not visible to customers."
      />

      <Card>
        <h2 className="font-medium">
          What we currently trust: founder prospecting, follow-up and leakage prevention
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Add or import a business &rarr; spot the ones you already have &rarr; give it an owner
          &rarr; see who has never been contacted &rarr; record the call you made &rarr; schedule
          what happens next &rarr; watch it appear on your day. This is the one path built end to
          end and checked in a browser. Everything else on this page is supporting it or not ready.
        </p>
        <p className="mt-3 rounded-md border border-dashed border-border p-3 text-sm">
          <span className="font-medium">Sangam does not send anything.</span> You make the call,
          send the WhatsApp message or write the email yourself, on your own phone or laptop, and
          then record here what happened. Everything on the Today screen is counted from what you
          recorded. Automatic sending needs a WhatsApp or email account that nobody has opened yet
          &mdash; see the table at the bottom of this page.
        </p>
        <p className="mt-3 text-sm">
          <Link href="/today" className="text-primary underline-offset-2 hover:underline">
            Start at Today
          </Link>
        </p>
      </Card>

      {/* The distinction the founders asked for: which figures come from people
          using the product, and which are still assumptions. */}
      {/* Pilot readiness, probed on every load. This is the page a founder opens
          before handing a workspace to a real business, so a row that cannot be
          confirmed says "not yet" rather than quietly rendering something
          reassuring. */}
      <section aria-labelledby="pilot-heading" className="space-y-3">
        <h2 id="pilot-heading" className="text-sm font-medium text-muted-foreground">
          Pilot readiness
        </h2>
        {readiness ? (
          <Card className="overflow-x-auto p-0" data-testid="pilot-readiness">
            <p className="px-5 pt-4 text-sm text-muted-foreground">
              Checked against{' '}
              <span className="font-medium text-foreground">
                {readiness.workspace.name ?? 'this workspace'}
              </span>{' '}
              just now &mdash; {readiness.summary.ready} proven, {readiness.summary.attention} not
              yet, {readiness.summary.manual} done by a person during a shadow pilot.
            </p>
            <table className="mt-3 w-full text-left text-sm">
              <caption className="sr-only">Pilot readiness checks</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th scope="col" className="px-5 py-3">
                    Check
                  </th>
                  <th scope="col" className="px-5 py-3">
                    What is true right now
                  </th>
                  <th scope="col" className="px-5 py-3">
                    State
                  </th>
                </tr>
              </thead>
              <tbody data-testid="pilot-readiness-rows">
                {readiness.checks.map((check) => (
                  <tr
                    key={check.key}
                    data-testid={`readiness-${check.key}`}
                    data-state={check.state}
                    className="border-b border-border/60"
                  >
                    <td className="px-5 py-3 font-medium">{check.label}</td>
                    <td className="px-5 py-3 text-muted-foreground">{check.detail}</td>
                    <td className="px-5 py-3">
                      <StatusPill tone={READINESS_TONE[check.state]}>
                        {READINESS_LABEL[check.state]}
                      </StatusPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-5 py-4 text-xs text-muted-foreground">
              &ldquo;Done by a person&rdquo; is not a gap. In a shadow pilot the business keeps
              making its own calls and sending its own messages; Sangam coordinates and measures
              the work rather than performing it.
            </p>
          </Card>
        ) : (
          <Card data-testid="pilot-readiness-unavailable">
            <p className="text-sm text-muted-foreground">
              Pilot readiness could not be checked. That is itself the answer: treat this workspace
              as not ready until this section loads.
            </p>
          </Card>
        )}
      </section>

      <Card>
        <h2 className="font-medium">Which numbers come from real use</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          These are counted from what people actually did in Sangam. Each one can be traced to
          records you can open and read.
        </p>
        <table className="mt-4 w-full text-left text-sm">
          <caption className="sr-only">Measurement sources</caption>
          <thead>
            <tr className="border-b border-border text-xs uppercase text-muted-foreground">
              <th scope="col" className="py-2 pr-4">
                Measurement
              </th>
              <th scope="col" className="py-2 pr-4">
                Where it comes from
              </th>
              <th scope="col" className="py-2">
                Trust
              </th>
            </tr>
          </thead>
          <tbody data-testid="measurement-rows">
            {MEASUREMENTS.map((row) => (
              <tr key={row.name} className="border-b border-border/60">
                <td className="py-2 pr-4 font-medium">{row.name}</td>
                <td className="py-2 pr-4 text-muted-foreground">{row.source}</td>
                <td className="py-2">
                  <StatusPill tone={row.trusted ? 'success' : 'warning'}>
                    {row.trusted ? 'From real use' : 'Not checked'}
                  </StatusPill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-4 text-sm text-muted-foreground">
          &ldquo;Waiting for a first reply&rdquo; only clears when somebody records an actual call,
          email or message <em>out</em> to the customer. Assigning a prospect, scoring it, writing
          an internal note, scheduling a follow-up, or logging a call that came <em>in</em> all
          leave it waiting &mdash; because none of those means the customer heard back.
        </p>
      </Card>

      <Card className="border-dashed">
        <h2 className="font-medium">About the data you are looking at</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The Sangam workspace is filled with{' '}
          <span className="font-medium text-foreground">made-up but realistic</span> Bengaluru
          businesses so the screens can be judged as they would look in use. None of these people
          exist and nothing has been sent to anybody. Real prospects can be added alongside them.
        </p>
      </Card>

      <section aria-labelledby="features-heading" className="space-y-3">
        <h2 id="features-heading" className="text-sm font-medium text-muted-foreground">
          What works
        </h2>
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Feature status</caption>
            <thead>
              <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                <th scope="col" className="px-5 py-3">
                  Feature
                </th>
                <th scope="col" className="px-5 py-3">
                  Status
                </th>
                <th scope="col" className="px-5 py-3">
                  What it does
                </th>
                <th scope="col" className="px-5 py-3">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody data-testid="feature-rows">
              {CORE.map((feature) => (
                <tr key={feature.name} className="border-b border-border/60">
                  <td className="px-5 py-3 font-medium">{feature.name}</td>
                  <td className="px-5 py-3">
                    <StatusPill tone={STATUS_TONE[feature.status]}>
                      {STATUS_LABEL[feature.status]}
                    </StatusPill>
                  </td>
                  <td className="px-5 py-3 text-muted-foreground">{feature.what}</td>
                  <td className="px-5 py-3 text-right">
                    {feature.href ? (
                      <Link
                        href={feature.href}
                        className="rounded-md border border-border px-3 py-1 text-xs hover:bg-surface-sunken"
                      >
                        Open
                      </Link>
                    ) : (
                      <span className="text-xs text-muted-foreground">No screen</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>

      <section aria-labelledby="scenarios-heading" className="space-y-3">
        <h2 id="scenarios-heading" className="text-sm font-medium text-muted-foreground">
          Things to try
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {SCENARIOS.map((scenario) => (
            <Card key={scenario.title} interactive>
              <h3 className="font-medium">{scenario.title}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{scenario.steps}</p>
              <p className="mt-3">
                <Link
                  href={scenario.href}
                  className="text-sm text-primary underline-offset-2 hover:underline"
                >
                  Try it
                </Link>
              </p>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="providers-heading" className="space-y-3">
        <h2 id="providers-heading" className="text-sm font-medium text-muted-foreground">
          Outside services, checked live just now
        </h2>
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">External provider status</caption>
            <thead>
              <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                <th scope="col" className="px-5 py-3">
                  Service
                </th>
                <th scope="col" className="px-5 py-3">
                  Can it be used?
                </th>
                <th scope="col" className="px-5 py-3">
                  Why not
                </th>
              </tr>
            </thead>
            <tbody data-testid="provider-rows">
              {channels.length === 0 ? (
                <tr className="border-b border-border/60">
                  <td className="px-5 py-3">Messaging channels</td>
                  <td className="px-5 py-3">
                    <StatusPill tone="neutral">Unknown</StatusPill>
                  </td>
                  <td className="px-5 py-3 text-muted-foreground">
                    The check did not return an answer.
                  </td>
                </tr>
              ) : (
                channels.map((channel) => (
                  <tr key={channel.channel} className="border-b border-border/60">
                    <td className="px-5 py-3 font-medium capitalize">
                      {channel.channel.replace(/_/g, ' ')}
                    </td>
                    <td className="px-5 py-3">
                      <StatusPill tone={channel.ready ? 'success' : 'neutral'}>
                        {channel.ready ? 'Yes' : 'No'}
                      </StatusPill>
                    </td>
                    <td className="px-5 py-3 text-muted-foreground">
                      {channel.ready
                        ? '—'
                        : 'No credential, and the switch that turns it on is off.'}
                    </td>
                  </tr>
                ))
              )}
              <tr className="border-b border-border/60">
                <td className="px-5 py-3 font-medium">File storage</td>
                <td className="px-5 py-3">
                  <StatusPill tone={storageOk ? 'success' : 'neutral'}>
                    {storageOk ? 'Yes' : 'No'}
                  </StatusPill>
                </td>
                <td className="px-5 py-3 text-muted-foreground">
                  {storageOk
                    ? '—'
                    : (storageResult.data?.blocker ?? 'No cloud storage is configured.')}
                </td>
              </tr>
              <tr>
                <td className="px-5 py-3 font-medium">Calendar sync</td>
                <td className="px-5 py-3">
                  <StatusPill tone={calendarOk ? 'success' : 'neutral'}>
                    {calendarOk ? 'Yes' : 'No'}
                  </StatusPill>
                </td>
                <td className="px-5 py-3 text-muted-foreground">
                  {calendarOk
                    ? '—'
                    : (calendarResult.data?.blocker ?? 'No calendar account is connected.')}
                </td>
              </tr>
            </tbody>
          </table>
        </Card>
        <p className="text-xs text-muted-foreground">
          Nothing above can be switched on from inside Sangam. Each one needs an account, a
          verification, or a commercial agreement that a person has to obtain.
        </p>
      </section>
    </div>
  );
}
