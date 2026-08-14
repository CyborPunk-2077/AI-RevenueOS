import { formatDate, formatDateTime } from '@/lib/dates';
import { money } from '@/lib/money';
import { cn } from './cn';

/**
 * Numbers, durations and times, formatted once.
 *
 * These existed as four separate copies of `duration()` across Today, Prospects,
 * prospect detail and the metrics panel. Four copies is how "2 hrs" on one screen
 * becomes "1h 47m" on another, and an owner who sees two answers to the same
 * question stops believing either.
 */

/**
 * Whole units. "1h 47m" invites a precision nobody acts on: at 47 minutes past
 * the hour, no decision changes.
 */
export function duration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '—';
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 60 * 48) return `${Math.round(minutes / 60)} hrs`;
  return `${Math.round(minutes / (60 * 24))} days`;
}

/** How long something has been waiting, from when it arrived. */
export function elapsedSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
}

export function minutesBetween(
  from: string | null | undefined,
  to: string | null | undefined,
): number | null {
  if (!from || !to) return null;
  return Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 60_000));
}

/**
 * How long ago, with the exact timestamp on hover and for a screen reader.
 *
 * `<time>` rather than a span, because "3 days" is only useful next to the fact
 * that it means Tuesday the 11th to somebody checking a promise.
 */
export function RelativeTime({
  iso,
  className = '',
  /** Some columns want the date itself; waiting columns want the elapsed time. */
  mode = 'elapsed',
}: {
  iso: string | null | undefined;
  className?: string;
  mode?: 'elapsed' | 'date' | 'datetime';
}): JSX.Element {
  if (!iso) return <span className={cn('text-muted-foreground', className)}>—</span>;

  const exact = formatDateTime(iso);
  const text =
    mode === 'date' ? formatDate(iso) : mode === 'datetime' ? exact : duration(elapsedSince(iso));

  return (
    <time dateTime={iso} title={exact} className={cn('tabular', className)}>
      {text}
    </time>
  );
}

/** Rupees, `en-IN` grouped, never with paise nobody quoted. */
export function Money({
  minor,
  className = '',
}: {
  minor: number | null | undefined;
  className?: string;
}): JSX.Element {
  if (minor === null || minor === undefined) {
    return <span className={cn('text-muted-foreground', className)}>—</span>;
  }
  return <span className={cn('tabular', className)}>{money(minor)}</span>;
}
