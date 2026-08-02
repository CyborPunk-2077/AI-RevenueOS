import { apiFetch } from '@/lib/session';
import { money } from '@/lib/money';

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
      <section>
        <h1 className="text-xl font-semibold">Analytics</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tenant and role scoped · {data.period.timezone} · {data.scope}
        </p>
      </section>

      <form method="get" className="flex flex-wrap items-end gap-4 rounded border p-4">
        <label className="grid gap-1 text-sm">
          Start date
          <input className="rounded border px-3 py-2" type="date" name="start" defaultValue={data.period.start} />
        </label>
        <label className="grid gap-1 text-sm">
          End date
          <input className="rounded border px-3 py-2" type="date" name="end" defaultValue={data.period.end} />
        </label>
        <button className="rounded bg-primary px-4 py-2 text-primary-foreground" type="submit">
          Apply range
        </button>
      </form>

      <dl className="dashboard-grid grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="analytics-totals">
        <Metric label="Leads" value={String(data.leads.created)} />
        <Metric label="Converted" value={String(data.leads.converted)} />
        <Metric label="Won revenue" value={money(data.revenue.won_amount_minor)} />
        <Metric label="Open pipeline" value={money(data.revenue.pipeline_amount_minor)} />
        <Metric label="Appointments" value={String(data.appointments.scheduled)} />
        <Metric label="Inbound messages" value={String(data.conversations.inbound)} />
        <Metric label="Captured payments" value={money(data.revenue.payments_captured_minor)} />
        <Metric label="Refunds" value={money(data.revenue.refunds_minor)} />
        <Metric label="Hot leads" value={String(data.leads.hot)} />
        <Metric label="SLA breaches" value={String(data.sla.breached)} />
      </dl>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded border p-4">
          <h2 className="font-medium">Lead sources</h2>
          {data.lead_sources.length ? (
            <ul className="mt-3 space-y-2 text-sm" data-testid="lead-sources">
              {data.lead_sources.map((item) => (
                <li key={item.source} className="flex justify-between">
                  <span>{item.source}</span><strong>{item.count}</strong>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-muted-foreground">No leads in this range.</p>}
        </div>
        <div className="rounded border p-4">
          <h2 className="font-medium">Daily trend</h2>
          <div className="mt-3 max-h-64 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead><tr><th className="py-2">Day</th><th>Leads</th><th>Won</th></tr></thead>
              <tbody data-testid="daily-trend">
                {data.daily.map((item) => (
                  <tr key={item.day} className="border-t">
                    <td className="py-2">{item.day}</td><td>{item.leads}</td><td>{money(item.won_amount_minor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="rounded border p-4">
        <h2 className="font-medium">Team performance</h2>
        {data.team_performance.length ? (
          <div className="mt-3 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead><tr><th className="py-2">Assignee</th><th>Won deals</th><th>Won revenue</th><th>Open deals</th></tr></thead>
              <tbody data-testid="team-performance">
                {data.team_performance.map((item) => (
                  <tr key={item.assignee_id ?? 'unassigned'} className="border-t">
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

function Metric({ label, value }: { readonly label: string; readonly value: string }): JSX.Element {
  return <div className="rounded border p-4"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="text-lg font-medium">{value}</dd></div>;
}
