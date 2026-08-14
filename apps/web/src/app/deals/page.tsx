import { apiFetch } from '@/lib/session';
import { DealBoard, type BoardStage } from '@/features/crm/deal-board';
import { money } from '@/lib/money';
import { NewDealForm } from '@/features/crm/new-deal-form';
import { MetricStrip, type Metric } from '@/features/ui/metric-strip';
import { PageHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

interface Board {
  readonly pipeline: { readonly id: string; readonly name: string };
  readonly stages: BoardStage[];
  readonly totals: {
    readonly open_count: number;
    readonly open_value_minor: number;
    readonly weighted_value_minor: number;
    readonly won_value_minor: number;
  };
}

interface NamedContact {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
}

export default async function DealsPage(): Promise<JSX.Element> {
  const [boardResult, accountResult, contactResult] = await Promise.all([
    apiFetch<Board>('/deals/board'),
    apiFetch<{ accounts: { id: string; name: string }[] }>('/accounts?page_size=200'),
    apiFetch<{ contacts: NamedContact[] }>('/contacts?page_size=200'),
  ]);

  if (!boardResult.ok || !boardResult.data) {
    return (
      <p
        role="alert"
        className="max-w-reading rounded border border-critical/40 bg-critical-soft px-3 py-2 text-sm text-critical"
      >
        {boardResult.error ?? 'Could not load the pipeline.'}
      </p>
    );
  }

  const board = boardResult.data;
  const accounts = accountResult.data?.accounts ?? [];
  const contacts = (contactResult.data?.contacts ?? []).map((c) => ({
    id: c.id,
    name: `${c.first_name} ${c.last_name ?? ''}`.trim(),
  }));

  const totals: Metric[] = [
    { key: 'open', label: 'Open deals', value: String(board.totals.open_count) },
    { key: 'value', label: 'Open value', value: money(board.totals.open_value_minor) },
    {
      key: 'weighted',
      label: 'Weighted',
      value: money(board.totals.weighted_value_minor),
      hint: 'by stage probability',
      testId: 'weighted-value',
    },
    { key: 'won', label: 'Won', value: money(board.totals.won_value_minor) },
  ];

  return (
    <div className="space-y-5">
      {/* The pipeline's own name, which this used to print as the literal
          template string `{board.pipeline.name}`. */}
      <PageHeader
        title="Deals"
        description={`Pipeline: ${board.pipeline.name}`}
        actions={<NewDealForm accounts={accounts} contacts={contacts} />}
      />

      <div data-testid="pipeline-totals">
        <MetricStrip metrics={totals} aria-label="Pipeline totals" />
      </div>

      <DealBoard stages={board.stages} />
    </div>
  );
}
