/**
 * Every AI surface must present a manual path when the model is unavailable.
 * An AI failure never blocks core CRM operation.
 */
export interface DegradedStateProps {
  readonly reason: string | null;
  readonly manualPath: string | null;
  readonly onManualAction?: () => void;
  readonly manualActionLabel?: string;
}

export function DegradedState({
  reason,
  manualPath,
  onManualAction,
  manualActionLabel = 'Continue manually',
}: DegradedStateProps): JSX.Element | null {
  if (!reason) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
    >
      <p className="font-medium">Assistance is temporarily unavailable</p>
      {manualPath ? <p className="mt-1">{manualPath}</p> : null}
      {onManualAction ? (
        <button
          type="button"
          onClick={onManualAction}
          className="mt-3 min-h-[44px] rounded-md bg-amber-900 px-4 py-2 text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {manualActionLabel}
        </button>
      ) : null}
    </div>
  );
}
