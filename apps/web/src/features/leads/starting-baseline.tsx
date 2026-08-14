'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';
import { formatDateTime } from '@/lib/dates';

/**
 * The workspace's "before" picture.
 *
 * This component is under a standing constraint that matters more than how it
 * looks: it may show what the numbers were at the start and what they are now,
 * and it may not characterise the difference. No arrows, no percentages, no
 * green. Two weeks into a shadow pilot the difference between those columns is
 * mostly who was on leave, and a product that calls that an improvement teaches
 * its customer to stop believing every other number it prints.
 *
 * Where there is not enough history to state a figure truthfully, the server says
 * so in words and this renders those words rather than a zero.
 *
 * It sits at the foot of Today rather than in the middle of it. Nobody acts on
 * this at 9:40am; it is a record, and putting a record above the day's work was
 * a large part of why Today read as a report.
 */

export interface BaselineMetrics {
  readonly open_total: number | null;
  readonly awaiting_first_response: number | null;
  readonly unassigned: number | null;
  readonly no_next_action: number | null;
  readonly overdue_follow_ups: number | null;
  readonly answered_total: number | null;
  readonly median_first_response_minutes: number | null;
  readonly longest_wait_minutes: number | null;
}

export interface BaselinePayload {
  readonly has_baseline: boolean;
  readonly captured_at?: string;
  readonly definition_version?: string;
  readonly definitions_current?: boolean;
  readonly baseline?: BaselineMetrics;
  readonly current?: BaselineMetrics;
  readonly preview?: {
    readonly metrics: BaselineMetrics;
    readonly insufficient_data: string[];
    readonly definitions: Record<string, string>;
  };
}

const ROWS: ReadonlyArray<{ key: keyof BaselineMetrics; label: string; duration?: boolean }> = [
  { key: 'open_total', label: 'Prospects being worked' },
  { key: 'awaiting_first_response', label: 'Waiting for a first reply' },
  { key: 'unassigned', label: 'With no owner' },
  { key: 'no_next_action', label: 'With nothing scheduled next' },
  { key: 'overdue_follow_ups', label: 'Follow-ups already overdue' },
  { key: 'answered_total', label: 'Replied to at least once' },
  { key: 'median_first_response_minutes', label: 'Typical time to first reply', duration: true },
  { key: 'longest_wait_minutes', label: 'Longest anyone is waiting', duration: true },
];

function duration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return 'not enough history';
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 60 * 48) return `${Math.round(minutes / 60)} hrs`;
  return `${Math.round(minutes / (60 * 24))} days`;
}

function show(value: number | null | undefined, isDuration: boolean | undefined): string {
  if (isDuration) return duration(value);
  return value === null || value === undefined ? '—' : String(value);
}

export function StartingBaseline({ payload }: { payload: BaselinePayload | null }): JSX.Element {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function capture(): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate('/api/leads/starting-baseline', {
      method: 'POST',
      body: { replace: false },
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(body.error?.message ?? 'Could not capture the starting baseline.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  if (!payload) return <></>;

  if (!payload.has_baseline) {
    const preview = payload.preview;
    return (
      <section aria-labelledby="baseline-heading" className="space-y-3" data-testid="baseline-absent">
        <SectionHeader
          id="baseline-heading"
          title="Starting baseline"
          description="No baseline has been captured for this workspace yet. Capturing one records today’s figures, so there is an honest picture of where things stood before anything changed."
        />

        {preview ? (
          <dl className="grid max-w-3xl gap-x-8 gap-y-1.5 text-[13px] sm:grid-cols-2" data-testid="baseline-preview">
            {ROWS.map((row) => (
              <div
                key={row.key}
                className="flex items-baseline justify-between gap-4 border-b border-border py-1.5"
              >
                <dt className="text-muted-foreground">{row.label}</dt>
                <dd className="tabular font-medium text-foreground">
                  {show(preview.metrics[row.key], row.duration)}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}

        {preview && preview.insufficient_data.length > 0 ? (
          <ul className="space-y-1 text-[13px] text-muted-foreground" data-testid="baseline-gaps">
            {preview.insufficient_data.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        ) : null}

        {error ? (
          <p role="alert" className="text-[13px] text-critical" data-testid="baseline-error">
            {error}
          </p>
        ) : null}

        <Button
          variant="primary"
          disabled={busy}
          onClick={() => void capture()}
          data-testid="capture-baseline"
        >
          {busy ? 'Capturing…' : 'Capture the starting baseline'}
        </Button>
      </section>
    );
  }

  const baseline = payload.baseline ?? ({} as BaselineMetrics);
  const current = payload.current ?? ({} as BaselineMetrics);

  return (
    <section aria-labelledby="baseline-heading" className="space-y-3" data-testid="baseline-present">
      <SectionHeader
        id="baseline-heading"
        title="Starting baseline"
        description={`Recorded ${formatDateTime(payload.captured_at ?? null)}. These are the figures this workspace started from — not a result, and not a comparison.`}
      />

      <div className="max-w-3xl overflow-x-auto rounded-lg border border-border bg-surface">
        <table className="w-full border-collapse text-left">
          <caption className="sr-only">
            The figures recorded when this workspace started, beside the same figures now
          </caption>
          <thead className="bg-surface-sunken">
            <tr className="border-b border-border-strong">
              <th
                scope="col"
                className="px-4 py-2 text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground"
              >
                Measure
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-right text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground"
              >
                At the start
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-right text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground"
              >
                Now
              </th>
            </tr>
          </thead>
          <tbody data-testid="baseline-rows">
            {ROWS.map((row) => (
              <tr key={row.key} className="border-b border-border last:border-b-0">
                <th scope="row" className="px-4 py-2 text-left text-sm font-normal text-secondary-foreground">
                  {row.label}
                </th>
                <td
                  className="tabular px-4 py-2 text-right text-sm text-foreground"
                  data-testid={`baseline-${row.key}`}
                >
                  {show(baseline[row.key], row.duration)}
                </td>
                <td
                  className="tabular px-4 py-2 text-right text-sm text-foreground"
                  data-testid={`current-${row.key}`}
                >
                  {show(current[row.key], row.duration)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="max-w-reading text-[13px] text-muted-foreground">
        Both columns are counts of records you can open. Nothing here says whether the change is
        good: too little time has passed for that to mean anything, and a pilot is for finding out,
        not for proving a point.
        {payload.definitions_current === false
          ? ' These figures were recorded under an older definition, so treat the two columns as measuring slightly different things.'
          : ''}
      </p>
    </section>
  );
}
