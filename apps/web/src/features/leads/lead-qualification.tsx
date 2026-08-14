'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';
import { StatusText, type Severity } from '@/features/ui/status';

interface QualificationResponse {
  readonly data?: {
    readonly qualification?: {
      readonly score: number;
      readonly category: string;
      readonly reasons?: readonly string[];
      readonly missing_fields?: readonly string[];
      readonly qualified_by?: string;
      readonly degraded?: boolean;
    };
  };
  readonly error?: { readonly message?: string };
}

/** Hot/warm/cold is a temperature, not an alarm. Only "hot" earns any colour. */
function tone(category: string | null): Severity {
  if (category === 'hot') return 'positive';
  return 'neutral';
}

/**
 * Qualification, scored by the rules rather than by a model.
 *
 * The rubric runs entirely server-side against the fields captured with the
 * enquiry, so this works with no AI provider configured - which is the state the
 * product is in today and, more importantly, the state a customer's office is in
 * when their internet drops. "Score with rules" is therefore the default and the
 * primary button; a manual override exists because a salesperson who has spoken
 * to the person knows things the form never captured.
 */
export function LeadQualification({
  leadId,
  score,
  category,
}: {
  leadId: string;
  score: number | null;
  category: string | null;
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reasons, setReasons] = useState<readonly string[]>([]);
  const [missing, setMissing] = useState<readonly string[]>([]);

  async function run(body: Record<string, unknown>): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/leads/${leadId}/qualify`, { method: 'POST', body });
    const payload = (await response.json().catch(() => ({}))) as QualificationResponse;
    if (!response.ok) {
      setError(payload.error?.message ?? 'Could not score this prospect.');
      setBusy(false);
      return;
    }
    setReasons(payload.data?.qualification?.reasons ?? []);
    setMissing(payload.data?.qualification?.missing_fields ?? []);
    setBusy(false);
    router.refresh();
  }

  async function onManual(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const raw = String(new FormData(event.currentTarget).get('manual_score') ?? '');
    if (raw === '') return;
    await run({ mode: 'manual', manual_score: Number(raw) });
  }

  return (
    <section aria-labelledby="qualification-heading" className="space-y-3">
      <SectionHeader
        id="qualification-heading"
        title="Qualification"
        actions={
          <p data-testid="lead-score">
            {score === null ? (
              <span className="text-[13px] text-muted-foreground">Not scored yet</span>
            ) : (
              <>
                <span className="text-xl font-semibold tabular text-foreground">{score}</span>
                <span className="sr-only"> out of 100. </span>
                <StatusText tone={tone(category)} className="ml-2 text-[13px]">
                  {category ?? 'unrated'}
                </StatusText>
              </>
            )}
          </p>
        }
      />

      <p className="text-[13px] text-muted-foreground">
        No AI provider is connected, so rules score this from the enquiry &mdash; the same result
        every time, and you can see why.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <Button
          variant="secondary"
          disabled={busy}
          data-testid="qualify-rules"
          onClick={() => void run({ mode: 'rule' })}
        >
          Score with rules
        </Button>

        <form onSubmit={onManual} className="flex items-end gap-2" noValidate>
          <div>
            <label htmlFor="manual_score" className="block text-[13px] text-muted-foreground">
              Or set it yourself
            </label>
            <input
              id="manual_score"
              name="manual_score"
              type="number"
              min={0}
              max={100}
              data-testid="manual-score"
              className={`${controlClass(false)} mt-1 w-20`}
            />
          </div>
          <Button variant="ghost" type="submit" disabled={busy} data-testid="qualify-manual">
            Save
          </Button>
        </form>
      </div>

      {error ? (
        <p role="alert" data-testid="qualify-error" className="text-[13px] text-critical">
          {error}
        </p>
      ) : null}

      {reasons.length > 0 ? (
        <div data-testid="qualify-reasons">
          <h3 className="text-[13px] font-semibold text-foreground">Why</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {missing.length > 0 ? (
        <p className="text-[13px] text-muted-foreground">
          Still missing: {missing.join(', ')}. Fill these in and score again for a firmer answer.
        </p>
      ) : null}
    </section>
  );
}
