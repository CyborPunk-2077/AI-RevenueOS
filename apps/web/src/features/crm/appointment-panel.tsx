'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { formatDateTime } from '@/lib/dates';

export interface AppointmentEntry {
  readonly id: string;
  readonly title: string;
  readonly status: string;
  readonly start_at: string;
  readonly end_at: string;
  readonly location_type: string;
  readonly contact_name: string | null;
  readonly organizer_name: string | null;
  readonly cancelled_reason: string | null;
  readonly outcome: string | null;
  readonly is_past: boolean;
  readonly version: number;
}

export function when(iso: string): string {
  return formatDateTime(iso);
}

/**
 * Booking, cancelling and recording outcomes.
 *
 * A 409 here is the database refusing a double booking, not a validation quirk,
 * so the message says the slot is taken rather than "something went wrong".
 */
export function AppointmentPanel({
  appointments,
  contactId,
}: {
  appointments: AppointmentEntry[];
  contactId?: string;
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function call(path: string, body: unknown, ifMatch?: number): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(path, { method: 'POST', body, ifMatch });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not update the appointment.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  async function onBook(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const start = String(data.get('start_at') ?? '');
    if (!start) return;
    setBusy(true);
    setError(null);
    const response = await mutate('/api/appointments', {
      method: 'POST',
      body: {
        title: String(data.get('title') ?? ''),
        start_at: new Date(start).toISOString(),
        duration_minutes: Number(data.get('duration_minutes') ?? 30),
        location_type: String(data.get('location_type') ?? 'physical'),
        contact_id: contactId ?? null,
      },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not book that slot.');
      setBusy(false);
      return;
    }
    setBusy(false);
    form.reset();
    router.refresh();
  }

  return (
    <section aria-labelledby="appointments-heading" className="space-y-4">
      <h2 id="appointments-heading" className="font-medium">Appointments</h2>

      <form onSubmit={onBook} className="flex flex-wrap items-end gap-3 rounded border p-4" noValidate>
        <div className="grow">
          <label htmlFor="appt_title" className="block text-sm">Title</label>
          <input id="appt_title" name="title" required className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="appt_start" className="block text-sm">Starts</label>
          <input id="appt_start" name="start_at" type="datetime-local" required
            className="mt-1 rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="appt_duration" className="block text-sm">Minutes</label>
          <input id="appt_duration" name="duration_minutes" type="number" min="5" step="5"
            defaultValue="30" className="mt-1 w-24 rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="appt_location" className="block text-sm">Where</label>
          <select id="appt_location" name="location_type" defaultValue="physical"
            className="mt-1 rounded border px-3 py-2">
            <option value="physical">In person</option>
            <option value="virtual">Virtual</option>
            <option value="phone">Phone</option>
          </select>
        </div>
        <button type="submit" disabled={busy} data-testid="book-appointment"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
          Book
        </button>
      </form>

      {error ? (<p role="alert" data-testid="appointment-error" className="text-sm text-destructive">{error}</p>) : null}

      {appointments.length === 0 ? (
        <p data-testid="appointments-empty" className="rounded border border-dashed p-6 text-sm text-muted-foreground">
          Nothing booked yet.
        </p>
      ) : (
        <ul className="divide-y" data-testid="appointment-rows">
          {appointments.map((appointment) => (
            <li key={appointment.id} className="flex items-center justify-between gap-4 py-3 text-sm">
              <div>
                <span className={appointment.status === 'cancelled' ? 'line-through text-muted-foreground' : ''}>
                  {appointment.title}
                </span>
                <span className="ml-2 rounded bg-muted px-2 py-0.5 text-xs uppercase">{appointment.status}</span>
                <p className="text-xs text-muted-foreground">
                  {when(appointment.start_at)} · {appointment.location_type}
                  {appointment.contact_name ? ` · ${appointment.contact_name}` : ''}
                  {appointment.organizer_name ? ` · ${appointment.organizer_name}` : ''}
                </p>
                {appointment.cancelled_reason ? (
                  <p className="text-xs text-muted-foreground">Cancelled: {appointment.cancelled_reason}</p>
                ) : null}
                {appointment.outcome ? (
                  <p className="text-xs text-muted-foreground">Outcome: {appointment.outcome}</p>
                ) : null}
              </div>
              {appointment.status === 'scheduled' || appointment.status === 'confirmed' ? (
                <div className="flex shrink-0 gap-2">
                  <button type="button" disabled={busy} data-testid={`complete-appt-${appointment.id}`}
                    onClick={() => void call(`/api/appointments/${appointment.id}/outcome`,
                      { status: 'completed' }, appointment.version)}
                    className="rounded border px-3 py-1 text-xs disabled:opacity-50">
                    Completed
                  </button>
                  <button type="button" disabled={busy} data-testid={`cancel-appt-${appointment.id}`}
                    onClick={() => void call(`/api/appointments/${appointment.id}/cancel`,
                      { reason: 'Cancelled from the app' }, appointment.version)}
                    className="rounded border px-3 py-1 text-xs disabled:opacity-50">
                    Cancel
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
