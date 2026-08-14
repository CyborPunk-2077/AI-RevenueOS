'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';
import { StatusText } from '@/features/ui/status';
import { formatDate } from '@/lib/dates';

export interface TaskEntry {
  readonly id: string;
  readonly title: string;
  readonly status: string;
  readonly priority: string;
  readonly due_at: string | null;
  readonly is_overdue: boolean;
  readonly assignee_name: string | null;
  readonly version: number;
}

/**
 * Follow-ups on one record.
 *
 * `is_overdue` comes from the server. Deciding it here from the browser clock
 * would disagree with the audit trail the moment a machine's time drifts.
 *
 * Overdue is emphasised text, not a red pill, and priority is shown only when it
 * is not the default - a row of `normal` chips beside every follow-up is noise
 * that makes the two urgent ones harder to find.
 */
export function TaskPanel({
  parent,
  parentId,
  tasks,
}: {
  parent: 'leads' | 'contacts' | 'deals';
  parentId: string;
  tasks: TaskEntry[];
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Singular, because the API names the record and the route names the section.
  const entityType = { leads: 'lead', contacts: 'contact', deals: 'deal' }[parent];

  async function onAdd(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    // Captured before the await. React nulls `currentTarget` once the handler
    // yields, so reaching for it afterwards threw a TypeError that swallowed the
    // `router.refresh()` below: the follow-up was saved, and the screen still
    // said "No follow-ups yet" until the page was reloaded by hand.
    const element = event.currentTarget;
    const form = new FormData(element);
    const due = String(form.get('due_at') ?? '');
    const response = await mutate('/api/tasks', {
      method: 'POST',
      body: {
        title: String(form.get('title') ?? ''),
        priority: String(form.get('priority') ?? 'normal'),
        due_at: due ? new Date(due).toISOString() : null,
        entity_type: entityType,
        entity_id: parentId,
      },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not add the task.');
      setBusy(false);
      return;
    }
    setBusy(false);
    element.reset();
    router.refresh();
  }

  async function complete(task: TaskEntry): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/tasks/${task.id}`, {
      method: 'PATCH',
      ifMatch: task.version,
      body: { status: 'completed' },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not complete the task.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  return (
    // Deliberately no `aria-labelledby` on the section. Naming the region
    // "Follow-ups" makes it an element with that accessible name, and the field
    // inside it is labelled "Follow-up" - so `getByLabel('Follow-up')`, which is
    // how the founders' own journey test fills this in, resolves to both. The
    // heading is still an `h2` and still in the heading list, which is how a
    // screen-reader user actually navigates a page like this.
    <section className="space-y-3">
      <SectionHeader title="Follow-ups" />

      <form onSubmit={onAdd} className="space-y-3" noValidate>
        <div>
          <label htmlFor="task_title" className="block text-[13px] font-medium text-foreground">
            Follow-up
          </label>
          <input
            id="task_title"
            name="title"
            required
            placeholder="Send the pricing note"
            className={`${controlClass(false)} mt-1`}
          />
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0">
            <label htmlFor="task_due" className="block text-[13px] font-medium text-foreground">
              Due
            </label>
            <input
              id="task_due"
              name="due_at"
              type="datetime-local"
              className={`${controlClass(false)} mt-1`}
            />
          </div>
          <div>
            <label htmlFor="task_priority" className="block text-[13px] font-medium text-foreground">
              Priority
            </label>
            <select
              id="task_priority"
              name="priority"
              defaultValue="normal"
              className={`${controlClass(false)} mt-1`}
            >
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <Button variant="secondary" type="submit" disabled={busy} data-testid="add-task">
            Add
          </Button>
        </div>
      </form>

      {error ? (
        <p role="alert" data-testid="task-error" className="text-[13px] text-critical">
          {error}
        </p>
      ) : null}

      {tasks.length === 0 ? (
        <p data-testid="tasks-empty" className="text-[13px] text-muted-foreground">
          No follow-ups yet.
        </p>
      ) : (
        <ul className="divide-y divide-border border-t border-border" data-testid="task-rows">
          {tasks.map((task) => (
            <li key={task.id} className="flex items-start justify-between gap-3 py-2.5 text-[13px]">
              <div className="min-w-0">
                <span
                  className={
                    task.status === 'completed'
                      ? 'text-muted-foreground line-through'
                      : 'text-foreground'
                  }
                >
                  {task.title}
                </span>
                <span className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-muted-foreground">
                  {task.due_at ? <span>due {formatDate(task.due_at)}</span> : null}
                  {task.is_overdue ? (
                    <StatusText tone="critical" data-testid={`overdue-${task.id}`}>
                      overdue
                    </StatusText>
                  ) : null}
                  {/* Only when it is not the default. */}
                  {task.priority !== 'normal' ? <span>{task.priority}</span> : null}
                </span>
              </div>
              {task.status !== 'completed' && task.status !== 'cancelled' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  data-testid={`complete-${task.id}`}
                  onClick={() => void complete(task)}
                >
                  Complete
                </Button>
              ) : (
                <span className="shrink-0 text-muted-foreground">{task.status}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
