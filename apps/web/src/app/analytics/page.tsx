import { apiFetch } from '@/lib/session';
import { money } from '@/lib/money';
import { LeadSourceMix, PipelineByStage, WonOverTime } from '@/features/analytics/charts';
import { Button } from '@/features/ui/controls';
import { DataTable, TableEmpty, type Column } from '@/features/ui/data-table';
import { duration } from '@/features/ui/format';
import { MetricStrip, type Metric } from '@/features/ui/metric-strip';
import { PageHeader, SectionHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

/**
 * Reporting, and the one thing that must never come off this page.
 *
 * **These figures have not been reconciled against the underlying records.** The
 * charts render, the sums add up inside themselves, and nobody has checked that
 * "won revenue" here equals the deals somebody can open and count. That is
 * recorded as a high-priority defect in `docs/PROJECT-STATE.md`, and until it is
 * closed the caveat belongs on the screen rather than in a document nobody
 * reading the screen has open.
 *
 * Analytics is not Today. It may be dense, and it may take a moment to read;
 * what it may not do is imply a precision it has not earned.
 */

interface Dashboard {
  readonly period: { readonly start: string; readonly end: string; readonly timezone: string };
  readonly leads: {
    readonly created: number;
    readonly qualified: number;
    readonly converted: number;
    readonly hot: number;
    readonly warm: number;
    readonly cold: number;
    readonly conversion_rate: number;
    readonly avg_first_response_seconds: number | null;
  };
  readonly revenue: {
    readonly deals_won: number;
    readonly deals_lost: number;
    readonly won_amount_minor: number;
    readonly pipeline_amount_minor: number;
    readonly payments_captured_minor: number;
    readonly refunds_minor: number;
  };
  readonly appointments: {
    readonly scheduled: number;
    readonly completed: number;
    readonly no_show: number;
  };
  readonly conversations: {
    readonly inbound: number;
    readonly outbound: number;
    readonly failed: number;
  };
  readonly sla: {
    readonly tracked: number;
    readonly resolved: number;
    readonly breached: number;
    readonly breach_rate: number;
  };
  readonly team_performance: readonly {
    readonly assignee_id: string | null;
    readonly deals_won: number;
    readonly won_amount_minor: number;
    readonly open_deals: number;
  }[];
  readonly lead_sources: readonly { readonly source: string; readonly count: number }[];
  readonly pipeline_by_stage: readonly {
    readonly stage: string;
    readonly amount_minor: number;
    readonly deal_count: number;
  }[];
  readonly daily: readonly {
    readonly day: string;
    readonly leads: number;
    readonly won_amount_minor: number;
  }[];
  readonly scope: string;
}

interface Member {
  readonly id: string;
  readonly full_name: string;
}

type TeamRow = Dashboard['team_performance'][number] & { name: string };

interface PageProps {
  readonly searchParams: { readonly start?: string; readonly end?: string };
}

/** A labelled pair, for the sections that are counts rather than a series. */
function Figures({
  items,
  caption,
}: {
  items: Array<{ label: string; value: string }>;
  caption?: string;
}): JSX.Element {
  return (
    <>
      <dl className="grid gap-x-8 gap-y-2 sm:grid-cols-2 min-[1100px]:grid-cols-3">
        {items.map((item) => (
          <div
            key={item.label}
            className="flex items-baseline justify-between gap-4 border-b border-border py-1.5"
          >
            <dt className="text-[13px] text-muted-foreground">{item.label}</dt>
            <dd className="text-sm font-medium tabular text-foreground">{item.value}</dd>
          </div>
        ))}
      </dl>
      {caption ? <p className="text-[13px] text-muted-foreground">{caption}</p> : null}
    </>
  );
}

export default async function AnalyticsPage({ searchParams }: PageProps): Promise<JSX.Element> {
  const query = new URLSearchParams();
  if (searchParams.start) query.set('start', searchParams.start);
  if (searchParams.end) query.set('end', searchParams.end);

  const [result, membersResult] = await Promise.all([
    apiFetch<Dashboard>(`/analytics/dashboard?${query.toString()}`),
    // So the team table names people rather than printing their UUIDs.
    apiFetch<{ members: Member[] }>('/users/members'),
  ]);

  if (!result.ok || !result.data) {
    return (
      <p
        role="alert"
        className="max-w-reading rounded border border-critical/40 bg-critical-soft px-3 py-2 text-sm text-critical"
      >
        {result.error ?? 'Could not load analytics.'}
      </p>
    );
  }

  const data = result.data;
  const owners = new Map((membersResult.data?.members ?? []).map((m) => [m.id, m.full_name]));

  const headline: Metric[] = [
    { key: 'leads', label: 'Leads created', value: String(data.leads.created) },
    { key: 'converted', label: 'Converted', value: String(data.leads.converted) },
    { key: 'won', label: 'Won revenue', value: money(data.revenue.won_amount_minor) },
    { key: 'pipeline', label: 'Open pipeline', value: money(data.revenue.pipeline_amount_minor) },
    {
      key: 'response',
      label: 'Average first response',
      value:
        data.leads.avg_first_response_seconds === null
          ? '—'
          : duration(Math.round(data.leads.avg_first_response_seconds / 60)),
    },
  ];

  const teamRows: TeamRow[] = data.team_performance.map((item) => ({
    ...item,
    name: item.assignee_id ? (owners.get(item.assignee_id) ?? 'Another colleague') : 'Unassigned',
  }));

  const teamColumns: Array<Column<TeamRow>> = [
    {
      key: 'name',
      header: 'Owner',
      width: '40%',
      cell: (row) => <span className="block truncate font-medium text-foreground">{row.name}</span>,
    },
    {
      key: 'won',
      header: 'Won deals',
      align: 'right',
      width: '18%',
      cell: (row) => <span className="text-secondary-foreground">{row.deals_won}</span>,
    },
    {
      key: 'revenue',
      header: 'Won revenue',
      align: 'right',
      width: '24%',
      cell: (row) => (
        <span className="text-secondary-foreground">{money(row.won_amount_minor)}</span>
      ),
    },
    {
      key: 'open',
      header: 'Open deals',
      align: 'right',
      width: '18%',
      cell: (row) => <span className="text-secondary-foreground">{row.open_deals}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        description={`${data.period.start} to ${data.period.end} · ${data.period.timezone} · scoped to ${data.scope}`}
      />

      {/*
        The caveat, on the page and above the numbers rather than beneath them.
        It is the single most important sentence here: everything below is
        internally consistent and has never been checked against the records it
        claims to summarise.
      */}
      <div
        role="note"
        data-testid="analytics-unreconciled"
        className="max-w-reading rounded border border-warning/50 bg-warning-soft px-3.5 py-2.5"
      >
        <p className="text-[13px] font-medium text-foreground">
          These figures have not been reconciled against the underlying records.
        </p>
        <p className="mt-1 text-[13px] text-secondary-foreground">
          They are internally consistent and nobody has yet checked them against the deals,
          prospects and payments they summarise. Treat them as indicative for internal use, and do
          not show them to a customer or quote them in a proposal.
        </p>
      </div>

      <form method="get" className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor="start" className="block text-[13px] font-medium text-foreground">
            Start date
          </label>
          <input
            id="start"
            className="field mt-1 w-auto"
            type="date"
            name="start"
            defaultValue={data.period.start}
          />
        </div>
        <div>
          <label htmlFor="end" className="block text-[13px] font-medium text-foreground">
            End date
          </label>
          <input
            id="end"
            className="field mt-1 w-auto"
            type="date"
            name="end"
            defaultValue={data.period.end}
          />
        </div>
        <Button variant="secondary" type="submit">
          Apply range
        </Button>
      </form>

      <div data-testid="analytics-totals">
        <MetricStrip metrics={headline} aria-label="Headline figures for this period" />
      </div>

      <section className="space-y-3 border-t border-border pt-6">
        <SectionHeader
          title="Prospects"
          description="How enquiries in this period were scored and what became of them."
        />
        <Figures
          items={[
            { label: 'Created', value: String(data.leads.created) },
            { label: 'Qualified', value: String(data.leads.qualified) },
            { label: 'Converted', value: String(data.leads.converted) },
            { label: 'Hot', value: String(data.leads.hot) },
            { label: 'Warm', value: String(data.leads.warm) },
            { label: 'Cold', value: String(data.leads.cold) },
            {
              label: 'Conversion rate',
              value: `${Math.round(data.leads.conversion_rate * 100)}%`,
            },
          ]}
        />
      </section>

      <section className="space-y-3 border-t border-border pt-6">
        <SectionHeader title="Revenue" description="Deals and money, over the same period." />
        <Figures
          items={[
            { label: 'Deals won', value: String(data.revenue.deals_won) },
            { label: 'Deals lost', value: String(data.revenue.deals_lost) },
            { label: 'Won value', value: money(data.revenue.won_amount_minor) },
            { label: 'Open pipeline', value: money(data.revenue.pipeline_amount_minor) },
            { label: 'Payments captured', value: money(data.revenue.payments_captured_minor) },
            { label: 'Refunds', value: money(data.revenue.refunds_minor) },
          ]}
          caption="Payments are provider-gated, so these two will read zero until Razorpay is live."
        />
      </section>

      <section className="space-y-3 border-t border-border pt-6">
        <SectionHeader
          title="Conversations and appointments"
          description="Message volume, and what happened to the meetings that were booked."
        />
        <Figures
          items={[
            { label: 'Inbound messages', value: String(data.conversations.inbound) },
            { label: 'Outbound messages', value: String(data.conversations.outbound) },
            { label: 'Failed sends', value: String(data.conversations.failed) },
            { label: 'Appointments scheduled', value: String(data.appointments.scheduled) },
            { label: 'Completed', value: String(data.appointments.completed) },
            { label: 'No-shows', value: String(data.appointments.no_show) },
          ]}
        />
      </section>

      <section className="space-y-3 border-t border-border pt-6">
        <SectionHeader
          title="Service levels"
          description="Only conversations with an SLA attached are counted here."
        />
        <Figures
          items={[
            { label: 'Tracked', value: String(data.sla.tracked) },
            { label: 'Resolved', value: String(data.sla.resolved) },
            { label: 'Breached', value: String(data.sla.breached) },
            { label: 'Breach rate', value: `${Math.round(data.sla.breach_rate * 100)}%` },
          ]}
        />
      </section>

      {/* The chart components carry their own table equivalent, so the data is
          still reachable without sight of the graphic. The test ids the suites
          select on are preserved on wrappers. */}
      <section className="grid gap-5 border-t border-border pt-6 min-[1100px]:grid-cols-2">
        <div data-testid="lead-sources">
          <LeadSourceMix
            rows={data.lead_sources.map((item) => ({ label: item.source, value: item.count }))}
          />
        </div>
        <div data-testid="daily-trend">
          <WonOverTime
            rows={data.daily.map((item) => ({
              label: item.day.slice(5),
              value: item.won_amount_minor,
            }))}
          />
        </div>
      </section>

      <section data-testid="pipeline-by-stage">
        <PipelineByStage
          rows={(data.pipeline_by_stage ?? []).map((item) => ({
            label: item.stage,
            value: item.amount_minor,
          }))}
        />
      </section>

      <section className="space-y-3 border-t border-border pt-6">
        <SectionHeader
          title="Team performance"
          description="Deals by the person who owns them."
        />
        <DataTable
          caption="Won and open deals by owner"
          columns={teamColumns}
          rows={teamRows}
          rowKey={(row) => row.assignee_id ?? 'unassigned'}
          bodyTestId="team-performance"
          stickyHeader={false}
          empty={
            <TableEmpty
              title="No assigned deals in this range"
              description="Deals appear here once they have an owner and fall inside the selected dates."
            />
          }
        />
      </section>

      <section
        className="space-y-2 border-t border-border pt-6"
        data-testid="exports-disabled"
      >
        <SectionHeader
          title="Export"
          description="Private exports are unavailable. AWS export storage is not activated, so no download and no placeholder file is created."
        />
        <Button variant="secondary" disabled>
          Export CSV
        </Button>
      </section>
    </div>
  );
}
