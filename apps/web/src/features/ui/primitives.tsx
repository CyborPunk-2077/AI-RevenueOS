import type { ReactNode } from 'react';

/**
 * The shared visual vocabulary. Everything else composes these, so a change to
 * elevation or density happens in one file rather than forty.
 *
 * Two rules run through all of it:
 *
 * - **Status is never colour alone.** Every `StatusPill` renders a text label;
 *   the tint is redundant reinforcement. The accessibility gate fails a story
 *   that relies on hue, and more to the point a red badge means nothing to the
 *   8% of men with a colour vision deficiency.
 * - **Skeletons mirror the real layout.** A spinner tells you to wait; a
 *   skeleton in the shape of the content tells you what is coming and stops the
 *   page jumping when it lands.
 */

type Tone = 'neutral' | 'success' | 'warning' | 'danger';

const TONE_CLASS: Record<Tone, string> = {
  neutral: 'pill-neutral',
  success: 'pill-success',
  warning: 'pill-warning',
  danger: 'pill-danger',
};

export function StatusPill({
  tone = 'neutral',
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}): JSX.Element {
  return <span className={`pill ${TONE_CLASS[tone]}`}>{children}</span>;
}

export function Card({
  as: Tag = 'div',
  interactive = false,
  className = '',
  children,
}: {
  as?: 'div' | 'article' | 'section' | 'li';
  interactive?: boolean;
  className?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <Tag className={`surface p-5 ${interactive ? 'interactive' : ''} ${className}`}>{children}</Tag>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}): JSX.Element {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="heading text-2xl">{title}</h1>
        {description ? (
          <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/**
 * A metric. `delta` is described in words as well as signed, because an arrow
 * and a colour do not survive a screen reader.
 */
export function Stat({
  label,
  value,
  delta,
  hint,
}: {
  label: string;
  value: string;
  delta?: { value: string; direction: 'up' | 'down' | 'flat' };
  hint?: string;
}): JSX.Element {
  const tone: Tone =
    delta?.direction === 'up' ? 'success' : delta?.direction === 'down' ? 'danger' : 'neutral';

  return (
    <Card interactive className="animate-fade-up">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="heading mt-2 text-3xl tabular">{value}</p>
      {delta ? (
        <p className="mt-2">
          <StatusPill tone={tone}>
            {delta.value}
            <span className="sr-only">
              {delta.direction === 'up'
                ? ' increase'
                : delta.direction === 'down'
                  ? ' decrease'
                  : ' no change'}
            </span>
          </StatusPill>
        </p>
      ) : null}
      {hint ? <p className="mt-2 text-xs text-muted-foreground">{hint}</p> : null}
    </Card>
  );
}

export function Skeleton({ className = '' }: { className?: string }): JSX.Element {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

/**
 * Loading state for a list. `aria-busy` plus a single polite message beats
 * announcing eight skeleton rows one at a time.
 */
export function ListSkeleton({ rows = 5 }: { rows?: number }): JSX.Element {
  return (
    <div aria-busy="true" aria-live="polite" className="space-y-3">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="surface flex items-center gap-4 p-4">
          <Skeleton className="h-10 w-10 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="h-6 w-16 rounded-full" />
        </div>
      ))}
    </div>
  );
}

/**
 * An empty state that says what to do next. "No results" alone leaves the
 * person guessing whether the product is broken or they simply have no data.
 */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="surface flex flex-col items-center gap-3 border-dashed px-6 py-12 text-center">
      <p className="heading text-base">{title}</p>
      <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
      {action}
    </div>
  );
}
