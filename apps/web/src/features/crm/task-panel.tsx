'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

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
 */
export function TaskPanel({
  parent,
  parentId,
  tasks,
}: {
  parent: 'contacts' | 'deals';
  parentId: string;
  tasks: TaskEntry[];
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const entityType = parent === 'contacts' ? 'contact' : 'deal';

  async function onAdd(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(event.currentTarget);
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
    event.currentTarget.reset();
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
    <section aria-labelledby="tasks-heading" className="space-y-4">
      <h2 id="tasks-heading" className="font-medium">Tasks</h2>

      <form onSubmit={onAdd} className="flex flex-wrap items-end gap-3 rounded border p-4" noValidate>
        <div className="grow">
          <label htmlFor="task_title" className="block text-sm">Follow-up</label>
          <input id="task_title" name="title" required className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="task_due" className="block text-sm">Due</label>
          <input id="task_due" name="due_at" type="datetime-local" className="mt-1 rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="task_priority" className="block text-sm">Priority</label>
          <select id="task_priority" name="priority" defaultValue="normal" className="mt-1 rounded border px-3 py-2">
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
        </div>
        <button type="submit" disabled={busy} data-testid="add-task"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
          Add task
        </button>
      </form>

      {error ? (<p role="alert" data-testid="task-error" className="text-sm text-destructive">{error}</p>) : null}

      {tasks.length === 0 ? (
        <p data-testid="tasks-empty" className="rounded border border-dashed p-6 text-sm text-muted-foreground">
          No follow-ups yet.
        </p>
      ) : (
        <ul className="divide-y" data-testid="task-rows">
          {tasks.map((task) => (
            <li key={task.id} className="flex items-center justify-between gap-4 py-2 text-sm">
              <div>
                <span className={task.status === 'completed' ? 'line-through text-muted-foreground' : ''}>
                  {task.title}
                </span>
                <span className="ml-2 rounded bg-muted px-2 py-0.5 text-xs">{task.priority}</span>
                {task.is_overdue ? (
                  <span data-testid={`overdue-${task.id}`} className="ml-2 text-xs font-medium text-destructive">
                    overdue
                  </span>
                ) : null}
                {task.due_at ? (
                  <span className="ml-2 text-xs text-muted-foreground">
                    due {new Date(task.due_at).toLocaleDateString()}
                  </span>
                ) : null}
              </div>
              {task.status !== 'completed' && task.status !== 'cancelled' ? (
                <button type="button" disabled={busy} data-testid={`complete-${task.id}`}
                  onClick={() => void complete(task)} className="rounded border px-3 py-1 text-xs disabled:opacity-50">
                  Complete
                </button>
              ) : (
                <span className="text-xs text-muted-foreground">{task.status}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
