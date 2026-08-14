'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';
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

  const label = 'block text-[13px] font-medium text-foreground';

  return (
    <section className="space-y-5">
      <div className="space-y-3">
        <SectionHeader
          title="Book a slot"
          description="Two requests for the same slot cannot both succeed; the database refuses the second."
        />
        <form onSubmit={onBook} className="flex flex-wrap items-end gap-3" noValidate>
          <div className="min-w-[16rem] grow">
            <label htmlFor="appt_title" className={label}>
              Title
            </label>
            <input id="appt_title" name="title" required className={`${controlClass(false)} mt-1`} />
          </div>
          <div>
            <label htmlFor="appt_start" className={label}>
              Starts
            </label>
            <input
              id="appt_start"
              name="start_at"
              type="datetime-local"
              required
              className={`${controlClass(false)} mt-1 w-auto`}
            />
          </div>
          <div>
            <label htmlFor="appt_duration" className={label}>
              Minutes
            </label>
            <input
              id="appt_duration"
              name="duration_minutes"
              type="number"
              min="5"
              step="5"
              defaultValue="30"
              className={`${controlClass(false)} mt-1 w-20`}
            />
          </div>
          <div>
            <label htmlFor="appt_location" className={label}>
              Where
            </label>
            <select
              id="appt_location"
              name="location_type"
              defaultValue="physical"
              className={`${controlClass(false)} mt-1 w-auto`}
            >
              <option value="physical">In person</option>
              <option value="virtual">Virtual</option>
              <option value="phone">Phone</option>
            </select>
          </div>
          <Button variant="primary" type="submit" disabled={busy} data-testid="book-appointment">
            Book
          </Button>
        </form>

        {error ? (
          <p role="alert" data-testid="appointment-error" className="text-[13px] text-critical">
            {error}
          </p>
        ) : null}
      </div>

      <div className="space-y-3 border-t border-border pt-5">
        <SectionHeader title="Booked" />
        {appointments.length === 0 ? (
          <p data-testid="appointments-empty" className="text-sm text-muted-foreground">
            Nothing booked yet.
          </p>
        ) : (
          <ul
            className="divide-y divide-border rounded-lg border border-border bg-surface"
            data-testid="appointment-rows"
          >
            {appointments.map((appointment) => (
              <li
                key={appointment.id}
                className="flex flex-wrap items-start justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="flex flex-wrap items-baseline gap-2">
                    <span
                      className={
                        appointment.status === 'cancelled'
                          ? 'text-sm text-muted-foreground line-through'
                          : 'text-sm font-medium text-foreground'
                      }
                    >
                      {appointment.title}
                    </span>
                    {/* Plain words. A booked meeting and a cancelled one are
                        different facts, not different colours. */}
                    <span className="text-[13px] text-muted-foreground">{appointment.status}</span>
                  </p>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">
                    {when(appointment.start_at)} &middot; {appointment.location_type}
                    {appointment.contact_name ? ` · ${appointment.contact_name}` : ''}
                    {appointment.organizer_name ? ` · ${appointment.organizer_name}` : ''}
                  </p>
                  {appointment.cancelled_reason ? (
                    <p className="text-[13px] text-muted-foreground">
                      Cancelled: {appointment.cancelled_reason}
                    </p>
                  ) : null}
                  {appointment.outcome ? (
                    <p className="text-[13px] text-muted-foreground">
                      Outcome: {appointment.outcome}
                    </p>
                  ) : null}
                </div>

                {appointment.status === 'scheduled' || appointment.status === 'confirmed' ? (
                  <div className="flex shrink-0 gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      data-testid={`complete-appt-${appointment.id}`}
                      onClick={() =>
                        void call(
                          `/api/appointments/${appointment.id}/outcome`,
                          { status: 'completed' },
                          appointment.version,
                        )
                      }
                    >
                      Completed
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      data-testid={`cancel-appt-${appointment.id}`}
                      onClick={() =>
                        void call(
                          `/api/appointments/${appointment.id}/cancel`,
                          { reason: 'Cancelled from the app' },
                          appointment.version,
                        )
                      }
                    >
                      Cancel
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
