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
    <div className="space-y-5">
      <PageHeader
        title="Appointments"
        description="Meetings booked with a customer, and what came of them."
      />

      {/* The real reason calendar sync is off, stated rather than left to be
          inferred from an absent feature. */}
      {sync && !sync.enabled ? (
        <p data-testid="calendar-gated" className="max-w-reading text-[13px] text-muted-foreground">
          {sync.blocker}
        </p>
      ) : null}

      <AppointmentPanel appointments={appointments} />
    </div>
  );
}
