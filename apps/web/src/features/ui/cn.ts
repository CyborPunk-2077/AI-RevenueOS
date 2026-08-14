/**
 * Join class names, dropping anything falsy.
 *
 * Deliberately ten lines rather than a dependency. It does not de-duplicate
 * conflicting Tailwind utilities, and it does not need to: components in this
 * codebase compose classes rather than override them, and a caller that has to
 * fight a primitive's own styling is a signal the primitive needs a variant.
 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
