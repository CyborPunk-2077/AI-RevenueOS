import type { ReactNode } from 'react';
import { cn } from './cn';

/**
 * How Sangam shows state.
 *
 * Section 9 of the UI/UX system bans rows of `[ HIGH ] [ MEDIUM ] [ LOW ]` and
 * `[ WAITING ] [ CONTACTED ]` in filled rounded pills. That pattern is the
 * clearest tell of a generated interface and, worse, it makes every row shout
 * equally - which means none of them shouts.
 *
 * Always take the highest of these that works:
 *
 *   1. **Ordering.** The oldest wait goes first. Nothing needs to be red for
 *      that to be understood, and no component is required.
 *   2. **Plain text.** `Unassigned`, `Not yet`, `None set`. The words carry it.
 *   3. **`StatusText`.** Weight and colour on the words themselves.
 *   4. **`SeverityMark`.** A 2px rule on a row that must be findable while
 *      scanning a long table.
 *   5. **`LabelChip`.** Last resort, where the word alone is genuinely
 *      ambiguous - the `sample` marker, a workspace kind, a `failed` delivery.
 *
 * Every one of them survives grayscale, because a rule is a shape and a word is
 * a word.
 */

export type Severity = 'neutral' | 'critical' | 'warning' | 'positive' | 'accent';

const TEXT_TONE: Record<Severity, string> = {
  neutral: 'text-muted-foreground',
  critical: 'font-medium text-critical',
  warning: 'font-medium text-warning',
  positive: 'text-positive',
  accent: 'text-accent',
};

/**
 * State as words. `emphasis` exists because "Overdue" and "3 days" are the same
 * grammatical thing and only one of them is a problem.
 */
export function StatusText({
  tone = 'neutral',
  children,
  className = '',
  ...rest
}: {
  tone?: Severity;
  children: ReactNode;
  className?: string;
} & { 'data-testid'?: string; title?: string }): JSX.Element {
  return (
    <span className={cn(TEXT_TONE[tone], className)} {...rest}>
      {children}
    </span>
  );
}

const MARK_TONE: Record<Severity, string> = {
  neutral: 'bg-transparent',
  critical: 'bg-critical',
  warning: 'bg-warning',
  positive: 'bg-positive',
  accent: 'bg-accent',
};

/**
 * The 2px rule down the left of a row that needs finding at a glance.
 *
 * Rendered as an absolutely-positioned span inside a `relative` cell rather than
 * as a border, so it does not shift the first column's text by two pixels and
 * break the alignment of every row that is not marked.
 */
export function SeverityMark({
  tone,
  label,
}: {
  tone: Exclude<Severity, 'neutral'>;
  /** Said out loud for anyone who cannot see the rule. Never colour alone. */
  label: string;
}): JSX.Element {
  return (
    <>
      <span
        aria-hidden="true"
        className={cn('absolute inset-y-0 left-0 w-0.5', MARK_TONE[tone])}
      />
      <span className="sr-only">{label}</span>
    </>
  );
}

const CHIP_TONE: Record<Severity, string> = {
  neutral: 'border-border-strong text-secondary-foreground',
  critical: 'border-critical/50 text-critical',
  warning: 'border-warning/50 text-warning',
  positive: 'border-positive/50 text-positive',
  accent: 'border-accent/40 text-accent',
};

/**
 * A bordered, unfilled rectangle. Not a pill: nothing in this product is a pill
 * except an avatar.
 */
export function LabelChip({
  tone = 'neutral',
  children,
  className = '',
  ...rest
}: {
  tone?: Severity;
  children: ReactNode;
  className?: string;
} & { 'data-testid'?: string; title?: string }): JSX.Element {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-px text-xs font-medium leading-5',
        CHIP_TONE[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
