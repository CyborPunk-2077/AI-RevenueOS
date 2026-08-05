import { apiFetch } from '@/lib/session';
import { AppointmentPanel, type AppointmentEntry } from '@/features/crm/appointment-panel';
import { PageHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

interface CalendarSync { readonly enabled: boolean; readonly blocker: string | null }

export default async function AppointmentsPage(): Promise<JSX.Element> {
  const [listResult, syncResult] = await Promise.all([
    apiFetch<{ appointments: AppointmentEntry[] }>('/appointments?page_size=100'),
    apiFetch<CalendarSync>('/appointments/calendar-sync'),
  ]);
  const appointments = listResult.data?.appointments ?? [];
  const sync = syncResult.data;

  return (
    <div className="space-y-8">
      <PageHeader title="Appointments" description="Double booking is prevented by the database, not by a check &mdash; two requests for the same slot cannot both succeed." />

      {sync && !sync.enabled ? (
        <p data-testid="calendar-gated" className="rounded border border-dashed p-3 text-sm text-muted-foreground">
          {sync.blocker}
        </p>
      ) : null}

      <AppointmentPanel appointments={appointments} />
    </div>
  );
}
