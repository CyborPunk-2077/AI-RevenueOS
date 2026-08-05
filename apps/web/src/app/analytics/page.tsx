import { apiFetch } from '@/lib/session';
import { money } from '@/lib/money';
import { PageHeader, Stat } from '@/features/ui/primitives';
import { LeadSourceMix, PipelineByStage, WonOverTime } from '@/features/analytics/charts';

export const dynamic = 'force-dynamic';

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
  readonly appointments: { readonly scheduled: number; readonly completed: number; readonly no_show: number };
  readonly conversations: { readonly inbound: number; readonly outbound: number; readonly failed: number };
  readonly sla: { readonly tracked: number; readonly resolved: number; readonly breached: number; readonly breach_rate: number };
  readonly team_performance: readonly { readonly assignee_id: string | null; readonly deals_won: number; readonly won_amount_minor: number; readonly open_deals: number }[];
  readonly lead_sources: readonly { readonly source: string; readonly count: number }[];
  readonly pipeline_by_stage: readonly {
    readonly stage: string;
    readonly amount_minor: number;
    readonly deal_count: number;
  }[];
  readonly daily: readonly { readonly day: string; readonly leads: number; readonly won_amount_minor: number }[];
  readonly scope: string;
}

interface PageProps {
  readonly searchParams: { readonly start?: string; readonly end?: string };
}

export default async function AnalyticsPage({ searchParams }: PageProps): Promise<JSX.Element> {
  const query = new URLSearchParams();
  if (searchParams.start) query.set('start', searchParams.start);
  if (searchParams.end) query.set('end', searchParams.end);
  const result = await apiFetch<Dashboard>(`/analytics/dashboard?${query.toString()}`);

  if (!result.ok || !result.data) {
    return (
      <p role="alert" className="rounded border border-destructive p-4 text-sm text-destructive">
        {result.error ?? 'Could not load analytics.'}
      </p>
    );
  }

  const data = result.data;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Analytics"
        description={`Tenant and role scoped · ${data.period.timezone} · ${data.scope}`}
      />

      <form method="get" className="surface flex flex-wrap items-end gap-4 p-4">
        <label className="grid gap-1 text-sm">
          Start date
          <input className="field" type="date" name="start" defaultValue={data.period.start} />
        </label>
        <label className="grid gap-1 text-sm">
          End date
          <input className="field" type="date" name="end" defaultValue={data.period.end} />
        </label>
        <button className="btn btn-primary" type="submit">
          Apply range
        </button>
      </form>

      <div
        className="dashboard-grid stagger grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        data-testid="analytics-totals"
      >
        <Stat label="Leads" value={String(data.leads.created)} />
        <Stat label="Converted" value={String(data.leads.converted)} />
        <Stat label="Won revenue" value={money(data.revenue.won_amount_minor)} />
        <Stat label="Open pipeline" value={money(data.revenue.pipeline_amount_minor)} />
        <Stat label="Appointments" value={String(data.appointments.scheduled)} />
        <Stat label="Inbound messages" value={String(data.conversations.inbound)} />
        <Stat label="Captured payments" value={money(data.revenue.payments_captured_minor)} />
        <Stat label="Refunds" value={money(data.revenue.refunds_minor)} />
        <Stat label="Hot leads" value={String(data.leads.hot)} />
        <Stat label="SLA breaches" value={String(data.sla.breached)} />
      </div>

      {/* The chart components carry their own table equivalent, so the data is
          still reachable without sight of the graphic. The test ids the suites
          select on are preserved on wrappers. */}
      <section className="grid gap-6 lg:grid-cols-2">
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

      <section className="surface p-5">
        <h2 className="font-medium">Team performance</h2>
        {data.team_performance.length ? (
          <div className="mt-3 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead><tr><th className="py-2">Assignee</th><th>Won deals</th><th>Won revenue</th><th>Open deals</th></tr></thead>
              <tbody data-testid="team-performance">
                {data.team_performance.map((item) => (
                  <tr key={item.assignee_id ?? 'unassigned'} className="row-hover border-t border-border/60">
                    <td className="py-2 font-mono text-xs">{item.assignee_id ?? 'Unassigned'}</td>
                    <td>{item.deals_won}</td><td>{money(item.won_amount_minor)}</td><td>{item.open_deals}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="mt-3 text-sm text-muted-foreground">No assigned deals in this range.</p>}
      </section>

      <aside className="rounded border border-dashed p-4 text-sm" data-testid="exports-disabled">
        <p className="font-medium">Private exports are unavailable.</p>
        <p className="mt-1 text-muted-foreground">
          AWS export storage is not activated. No download or placeholder file is created.
        </p>
        <button className="mt-3 rounded border px-4 py-2" type="button" disabled>
          Export CSV
        </button>
      </aside>
    </div>
  );
}
