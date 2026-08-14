import Link from 'next/link';
import { cn } from './cn';

/**
 * The operational figures, as one row separated by rules.
 *
 * **Not five cards.** Five bordered boxes in a grid is the shape that made the
 * old Today read as a dashboard rather than as a page: each box claimed equal
 * importance, and the gaps between them said the figures were unrelated when
 * they describe one workload.
 *
 * Every figure links to the rows behind it. A dashboard whose numbers cannot be
 * clicked through to the records that make them up is decoration, and an SME
 * owner learns not to trust it within a week.
 *
 * No sparklines, no deltas, no arrows, no icons, no invented percentage
 * improvements. Where a figure cannot be computed the value is an em dash and
 * the hint says why, rather than a zero that actually means "we do not know".
 */

export interface Metric {
  key: string;
  label: string;
  value: string;
  hint?: string;
  href?: string;
  testId?: string;
  /**
   * Reserved for a figure that is genuinely a problem. The label already says
   * what it is, so the colour is redundant reinforcement rather than the only
   * thing carrying the meaning - which is what keeps it grayscale-safe.
   */
  emphasis?: 'critical';
}

export function MetricStrip({
  metrics,
  className = '',
  'aria-label': ariaLabel = 'Operational summary',
}: {
  metrics: Metric[];
  className?: string;
  'aria-label'?: string;
}): JSX.Element {
  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        // Vertical rules only where the strip is genuinely one row. Wrapped into
        // two or three columns they would draw a stray line down the left of
        // every row after the first, which is worse than no rule at all.
        'grid grid-cols-2 gap-x-6 gap-y-6 rounded-lg border border-border bg-surface px-5 py-4 sm:grid-cols-3 min-[1100px]:grid-cols-5 min-[1100px]:gap-x-0',
        className,
      )}
    >
      {metrics.map((metric, index) => {
        const body = (
          <>
            <span className="block text-[13px] font-medium leading-[18px] text-muted-foreground">
              {metric.label}
            </span>
            <span
              className={cn(
                'mt-1 block text-[26px] font-semibold leading-[30px] tabular',
                metric.emphasis === 'critical' ? 'text-critical' : 'text-foreground',
              )}
            >
              {metric.value}
            </span>
            {metric.hint ? (
              <span className="mt-1 block text-[13px] leading-[18px] text-muted-foreground">
                {metric.hint}
              </span>
            ) : null}
          </>
        );

        return (
          <div
            key={metric.key}
            data-testid={metric.testId}
            className={cn(
              'min-w-0',
              index > 0 && 'min-[1100px]:border-l min-[1100px]:border-border min-[1100px]:pl-5',
              index < metrics.length - 1 && 'min-[1100px]:pr-5',
            )}
          >
            {metric.href ? (
              <Link
                href={metric.href}
                className="-mx-1 block rounded px-1 py-0.5 transition-colors hover:bg-surface-hover"
              >
                {body}
              </Link>
            ) : (
              body
            )}
          </div>
        );
      })}
    </section>
  );
}
