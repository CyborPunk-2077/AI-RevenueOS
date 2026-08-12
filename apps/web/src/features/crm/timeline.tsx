'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { formatDateTime } from '@/lib/dates';

export interface TimelineEntry {
  readonly kind: 'activity' | 'note';
  readonly id: string;
  readonly activity_type?: string;
  readonly direction?: string | null;
  readonly subject?: string;
  readonly body: string | null;
  readonly actor_name: string | null;
  readonly editable: boolean;
  readonly is_pinned?: boolean;
  readonly version?: number;
  readonly created_at: string | null;
}

function when(iso: string | null): string {
  if (!iso) return '';
  return formatDateTime(iso);
}

/**
 * The activity and note timeline for one lead, contact or account.
 *
 * Leads are included deliberately: the call that happened while somebody was
 * still a prospect is the same record after they become a customer, so the
 * history does not restart at conversion.
 *
 * `editable` comes from the server, which knows who wrote each note. The button
 * is hidden when it is false and the API refuses the edit regardless, so the two
 * cannot disagree in the caller's favour.
 */
export function Timeline({
  parent,
  parentId,
  entries,
}: {
  parent: 'leads' | 'contacts' | 'accounts';
  parentId: string;
  entries: TimelineEntry[];
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');

  // Singular, because the tasks API names the record while the route names the
  // section.
  const entityType = { leads: 'lead', contacts: 'contact', accounts: 'account' }[parent];

  async function post(path: string, body: unknown): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(path, { method: 'POST', body });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      setError(payload.error?.message ?? 'Could not save.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  // Both handlers capture the form element before awaiting. React nulls
  // `currentTarget` once a handler yields, so touching it after the await threw a
  // TypeError and left the submitted text sitting in the boxes.
  /**
   * One submit records what happened *and* what happens next.
   *
   * A call almost always ends with "I'll send it Tuesday". Making that a second
   * trip to a different form on the same page is how the follow-up stops being
   * recorded at all - and an unrecorded follow-up is precisely the leak this
   * product exists to close. The activity is written first and is never rolled
   * back if the follow-up fails; a recorded call with no follow-up is a smaller
   * lie than a follow-up with no call.
   */
  async function onLogActivity(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    const outcome = String(form.get('outcome') ?? '').trim();
    const subject = String(form.get('subject') ?? '');

    await post(`/api/${parent}/${parentId}/activities`, {
      activity_type: String(form.get('activity_type') ?? 'call'),
      // The outcome leads the subject line, because that is what a person scans
      // the timeline for six weeks later.
      subject: outcome ? `${outcome} — ${subject}` : subject,
      body: String(form.get('activity_body') ?? '') || null,
      // Only an outbound contact counts as answering a prospect, so the server
      // needs to be told which this was rather than assuming.
      direction: String(form.get('direction') ?? 'outbound'),
    });

    const nextAction = String(form.get('next_action') ?? '').trim();
    if (nextAction) {
      const due = String(form.get('next_due') ?? '');
      await post('/api/tasks', {
        title: nextAction,
        due_at: due ? new Date(due).toISOString() : null,
        priority: 'normal',
        entity_type: entityType,
        entity_id: parentId,
        is_next_action: true,
      });
    }
    element.reset();
  }

  async function onAddNote(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    await post(`/api/${parent}/${parentId}/notes`, {
      body: String(form.get('note_body') ?? ''),
      is_pinned: form.get('is_pinned') === 'on',
    });
    element.reset();
  }

  async function onSaveNote(entry: TimelineEntry): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/notes/${entry.id}`, {
      method: 'PATCH',
      ifMatch: entry.version,
      body: { body: draft },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      setError(payload.error?.message ?? 'Could not save the note.');
      setBusy(false);
      return;
    }
    setBusy(false);
    setEditingId(null);
    router.refresh();
  }

  return (
    <section aria-labelledby="timeline-heading" className="space-y-6">
      <h2 id="timeline-heading" className="font-medium">
        Timeline
      </h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <form onSubmit={onLogActivity} className="space-y-3 rounded border p-4" noValidate>
          <h3 className="text-sm font-medium">Record an outreach you made</h3>
          <p className="text-xs text-muted-foreground">
            You make the call or send the message yourself; Sangam records it. Nothing here sends
            anything.
          </p>
          <div>
            <label htmlFor="activity_type" className="block text-sm">
              Type
            </label>
            <select
              id="activity_type"
              name="activity_type"
              defaultValue="call"
              className="mt-1 w-full rounded border px-3 py-2"
            >
              <option value="call">Call</option>
              <option value="meeting">Meeting</option>
              <option value="email">Email</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="task">Task</option>
            </select>
          </div>
          <div>
            <label htmlFor="direction" className="block text-sm">
              Who got in touch
            </label>
            <select
              id="direction"
              name="direction"
              defaultValue="outbound"
              data-testid="activity-direction"
              className="mt-1 w-full rounded border px-3 py-2"
            >
              <option value="outbound">We contacted them</option>
              <option value="inbound">They contacted us</option>
            </select>
          </div>
          <div>
            <label htmlFor="subject" className="block text-sm">
              Subject
            </label>
            <input
              id="subject"
              name="subject"
              required
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </div>
          <div>
            <label htmlFor="outcome" className="block text-sm">
              How did it go
            </label>
            <select
              id="outcome"
              name="outcome"
              defaultValue=""
              data-testid="activity-outcome"
              className="mt-1 w-full rounded border px-3 py-2"
            >
              <option value="">Not recorded</option>
              <option value="Spoke to them">Spoke to them</option>
              <option value="No answer">No answer</option>
              <option value="Call back later">Asked to call back later</option>
              <option value="Wants a demo">Wants a demo</option>
              <option value="Sent information">Sent information</option>
              <option value="Not interested">Not interested</option>
            </select>
          </div>
          <div>
            <label htmlFor="activity_body" className="block text-sm">
              Details
            </label>
            <textarea
              id="activity_body"
              name="activity_body"
              rows={2}
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </div>

          {/* The next action is part of this form, not a separate errand. Most
              calls end with a promise, and a promise recorded ten minutes later
              is usually a promise not recorded. */}
          <div className="rounded border border-dashed p-3">
            <label htmlFor="next_action" className="block text-sm font-medium">
              And what happens next
            </label>
            <input
              id="next_action"
              name="next_action"
              placeholder="Send the pricing note"
              data-testid="next-action-input"
              className="mt-1 w-full rounded border px-3 py-2"
            />
            <label htmlFor="next_due" className="mt-2 block text-sm">
              By when
            </label>
            <input
              id="next_due"
              name="next_due"
              type="datetime-local"
              data-testid="next-action-due"
              className="mt-1 w-full rounded border px-3 py-2"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              Leave blank if there is nothing to do next. Anything typed here becomes a follow-up
              on this prospect.
            </p>
          </div>

          <button
            type="submit"
            disabled={busy}
            data-testid="log-activity"
            className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
          >
            Log activity
          </button>
        </form>

        <form onSubmit={onAddNote} className="space-y-3 rounded border p-4" noValidate>
          <h3 className="text-sm font-medium">Add a note</h3>
          <div>
            <label htmlFor="note_body" className="block text-sm">
              Note
            </label>
            <textarea
              id="note_body"
              name="note_body"
              rows={4}
              required
              className="mt-1 w-full rounded border px-3 py-2"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="is_pinned" />
            Pin to the top
          </label>
          <button
            type="submit"
            disabled={busy}
            data-testid="add-note"
            className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
          >
            Add note
          </button>
        </form>
      </div>

      {error ? (
        <p role="alert" data-testid="timeline-error" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {entries.length === 0 ? (
        <p
          data-testid="timeline-empty"
          className="rounded border border-dashed p-6 text-sm text-muted-foreground"
        >
          Nothing logged yet. Record a call or add a note above.
        </p>
      ) : (
        <ol className="space-y-3" data-testid="timeline-entries">
          {entries.map((entry) => (
            <li key={`${entry.kind}-${entry.id}`} className="rounded border p-4 text-sm">
              <div className="flex items-baseline justify-between gap-4">
                <span className="font-medium">
                  {entry.kind === 'activity' ? (
                    <>
                      <span className="rounded bg-muted px-2 py-0.5 text-xs uppercase">
                        {entry.activity_type}
                      </span>{' '}
                      {/* Which way it went, because "we called them" and "they
                          called us" are different events and only one of them
                          answers an enquiry. */}
                      {entry.direction ? (
                        <span className="mr-1 text-xs text-muted-foreground">
                          {entry.direction === 'inbound' ? 'they contacted us ·' : 'we contacted them ·'}
                        </span>
                      ) : null}
                      {entry.subject}
                    </>
                  ) : (
                    <>
                      <span className="rounded bg-muted px-2 py-0.5 text-xs uppercase">note</span>
                      {entry.is_pinned ? (
                        <span className="ml-2 text-xs text-muted-foreground">pinned</span>
                      ) : null}
                    </>
                  )}
                </span>
                <span className="whitespace-nowrap text-xs text-muted-foreground">
                  {entry.actor_name ?? 'Unknown'} &middot; {when(entry.created_at)}
                </span>
              </div>

              {editingId === entry.id ? (
                <div className="mt-2 space-y-2">
                  <label htmlFor={`note-${entry.id}`} className="sr-only">
                    Note body
                  </label>
                  <textarea
                    id={`note-${entry.id}`}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={3}
                    className="w-full rounded border px-3 py-2"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      data-testid={`save-note-${entry.id}`}
                      onClick={() => void onSaveNote(entry)}
                      className="rounded bg-primary px-3 py-1 text-primary-foreground disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      className="rounded border px-3 py-1"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {entry.body ? <p className="mt-2 whitespace-pre-wrap">{entry.body}</p> : null}
                  {entry.kind === 'note' && entry.editable ? (
                    <button
                      type="button"
                      data-testid={`edit-note-${entry.id}`}
                      onClick={() => {
                        setEditingId(entry.id);
                        setDraft(entry.body ?? '');
                      }}
                      className="mt-2 text-xs underline"
                    >
                      Edit
                    </button>
                  ) : null}
                </>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
