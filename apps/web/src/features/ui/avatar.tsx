import { cn } from './cn';

/**
 * A person or a business, shown as initials.
 *
 * **No photograph is ever fetched, generated or guessed.** No gravatar, no
 * avatar service, no stock faces, no AI portraits. The resolution order is: an
 * image the Sangam user uploaded, then an image the business explicitly
 * supplied, then these initials. Sangam holds no uploaded images today - object
 * storage is provider-gated - so initials are not the fallback, they are the
 * normal state, and the interface has to look finished with nothing else.
 *
 * The tint is deterministic across four muted hues so a name keeps the same
 * colour everywhere and a dense list can be scanned by shape. Four, and muted,
 * because a saturated eight-colour set turns a prospect list into a chart. The
 * avatar never carries status: an overdue prospect is not a red circle.
 */

const TINTS = [
  // Each pairs a low-chroma background with a foreground measured against it in
  // both themes. Adding a fifth means measuring a fifth.
  'bg-[hsl(216_28%_92%)] text-[hsl(216_45%_28%)] dark:bg-[hsl(216_22%_22%)] dark:text-[hsl(216_45%_82%)]',
  'bg-[hsl(152_20%_91%)] text-[hsl(152_40%_24%)] dark:bg-[hsl(152_16%_21%)] dark:text-[hsl(152_35%_80%)]',
  'bg-[hsl(32_28%_92%)] text-[hsl(32_50%_26%)] dark:bg-[hsl(32_20%_22%)] dark:text-[hsl(32_45%_80%)]',
  'bg-[hsl(280_16%_92%)] text-[hsl(280_30%_30%)] dark:bg-[hsl(280_14%_23%)] dark:text-[hsl(280_28%_83%)]',
];

const NEUTRAL = 'bg-surface-sunken text-secondary-foreground';

/** Up to two characters, from the first and last word of the stored name. */
export function initialsOf(name: string): string {
  const words = name
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return '—';
  if (words.length === 1) return words[0]!.slice(0, 2).toUpperCase();
  return `${words[0]![0]!}${words[words.length - 1]![0]!}`.toUpperCase();
}

/** Same name, same tint, on every screen and every render. */
function tintFor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % 997;
  return TINTS[hash % TINTS.length]!;
}

const SIZES = {
  sm: 'h-6 w-6 text-[11px]',
  md: 'h-7 w-7 text-xs',
  lg: 'h-9 w-9 text-sm',
} as const;

export function Avatar({
  name,
  size = 'sm',
  tinted = true,
  className = '',
}: {
  name: string;
  size?: keyof typeof SIZES;
  /** Neutral by default in headers; tinted where a dense list is scanned. */
  tinted?: boolean;
  className?: string;
}): JSX.Element {
  const label = name.trim() || 'Unknown';
  return (
    <span
      aria-hidden="true"
      title={label}
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center rounded-full border border-border font-medium leading-none',
        SIZES[size],
        tinted ? tintFor(label) : NEUTRAL,
        className,
      )}
    >
      {initialsOf(label)}
    </span>
  );
}
