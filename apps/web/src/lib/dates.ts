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
