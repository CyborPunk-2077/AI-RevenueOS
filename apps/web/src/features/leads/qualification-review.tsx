/**
 * AI qualification review. Score, evidence, reasons, missing fields and provenance
 * are always shown, and the reviewer can accept, edit, reject or defer.
 */
export interface Evidence {
  readonly criterion: string;
  readonly value: unknown;
  readonly source: string;
  readonly excerpt?: string | null;
  readonly confidence: number;
}

export interface Qualification {
  readonly score: number;
  readonly category: 'hot' | 'warm' | 'cold';
  readonly evidence: readonly Evidence[];
  readonly reasons: readonly string[];
  readonly missing_fields: readonly string[];
  readonly qualified_by: 'ai' | 'rule' | 'manual';
  readonly degraded: boolean;
  readonly review_state: 'pending' | 'accepted' | 'edited' | 'rejected' | 'deferred';
  readonly provenance: Record<string, unknown>;
}

export type ReviewDecision = 'accepted' | 'edited' | 'rejected' | 'deferred';

export interface QualificationReviewProps {
  readonly qualification: Qualification;
  readonly onDecision: (decision: ReviewDecision, editedScore?: number) => void;
  readonly disabled?: boolean;
}

const CATEGORY_LABEL: Record<Qualification['category'], string> = {
  hot: 'Hot (80 and above)',
  warm: 'Warm (40 to 79)',
  cold: 'Cold (below 40)',
};

export function QualificationReview({
  qualification,
  onDecision,
  disabled = false,
}: QualificationReviewProps): JSX.Element {
  const { score, category, evidence, reasons, missing_fields, qualified_by, degraded } = qualification;

  return (
    <section aria-labelledby="qualification-heading" className="space-y-4">
      <header className="flex items-baseline justify-between">
        <h2 id="qualification-heading" className="text-lg font-semibold">
          Qualification
        </h2>
        <p>
          <span className="text-2xl font-bold">{score}</span>
          <span className="sr-only"> out of 100. </span>
          <span className="ml-2 text-sm text-muted-foreground">{CATEGORY_LABEL[category]}</span>
        </p>
      </header>

      {/* Provenance is never hidden: the reviewer must know what produced the score. */}
      <p className="text-sm text-muted-foreground">
        Scored by {qualified_by === 'ai' ? 'the assistant' : qualified_by === 'manual' ? 'a colleague' : 'the qualification rules'}
        {degraded ? ' (assistant unavailable; rules were used instead)' : ''}.
      </p>

      {evidence.length > 0 ? (
        <div>
          <h3 className="text-sm font-medium">Evidence</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {evidence.map((item) => (
              <li key={item.criterion}>
                <span className="font-medium">{item.criterion}</span>: {String(item.value)}{' '}
                <span className="text-muted-foreground">({item.source})</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {reasons.length > 0 ? (
        <div>
          <h3 className="text-sm font-medium">Reasons</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {missing_fields.length > 0 ? (
        <div>
          <h3 className="text-sm font-medium">Missing information</h3>
          <p className="mt-1 text-sm text-muted-foreground">{missing_fields.join(', ')}</p>
        </div>
      ) : null}

      <div role="group" aria-label="Qualification decision" className="flex flex-wrap gap-2">
        {(['accepted', 'edited', 'rejected', 'deferred'] as const).map((decision) => (
          <button
            key={decision}
            type="button"
            disabled={disabled}
            onClick={() => onDecision(decision)}
            className="min-h-[44px] min-w-[44px] rounded-md border px-4 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
          >
            {decision === 'accepted'
              ? 'Accept'
              : decision === 'edited'
                ? 'Edit score'
                : decision === 'rejected'
                  ? 'Reject'
                  : 'Decide later'}
          </button>
        ))}
      </div>
    </section>
  );
}
