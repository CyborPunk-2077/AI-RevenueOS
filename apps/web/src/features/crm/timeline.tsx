'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export interface TimelineEntry {
  readonly kind: 'activity' | 'note';
  readonly id: string;
  readonly activity_type?: string;
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
  return new Date(iso).toLocaleString();
}

/**
 * The activity and note timeline for one contact or account.
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
  parent: 'contacts' | 'accounts';
  parentId: string;
  entries: TimelineEntry[];
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');

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

  async function onLogActivity(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await post(`/api/${parent}/${parentId}/activities`, {
      activity_type: String(form.get('activity_type') ?? 'call'),
      subject: String(form.get('subject') ?? ''),
      body: String(form.get('activity_body') ?? '') || null,
    });
    event.currentTarget.reset();
  }

  async function onAddNote(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await post(`/api/${parent}/${parentId}/notes`, {
      body: String(form.get('note_body') ?? ''),
      is_pinned: form.get('is_pinned') === 'on',
    });
    event.currentTarget.reset();
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
          <h3 className="text-sm font-medium">Log an activity</h3>
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
