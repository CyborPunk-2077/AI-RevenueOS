import { apiFetch } from '@/lib/session';
import { DealBoard, type BoardStage } from '@/features/crm/deal-board';
import { money } from '@/lib/money';
import { NewDealForm } from '@/features/crm/new-deal-form';

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
      <p role="alert" className="rounded border border-destructive p-4 text-sm text-destructive">
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

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold">Deals</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pipeline: {board.pipeline.name}
        </p>
      </section>

      <dl className="grid gap-4 sm:grid-cols-4" data-testid="pipeline-totals">
        <div className="rounded border p-4">
          <dt className="text-xs text-muted-foreground">Open deals</dt>
          <dd className="text-lg font-medium">{board.totals.open_count}</dd>
        </div>
        <div className="rounded border p-4">
          <dt className="text-xs text-muted-foreground">Open value</dt>
          <dd className="text-lg font-medium">{money(board.totals.open_value_minor)}</dd>
        </div>
        <div className="rounded border p-4">
          <dt className="text-xs text-muted-foreground">Weighted</dt>
          <dd className="text-lg font-medium" data-testid="weighted-value">
            {money(board.totals.weighted_value_minor)}
          </dd>
        </div>
        <div className="rounded border p-4">
          <dt className="text-xs text-muted-foreground">Won</dt>
          <dd className="text-lg font-medium">{money(board.totals.won_value_minor)}</dd>
        </div>
      </dl>

      <NewDealForm accounts={accounts} contacts={contacts} />

      <DealBoard stages={board.stages} />
    </div>
  );
}
