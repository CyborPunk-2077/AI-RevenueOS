import type { ReactNode } from 'react';
import { cn } from './cn';

/**
 * The shared visual vocabulary. Everything else composes these, so a change to
 * density or hierarchy happens in one file rather than forty.
 *
 * Two rules run through all of it:
 *
 * - **Containment is earned.** A panel appears only where what is inside it
 *   genuinely needs separating from what surrounds it. A page is a titled
 *   document with sections divided by rules and space, not a tray of floating
 *   rounded boxes.
 * - **State is never colour alone.** The grayscale test is the same requirement
 *   the accessibility gate states as contrast: remove the hue and every state -
 *   overdue, waiting, unassigned, failed - must still be identifiable.
 */

/**
 * @deprecated Use `StatusText`, `SeverityMark` or `LabelChip` from `./status`.
 *
 * A compatibility shim while the last callers migrate. The filled rounded pill
 * it used to render is the pattern section 9 of the UI/UX system bans outright;
 * what it renders now is already the endpoint - rectangular, bordered, unfilled -
 * so a screen that has not been rebuilt yet does not look like a different
 * product. Delete it once nothing imports it.
 */
export function StatusPill({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'success' | 'warning' | 'danger';
  children: ReactNode;
}): JSX.Element {
  const toneClass = {
    neutral: 'pill-neutral',
    success: 'pill-success',
    warning: 'pill-warning',
    danger: 'pill-danger',
  }[tone];
  return <span className={`pill ${toneClass}`}>{children}</span>;
}

/**
 * A genuine panel: 1px border, small radius, no shadow, no hover lift.
 *
 * `data-testid` is forwarded explicitly. JSX does not type-check hyphenated
 * attributes on a component, so one passed here used to be silently dropped -
 * the element rendered, the marker vanished, and nothing anywhere said why. That
 * cost a session once.
 */
export function Card({
  as: Tag = 'div',
  padded = true,
  className = '',
  children,
  'data-testid': testId,
}: {
  as?: 'div' | 'article' | 'section' | 'li';
  padded?: boolean;
  className?: string;
  children: ReactNode;
  'data-testid'?: string;
}): JSX.Element {
  return (
    <Tag
      className={cn('rounded-lg border border-border bg-surface', padded && 'p-5', className)}
      data-testid={testId}
    >
      {children}
    </Tag>
  );
}

/**
 * The page header: one `h1`, an optional line of context, the primary action on
 * the same baseline, and a rule that closes it off from the content.
 */
export function PageHeader({
  title,
  description,
  actions,
  className = '',
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <header className={cn('border-b border-border pb-4', className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold leading-[30px] tracking-[-0.01em] text-foreground">
            {title}
          </h1>
          {description ? (
            <p className="mt-1 max-w-reading text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}

/**
 * A section inside a page. A heading and a hairline, not another rounded box:
 * this is what makes a page read as one document rather than as a tray.
 */
export function SectionHeader({
  title,
  description,
  actions,
  id,
  className = '',
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  id?: string;
  className?: string;
}): JSX.Element {
  return (
    <div className={cn('flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1', className)}>
      <div className="min-w-0">
        <h2 id={id} className="text-[15px] font-semibold leading-5 text-foreground">
          {title}
        </h2>
        {description ? (
          <p className="mt-0.5 max-w-reading text-[13px] text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-3">{actions}</div> : null}
    </div>
  );
}

/**
 * A single quiet figure.
 *
 * This used to be an interactive card with a `text-3xl` number and a coloured
 * delta pill, and the delta was the problem: it implied a comparison the product
 * does not make. Nothing here measures a previous period, so nothing here may
 * draw an arrow. Where several figures belong together, use `MetricStrip`
 * instead - a row of these in a grid is the card tray again.
 */
export function Stat({
  label,
  value,
  hint,
  className = '',
}: {
  label: string;
  value: string;
  hint?: string;
  className?: string;
}): JSX.Element {
  return (
    <div className={cn('min-w-0', className)}>
      <p className="text-[13px] font-medium leading-[18px] text-muted-foreground">{label}</p>
      <p className="mt-1 text-[26px] font-semibold leading-[30px] tabular text-foreground">
        {value}
      </p>
      {hint ? (
        <p className="mt-1 text-[13px] leading-[18px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export function Skeleton({ className = '' }: { className?: string }): JSX.Element {
  return <div className={cn('skeleton', className)} aria-hidden="true" />;
}

/**
 * Loading state for a list, in the shape of the table it becomes. `aria-busy`
 * plus a single polite message beats announcing eight skeleton rows one by one.
 */
export function ListSkeleton({ rows = 5 }: { rows?: number }): JSX.Element {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className="overflow-hidden rounded-lg border border-border bg-surface"
    >
      <span className="sr-only">Loading…</span>
      <div className="h-9 border-b border-border-strong bg-surface-sunken" />
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-4 border-b border-border px-4 py-3 last:border-b-0">
          <Skeleton className="h-6 w-6 rounded-full" />
          <Skeleton className="h-3.5 w-1/4" />
          <Skeleton className="h-3.5 w-1/6" />
          <Skeleton className="ml-auto h-3.5 w-16" />
        </div>
      ))}
    </div>
  );
}

/**
 * An empty state that says what to do next. "No results" alone leaves somebody
 * guessing whether the product is broken or they simply have no data. No dashed
 * border and no illustration: a sentence and a button.
 */
export function EmptyState({
  title,
  description,
  action,
  className = '',
}: {
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-surface px-6 py-12 text-center',
        className,
      )}
    >
      <p className="text-[15px] font-semibold text-foreground">{title}</p>
      <p className="mx-auto mt-1.5 max-w-reading text-sm text-muted-foreground">{description}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}
