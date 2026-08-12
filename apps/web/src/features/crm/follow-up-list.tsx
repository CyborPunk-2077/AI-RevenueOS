'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { StatusPill } from '@/features/ui/primitives';
import { formatDate } from '@/lib/dates';

export interface FollowUp {
  readonly id: string;
  readonly title: string;
  readonly status: string;
  readonly priority: string;
  readonly entity_type: string | null;
  readonly entity_id: string | null;
  readonly assignee_name: string | null;
  readonly due_at: string | null;
  readonly is_overdue: boolean;
  readonly version: number;
}

function href(task: FollowUp): string | null {
  if (!task.entity_id) return null;
  if (task.entity_type === 'lead') return `/leads/${task.entity_id}`;
  if (task.entity_type === 'contact') return `/contacts/${task.entity_id}`;
  if (task.entity_type === 'deal') return `/deals/${task.entity_id}`;
  return null;
}

const WHAT: Record<string, string> = {
  lead: 'Prospect',
  contact: 'Contact',
  deal: 'Deal',
};

/**
 * The follow-up queue with a Done button on every row.
 *
 * Completing from the queue rather than only from the record matters more than
 * it sounds: the reason follow-ups rot in other tools is that closing one costs
 * three clicks and a page load, so nobody does it, so the queue stops being true.
 */
export function FollowUpList({ tasks }: { tasks: FollowUp[] }): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function complete(task: FollowUp): Promise<void> {
    setBusyId(task.id);
    setError(null);
    const response = await mutate(`/api/tasks/${task.id}`, {
      method: 'PATCH',
      ifMatch: task.version,
      body: { status: 'completed' },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not close that follow-up.');
      setBusyId(null);
      return;
    }
    setBusyId(null);
    router.refresh();
  }

  return (
    <>
      {error ? (
        <p role="alert" data-testid="follow-up-error" className="px-5 pt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Follow-ups, soonest due first</caption>
          <thead>
            <tr className="border-b border-border text-xs uppercase text-muted-foreground">
              <th scope="col" className="px-5 py-3">
                Follow-up
              </th>
              <th scope="col" className="px-5 py-3">
                About
              </th>
              <th scope="col" className="px-5 py-3">
                Owner
              </th>
              <th scope="col" className="px-5 py-3">
                Due
              </th>
              <th scope="col" className="px-5 py-3">
                <span className="sr-only">Action</span>
              </th>
            </tr>
          </thead>
          <tbody data-testid="follow-up-rows">
            {tasks.map((task) => {
              const link = href(task);
              return (
                <tr key={task.id} className="border-b border-border/60 hover:bg-surface-sunken">
                  <td className="px-5 py-3">
                    <span
                      className={
                        task.status === 'completed' ? 'text-muted-foreground line-through' : ''
                      }
                    >
                      {task.title}
                    </span>
                    {task.priority === 'urgent' || task.priority === 'high' ? (
                      <span className="ml-2 rounded bg-muted px-2 py-0.5 text-xs">
                        {task.priority}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-5 py-3">
                    {link ? (
                      <Link
                        href={link}
                        data-testid={`follow-up-link-${task.id}`}
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        {WHAT[task.entity_type ?? ''] ?? 'Record'}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">Not linked</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-muted-foreground">
                    {task.assignee_name ?? 'Unassigned'}
                  </td>
                  <td className="tabular px-5 py-3">
                    {task.due_at ? (
                      <>
                        <span className="text-muted-foreground">
                          {formatDate(task.due_at)}
                        </span>
                        {task.is_overdue ? (
                          <span className="ml-2" data-testid={`overdue-${task.id}`}>
                            <StatusPill tone="danger">overdue</StatusPill>
                          </span>
                        ) : null}
                      </>
                    ) : (
                      <span className="text-muted-foreground">No date</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {task.status === 'completed' || task.status === 'cancelled' ? (
                      <span className="text-xs text-muted-foreground">{task.status}</span>
                    ) : (
                      <button
                        type="button"
                        disabled={busyId === task.id}
                        data-testid={`done-${task.id}`}
                        onClick={() => void complete(task)}
                        className="rounded-md border border-border px-3 py-1 text-xs disabled:opacity-50"
                      >
                        Done
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
