'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button } from '@/features/ui/controls';
import { DataTable, TableEmpty, type Column } from '@/features/ui/data-table';
import { MissingValue, StatusText } from '@/features/ui/status';
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

/** Business names for the prospects these follow-ups hang off, resolved once. */
export interface AboutRecord {
  readonly label: string;
  readonly href: string;
}

const FALLBACK_LABEL: Record<string, string> = {
  lead: 'A prospect',
  contact: 'A contact',
  deal: 'A deal',
};

function about(task: FollowUp, businesses: Record<string, AboutRecord>): AboutRecord | null {
  if (!task.entity_id || !task.entity_type) return null;
  const known = businesses[task.entity_id];
  if (known) return known;
  const path =
    task.entity_type === 'lead'
      ? 'leads'
      : task.entity_type === 'contact'
        ? 'contacts'
        : task.entity_type === 'deal'
          ? 'deals'
          : null;
  if (!path) return null;
  // Named by what it is, because the tasks endpoint returns no name for a deal
  // or a contact and inventing one would be worse than saying which kind of
  // record it is.
  return { label: FALLBACK_LABEL[task.entity_type] ?? 'A record', href: `/${path}/${task.entity_id}` };
}

/**
 * The shared promise queue, with a Done button on every row.
 *
 * Completing from the queue rather than only from the record matters more than
 * it sounds: the reason follow-ups rot in other tools is that closing one costs
 * three clicks and a page load, so nobody does it, so the queue stops being
 * true. This is also the interaction that proves the dashboard is real - the
 * Today figure moves the moment a row here is closed - so it has to feel
 * immediate.
 *
 * **Overdue is ordering, words and a 2px rule, never a red pill.** The overdue
 * rows are at the top because that is where the eye starts; the due cell says
 * "Overdue" in emphasised text; and the rule down the left makes the block of
 * them findable while scanning. All three survive a black-and-white print.
 */
export function FollowUpList({
  tasks,
  businesses,
  truncated,
}: {
  tasks: FollowUp[];
  businesses: Record<string, AboutRecord>;
  truncated: boolean;
}): JSX.Element {
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

  // Overdue first, then soonest, then anything with no date at all. The server
  // orders by due date; this only decides where undated promises go, and they go
  // last because a promise with no date is not late, it is unscheduled.
  const ordered = [...tasks].sort((a, b) => {
    if (a.is_overdue !== b.is_overdue) return a.is_overdue ? -1 : 1;
    if (!a.due_at) return 1;
    if (!b.due_at) return -1;
    return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
  });

  const columns: Array<Column<FollowUp>> = [
    {
      key: 'title',
      header: 'Follow-up',
      width: '32%',
      cell: (task) => (
        <span className="flex items-baseline gap-2">
          <span
            className={
              task.status === 'completed'
                ? 'truncate text-muted-foreground line-through'
                : 'truncate font-medium text-foreground'
            }
            title={task.title}
          >
            {task.title}
          </span>
          {/* Only where it is not the default. A row of `normal` markers is noise
              that makes the two urgent ones harder to find. */}
          {task.priority === 'urgent' || task.priority === 'high' ? (
            <span className="shrink-0 text-[13px] text-muted-foreground">{task.priority}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'about',
      header: 'About',
      width: '22%',
      cell: (task) => {
        const record = about(task, businesses);
        return record ? (
          <Link
            href={record.href}
            data-testid={`follow-up-link-${task.id}`}
            title={record.label}
            className="block truncate text-accent underline-offset-2 hover:underline"
          >
            {record.label}
          </Link>
        ) : (
          <span className="text-muted-foreground">Not linked</span>
        );
      },
    },
    {
      key: 'owner',
      header: 'Owner',
      width: '16%',
      dropAt: 900,
      cell: (task) =>
        task.assignee_name ? (
          <span className="block truncate text-secondary-foreground">{task.assignee_name}</span>
        ) : (
          <MissingValue>Unassigned</MissingValue>
        ),
    },
    {
      key: 'due',
      header: 'Due',
      align: 'right',
      width: '20%',
      cell: (task) =>
        task.due_at ? (
          task.is_overdue ? (
            <span data-testid={`overdue-${task.id}`}>
              <StatusText tone="critical">Overdue</StatusText>
              <span className="ml-2 text-muted-foreground">{formatDate(task.due_at)}</span>
            </span>
          ) : (
            <span className="text-secondary-foreground">{formatDate(task.due_at)}</span>
          )
        ) : (
          <span className="text-muted-foreground">No date</span>
        ),
    },
    {
      key: 'action',
      header: 'Action',
      align: 'right',
      width: '10%',
      cell: (task) =>
        task.status === 'completed' || task.status === 'cancelled' ? (
          <span className="text-[13px] text-muted-foreground">{task.status}</span>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            disabled={busyId === task.id}
            data-testid={`done-${task.id}`}
            onClick={() => void complete(task)}
          >
            Done
          </Button>
        ),
    },
  ];

  return (
    <div className="space-y-2">
      {error ? (
        <p role="alert" data-testid="follow-up-error" className="text-[13px] text-critical">
          {error}
        </p>
      ) : null}

      <DataTable
        caption="Follow-ups, overdue first and then soonest due"
        columns={columns}
        rows={ordered}
        rowKey={(task) => task.id}
        bodyTestId="follow-up-rows"
        severity={(task) => (task.is_overdue ? { tone: 'critical', label: 'Overdue' } : null)}
        empty={
          <TableEmpty
            title="No follow-ups here"
            description="Follow-ups are created on a prospect or a deal. Open one and add the next action."
          />
        }
      />

      {truncated ? (
        <p className="text-[13px] text-muted-foreground">
          Showing the 100 nearest follow-ups. Anything further out is not listed here yet.
        </p>
      ) : null}
    </div>
  );
}
