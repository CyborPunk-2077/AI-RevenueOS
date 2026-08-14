'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { ChannelIcon } from '@/features/ui/channel-icon';
import { Button, Checkbox, controlClass } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';
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
 * The activity and note history for one lead, contact or account.
 *
 * **Append-only, and it looks it.** There is no edit or delete affordance on an
 * activity, because the database trigger would refuse one and an affordance that
 * cannot work is worse than none. A note may be edited by its author only, which
 * the server decides and this reflects.
 *
 * Leads are included deliberately: the call that happened while somebody was
 * still a prospect is the same record after they become a customer, so the
 * history does not restart at conversion.
 *
 * Direction is stated in words - "We contacted them" / "They contacted us" -
 * because only outbound contact answers an enquiry, and a coloured dot cannot
 * carry that distinction.
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

  const label = 'block text-[13px] font-medium text-foreground';

  return (
    <section aria-labelledby="timeline-heading" className="space-y-5">
      <SectionHeader
        id="timeline-heading"
        title="Activity"
        description="Append-only: once written, nothing here can be edited or removed."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <form onSubmit={onLogActivity} className="space-y-3" noValidate>
          <h3 className="text-[13px] font-semibold text-foreground">Record an outreach you made</h3>
          <p className="text-[13px] text-muted-foreground">
            You make the contact yourself; this only records it. Nothing here sends anything.
          </p>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="activity_type" className={label}>
                Type
              </label>
              <select
                id="activity_type"
                name="activity_type"
                value={activityType}
                onChange={(e) => setActivityType(e.target.value)}
                data-testid="activity-type"
                className={`${controlClass(false)} mt-1`}
              >
                <option value="call">Call</option>
                <option value="meeting">Meeting</option>
                <option value="email">Email</option>
                <option value="whatsapp">WhatsApp</option>
                <option value="task">Task</option>
              </select>
            </div>
            <div>
              <label htmlFor="direction" className={label}>
                Who got in touch
              </label>
              <select
                id="direction"
                name="direction"
                defaultValue="outbound"
                data-testid="activity-direction"
                className={`${controlClass(false)} mt-1`}
              >
                <option value="outbound">We contacted them</option>
                <option value="inbound">They contacted us</option>
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="subject" className={label}>
              Subject
            </label>
            <input id="subject" name="subject" required className={`${controlClass(false)} mt-1`} />
          </div>

          {(OUTCOMES_BY_TYPE[activityType] ?? []).length > 0 ? (
            <div>
              <label htmlFor="outcome" className={label}>
                What actually happened
              </label>
              <select
                id="outcome"
                name="outcome"
                defaultValue=""
                data-testid="activity-outcome"
                className={`${controlClass(false)} mt-1`}
              >
                <option value="">Not recorded</option>
                {(OUTCOMES_BY_TYPE[activityType] ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[13px] text-muted-foreground">
                Only contact that actually reached the customer counts as a reply. A missed call
                leaves this prospect waiting.
              </p>
            </div>
          ) : null}

          <div>
            <label htmlFor="activity_body" className={label}>
              Details
            </label>
            <textarea
              id="activity_body"
              name="activity_body"
              rows={2}
              className={`${controlClass(false)} mt-1`}
            />
          </div>

          {/* The next action is part of this form, not a separate errand. Most
              calls end with a promise, and a promise recorded ten minutes later
              is usually a promise not recorded. */}
          <div className="space-y-2 border-t border-border pt-3">
            <div>
              <label htmlFor="next_action" className={label}>
                And what happens next
              </label>
              <input
                id="next_action"
                name="next_action"
                placeholder="Send the pricing note"
                data-testid="next-action-input"
                className={`${controlClass(false)} mt-1`}
              />
            </div>
            <div>
              <label htmlFor="next_due" className={label}>
                By when
              </label>
              <input
                id="next_due"
                name="next_due"
                type="datetime-local"
                data-testid="next-action-due"
                className={`${controlClass(false)} mt-1`}
              />
            </div>
            <p className="text-[13px] text-muted-foreground">
              Anything typed here becomes a follow-up on this prospect.
            </p>
          </div>

          <Button variant="primary" type="submit" disabled={busy} data-testid="log-activity">
            Log activity
          </Button>
        </form>

        <form onSubmit={onAddNote} className="space-y-3" noValidate>
          <h3 className="text-[13px] font-semibold text-foreground">Add a note</h3>
          <p className="text-[13px] text-muted-foreground">Only you can edit your own notes.</p>
          <div>
            <label htmlFor="note_body" className={label}>
              Note
            </label>
            <textarea
              id="note_body"
              name="note_body"
              rows={5}
              required
              className={`${controlClass(false)} mt-1`}
            />
          </div>
          <Checkbox id="is_pinned" name="is_pinned" label="Pin to the top" />
          <div>
            <Button variant="secondary" type="submit" disabled={busy} data-testid="add-note">
              Add note
            </Button>
          </div>
        </form>
      </div>

      {error ? (
        <p role="alert" data-testid="timeline-error" className="text-[13px] text-critical">
          {error}
        </p>
      ) : null}

      {entries.length === 0 ? (
        <p data-testid="timeline-empty" className="border-t border-border pt-5 text-sm text-muted-foreground">
          Nothing logged yet. Record a call or add a note above.
        </p>
      ) : (
        <ol className="border-t border-border" data-testid="timeline-entries">
          {entries.map((entry) => (
            <li key={`${entry.kind}-${entry.id}`} className="border-b border-border py-3.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-sm">
                  {entry.kind === 'activity' ? (
                    <>
                      {entry.activity_type ? (
                        <ChannelIcon channel={entry.activity_type} className="self-center" />
                      ) : null}
                      {/* Which way it went, because "we called them" and "they
                          called us" are different events and only one of them
                          answers an enquiry. */}
                      {entry.direction ? (
                        <span className="text-muted-foreground">
                          {entry.direction === 'inbound' ? 'They contacted us' : 'We contacted them'}
                        </span>
                      ) : null}
                      <span className="font-medium text-foreground">{entry.subject}</span>
                      {/* What came of it, in plain words. Six weeks later this is
                          the difference between "we called them" and "we tried to
                          call them", and only one of those answered anybody. */}
                      {entry.outcome_label ? (
                        <span
                          data-testid={`activity-outcome-${entry.id}`}
                          className="text-muted-foreground"
                        >
                          &middot; {entry.outcome_label}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <span className="text-muted-foreground">Note</span>
                      {entry.is_pinned ? (
                        <span className="text-muted-foreground">&middot; pinned</span>
                      ) : null}
                    </>
                  )}
                </p>
                <p className="whitespace-nowrap text-[13px] text-muted-foreground">
                  {entry.actor_name ?? 'Unknown'} &middot; {when(entry.created_at)}
                </p>
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
                    className={controlClass(false)}
                  />
                  <div className="flex gap-2">
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={busy}
                      data-testid={`save-note-${entry.id}`}
                      onClick={() => void onSaveNote(entry)}
                    >
                      Save
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setEditingId(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <>
                  {entry.body ? (
                    <p className="mt-1 max-w-reading whitespace-pre-wrap text-sm text-secondary-foreground">
                      {entry.body}
                    </p>
                  ) : null}
                  {/* Notes only. An activity has no edit control because the
                      database would refuse one. */}
                  {entry.kind === 'note' && entry.editable ? (
                    <button
                      type="button"
                      data-testid={`edit-note-${entry.id}`}
                      onClick={() => {
                        setEditingId(entry.id);
                        setDraft(entry.body ?? '');
                      }}
                      className="mt-1 text-[13px] text-accent underline-offset-2 hover:underline"
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
