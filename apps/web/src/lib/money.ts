/**
 * Money formatting, in a plain module on purpose.
 *
 * It used to be exported from `deal-board.tsx`, which carries 'use client'.
 * Next marks every export of a client module as a client reference, so a server
 * component calling it threw at render time and the page 500'd. Anything both
 * sides need has to live outside the client boundary.
 */
export function money(minor: number, currency = 'INR'): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(minor / 100);
}
