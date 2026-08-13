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
  readonly outcome?: string | null;
  readonly outcome_label?: string | null;
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
 * What each kind of contact can end in, in the words a salesperson would use.
 *
 * This mirrors `domain/leads/first_response.OUTCOMES_BY_CHANNEL`. The server
 * rejects a pairing that is not in its own copy, so the worst a drift here can
 * do is offer something the API refuses - never record something the dashboard
 * then misreads.
 *
 * The starred options are the ones that mean somebody actually got through. It
 * is worth the founders knowing which those are: they are exactly the ones that
 * stop a prospect showing as waiting.
 */
const OUTCOMES_BY_TYPE: Record<string, ReadonlyArray<{ value: string; label: string }>> = {
  call: [
    { value: 'spoke', label: 'Spoke with them' },
    { value: 'no_answer', label: 'No answer / missed' },
  ],
  meeting: [
    { value: 'meeting_held', label: 'Meeting happened' },
    { value: 'meeting_scheduled', label: 'Scheduled for later' },
    { value: 'no_show', label: 'They did not come' },
    { value: 'cancelled', label: 'Cancelled' },
  ],
  email: [
    { value: 'sent', label: 'Sent it' },
    { value: 'received', label: 'They wrote to us' },
    { value: 'failed', label: 'Could not send' },
  ],
  whatsapp: [
    { value: 'sent', label: 'Sent it' },
    { value: 'received', label: 'They messaged us' },
    { value: 'failed', label: 'Could not send' },
  ],
  task: [],
};

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
  // Drives which outcomes are offered. "How did it go" only makes sense once you
  // know what "it" was, and offering "no answer" against an email taught the
  // founders to ignore the field.
  const [activityType, setActivityType] = useState('call');

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

    await post(`/api/${parent}/${parentId}/activities`, {
      activity_type: String(form.get('activity_type') ?? 'call'),
      subject: String(form.get('subject') ?? ''),
      body: String(form.get('activity_body') ?? '') || null,
      // Direction and outcome together decide whether this answered the
      // prospect, and the server decides that - not this form. It used to paste
      // the outcome onto the subject line, which meant a call nobody picked up
      // still cleared the "waiting for a reply" warning.
      direction: String(form.get('direction') ?? 'outbound'),
      outcome: outcome || null,
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
              value={activityType}
              onChange={(e) => setActivityType(e.target.value)}
              data-testid="activity-type"
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
          {(OUTCOMES_BY_TYPE[activityType] ?? []).length > 0 ? (
            <div>
              <label htmlFor="outcome" className="block text-sm">
                What actually happened
              </label>
              <select
                id="outcome"
                name="outcome"
                defaultValue=""
                data-testid="activity-outcome"
                className="mt-1 w-full rounded border px-3 py-2"
              >
                <option value="">Not recorded</option>
                {(OUTCOMES_BY_TYPE[activityType] ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-muted-foreground">
                Only contact that actually reached the customer counts as replying to them. A
                missed call or a meeting still in the diary leaves this prospect waiting, which is
                what the Today page will keep telling you.
              </p>
            </div>
          ) : null}
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
                      {/* What came of it, in plain words. Six weeks later this is
                          the difference between "we called them" and "we tried
                          to call them", and only one of those answered anybody. */}
                      {entry.outcome_label ? (
                        <span
                          data-testid={`activity-outcome-${entry.id}`}
                          className="ml-2 rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                        >
                          {entry.outcome_label}
                        </span>
                      ) : null}
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
