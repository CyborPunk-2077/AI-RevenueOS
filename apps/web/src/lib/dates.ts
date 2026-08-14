/**
 * Dates, always in Indian Standard Time.
 *
 * Without an explicit zone these formatters follow whichever clock the code
 * happens to run on. The server container runs in UTC and the browser runs in
 * whatever the laptop is set to, so the *same* follow-up rendered on a server
 * component and on a client component showed two different dates - and React
 * hydration silently replaced one with the other. An SME in Bengaluru has one
 * working day, so both sides are pinned to it.
 *
 * `en-IN` gives day/month/year, which is what the reader expects. When per-tenant
 * timezones become configurable this is the one place that has to change.
 */

const ZONE = 'Asia/Kolkata';

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', {
    timeZone: ZONE,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    timeZone: ZONE,
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Clock time alone, for a message that already sits under a date separator. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('en-IN', {
    timeZone: ZONE,
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * The working day an instant falls on, in IST, as `YYYY-MM-DD`.
 *
 * Used to decide where a transcript's date separators go. Comparing the ISO
 * strings directly would group by UTC day, which splits a Bengaluru evening in
 * half: 6pm IST onwards is already tomorrow in UTC, so a conversation held after
 * dinner would be dated across two headings.
 */
export function dayKey(iso: string | null | undefined): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-CA', { timeZone: ZONE });
}

/**
 * A date separator's label: Today, Yesterday, or the date itself.
 *
 * Relative to the reader's own working day, also in IST, so "Today" means what
 * somebody sitting in the office would mean by it.
 */
export function formatDayHeading(iso: string | null | undefined): string {
  if (!iso) return '';
  const key = dayKey(iso);
  const now = new Date();
  if (key === dayKey(now.toISOString())) return 'Today';
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (key === dayKey(yesterday.toISOString())) return 'Yesterday';
  return formatDate(iso);
}
