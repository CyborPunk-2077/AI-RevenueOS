'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { money } from '@/lib/money';

export interface BoardDeal {
  readonly id: string;
  readonly title: string;
  readonly amount_minor: number;
  readonly currency: string;
  readonly status: string;
  readonly stage_id: string;
  readonly account_name: string | null;
  readonly version: number;
}

export interface BoardStage {
  readonly id: string;
  readonly name: string;
  readonly probability: number;
  readonly is_lost: boolean;
  readonly deal_count: number;
  readonly value_minor: number;
  readonly deals: BoardDeal[];
}

/**
 * The pipeline as columns.
 *
 * Moving a deal is a server decision, not a client one: the API applies the
 * domain policy (required fields, direction limits, loss reasons) and can refuse.
 * So this sends the move and re-renders from the response rather than optimistically
 * repainting a card that may bounce back.
 */
export function DealBoard({ stages }: { stages: BoardStage[] }): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function move(deal: BoardDeal, stage: BoardStage): Promise<void> {
    setBusyId(deal.id);
    setError(null);

    // A lost stage needs a reason. Asking here keeps the request valid rather
    // than letting the server refuse something the user could have supplied.
    let lossReason: string | null = null;
    if (stage.is_lost) {
      lossReason = window.prompt(`Why was “${deal.title}” lost?`);
      if (!lossReason) {
        setBusyId(null);
        return;
      }
    }

    const response = await mutate(`/api/deals/${deal.id}/stage`, {
      method: 'POST',
      ifMatch: deal.version,
      body: { stage_id: stage.id, loss_reason: lossReason },
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      setError(payload.error?.message ?? 'Could not move that deal.');
      setBusyId(null);
      return;
    }
    setBusyId(null);
    router.refresh();
  }

  return (
    <div className="space-y-4">
      {error ? (
        <p role="alert" data-testid="board-error" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="deal-board">
        {stages.map((stage) => (
          <section
            key={stage.id}
            aria-labelledby={`stage-${stage.id}`}
            data-testid={`stage-${stage.name}`}
            className="rounded border p-3"
          >
            <h3 id={`stage-${stage.id}`} className="text-sm font-medium">
              {stage.name}
              <span className="ml-2 text-xs text-muted-foreground">{stage.deal_count}</span>
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">{money(stage.value_minor)}</p>

            <ul className="mt-3 space-y-2">
              {stage.deals.map((deal) => (
                <li key={deal.id} className="rounded border bg-background p-2 text-sm">
                  <Link href={`/deals/${deal.id}`} className="font-medium underline">
                    {deal.title}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {money(deal.amount_minor, deal.currency)}
                    {deal.account_name ? ` · ${deal.account_name}` : ''}
                  </p>
                  {deal.status !== 'open' ? (
                    <p className="mt-1 text-xs uppercase text-muted-foreground">{deal.status}</p>
                  ) : null}

                  <label htmlFor={`move-${deal.id}`} className="sr-only">
                    Move {deal.title} to another stage
                  </label>
                  <select
                    id={`move-${deal.id}`}
                    data-testid={`move-${deal.id}`}
                    value={deal.stage_id}
                    disabled={busyId === deal.id}
                    onChange={(event) => {
                      const target = stages.find((s) => s.id === event.target.value);
                      if (target && target.id !== deal.stage_id) void move(deal, target);
                    }}
                    className="mt-2 w-full rounded border px-2 py-1 text-xs"
                  >
                    {stages.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.name}
                      </option>
                    ))}
                  </select>
                </li>
              ))}
            </ul>

            {stage.deals.length === 0 ? (
              <p className="mt-3 text-xs text-muted-foreground">Empty</p>
            ) : null}
          </section>
        ))}
      </div>
    </div>
  );
}
