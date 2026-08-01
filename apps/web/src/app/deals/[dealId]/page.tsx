import Link from 'next/link';
import { notFound } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { money } from '@/lib/money';

export const dynamic = 'force-dynamic';

interface Deal {
  readonly id: string;
  readonly title: string;
  readonly amount_minor: number;
  readonly currency: string;
  readonly probability: number;
  readonly status: string;
  readonly loss_reason: string | null;
  readonly stage_name: string | null;
  readonly contact_id: string | null;
  readonly contact_name: string | null;
  readonly account_id: string | null;
  readonly account_name: string | null;
  readonly closed_at: string | null;
}

export default async function DealDetailPage({
  params,
}: {
  params: { dealId: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<Deal>(`/deals/${params.dealId}`);
  if (!result.ok || !result.data) notFound();
  const deal = result.data;

  return (
    <div className="space-y-8">
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/deals" className="underline">Deals</Link>
      </nav>

      <section>
        <h1 className="text-xl font-semibold" data-testid="deal-title">{deal.title}</h1>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">Value</dt>
            <dd>{money(deal.amount_minor, deal.currency)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Stage</dt>
            <dd data-testid="deal-stage">{deal.stage_name ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Status</dt>
            <dd data-testid="deal-status">{deal.status}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Probability</dt>
            <dd>{deal.probability}%</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Account</dt>
            <dd>
              {deal.account_id && deal.account_name ? (
                <Link href={`/accounts/${deal.account_id}`} className="underline">
                  {deal.account_name}
                </Link>
              ) : ('—')}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Contact</dt>
            <dd>
              {deal.contact_id && deal.contact_name ? (
                <Link href={`/contacts/${deal.contact_id}`} className="underline">
                  {deal.contact_name}
                </Link>
              ) : ('—')}
            </dd>
          </div>
          {deal.loss_reason ? (
            <div className="sm:col-span-2">
              <dt className="text-muted-foreground">Loss reason</dt>
              <dd data-testid="loss-reason">{deal.loss_reason}</dd>
            </div>
          ) : null}
        </dl>
      </section>
    </div>
  );
}
