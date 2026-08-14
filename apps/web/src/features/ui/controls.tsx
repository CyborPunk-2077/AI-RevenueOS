import type { ReactNode } from 'react';
import { cn } from './cn';

/**
 * Buttons, fields and the row that wires a field to its message.
 *
 * The validation contract encoded in `FieldRow` was hard-won in session 4 and is
 * pinned by browser tests, so it is a component rather than a convention:
 * `aria-invalid` plus `aria-describedby` on the control, the message directly
 * beneath it as a sentence, and a 2px critical rule on the field. Never a toast,
 * never only a summary at the top, and never framework wording - a founder must
 * not read "The request payload failed validation".
 */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'md' | 'sm';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-accent-foreground hover:bg-accent-hover',
  secondary: 'border border-border-strong text-foreground hover:bg-surface-hover',
  ghost: 'text-secondary-foreground hover:bg-surface-hover hover:text-foreground',
  // Destructive actions are never adjacent to the primary one, which is a
  // layout rule this component cannot enforce - but it can at least not look
  // like the primary.
  danger: 'border border-critical/50 text-critical hover:bg-critical-soft',
};

const SIZE: Record<ButtonSize, string> = {
  md: 'px-3 text-sm',
  sm: 'px-2.5 text-[13px]',
};

export function Button({
  variant = 'secondary',
  size = 'md',
  type = 'button',
  className = '',
  children,
  ...rest
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>): JSX.Element {
  return (
    <button
      // eslint-disable-next-line react/button-has-type -- narrowed by the default
      type={type}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55',
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

const CONTROL =
  'w-full rounded border bg-surface px-3 text-sm text-foreground transition-colors placeholder:text-disabled-foreground focus:outline-none focus:ring-[3px] focus:ring-ring/25 disabled:opacity-55';

/** Shared by input, select and textarea so the three cannot drift apart. */
export function controlClass(invalid: boolean, extra = ''): string {
  return cn(
    CONTROL,
    'min-h-[var(--control-height)] py-1.5',
    invalid ? 'border-l-2 border-critical' : 'border-border-strong focus:border-ring',
    extra,
  );
}

/**
 * A labelled control with its own message.
 *
 * The label is always above and always visible - a placeholder is not a label,
 * and the moment somebody types, a placeholder-labelled form is a row of boxes
 * nobody can check. `width` exists because a full-width input for a ten-digit
 * phone number looks unconsidered.
 */
export function FieldRow({
  id,
  label,
  hint,
  error,
  errorTestId,
  width,
  children,
  className = '',
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  errorTestId?: string;
  width?: 'sm' | 'md' | 'lg' | 'full';
  /** Receives the wiring it needs: id, aria-invalid, aria-describedby. */
  children: (props: {
    id: string;
    'aria-invalid'?: true;
    'aria-describedby'?: string;
    className: string;
  }) => ReactNode;
  className?: string;
}): JSX.Element {
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const widthClass =
    width === 'sm'
      ? 'max-w-[11rem]'
      : width === 'md'
        ? 'max-w-[18rem]'
        : width === 'lg'
          ? 'max-w-[28rem]'
          : '';

  return (
    <div className={cn(widthClass, className)}>
      <label htmlFor={id} className="block text-[13px] font-medium text-foreground">
        {label}
      </label>
      <div className="mt-1">
        {children({
          id,
          ...(error ? { 'aria-invalid': true as const } : {}),
          ...(describedBy ? { 'aria-describedby': describedBy } : {}),
          className: controlClass(Boolean(error)),
        })}
      </div>
      {error ? (
        <p id={`${id}-error`} data-testid={errorTestId} className="mt-1 text-[13px] text-critical">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-[13px] text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/**
 * A checkbox with its label. The 44px target rule already applies to the input,
 * so the label sits beside it rather than stretching the row.
 */
export function Checkbox({
  id,
  label,
  ...rest
}: { id: string; label: ReactNode } & React.InputHTMLAttributes<HTMLInputElement>): JSX.Element {
  return (
    <label htmlFor={id} className="inline-flex items-center gap-2 text-sm text-foreground">
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 rounded-sm border-border-strong accent-accent"
        {...rest}
      />
      {label}
    </label>
  );
}
