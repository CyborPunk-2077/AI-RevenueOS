'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export interface Member {
  readonly id: string;
  readonly full_name: string;
  readonly email: string;
  readonly is_active: boolean;
}

/**
 * Who owns this enquiry.
 *
 * The single most common way an SME loses a prospect is that everybody assumed
 * somebody else was calling. So ownership is a first-class control on the record
 * rather than a column buried in a settings screen, and "Unassigned" is stated
 * out loud instead of being rendered as an empty cell.
 *
 * The version goes up with `If-Match`, so two people reassigning the same lead at
 * once produces a refusal rather than a silent last-write-wins.
 */
export function LeadOwner({
  leadId,
  version,
  assigneeId,
  members,
}: {
  leadId: string;
  version: number;
  assigneeId: string | null;
  members: Member[];
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const current = members.find((m) => m.id === assigneeId) ?? null;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const chosen = String(new FormData(event.currentTarget).get('assignee_id') ?? '');
    const response = await mutate(`/api/leads/${leadId}`, {
      method: 'PATCH',
      ifMatch: version,
      body: { assignee_id: chosen === '' ? null : chosen },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not change the owner.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3" noValidate>
      <div>
        <label htmlFor="assignee_id" className="block text-sm text-muted-foreground">
          Owner
        </label>
        <select
          id="assignee_id"
          name="assignee_id"
          defaultValue={assigneeId ?? ''}
          data-testid="lead-owner-select"
          className="mt-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
        >
          <option value="">Unassigned</option>
          {members
            .filter((m) => m.is_active)
            .map((member) => (
              <option key={member.id} value={member.id}>
                {member.full_name}
              </option>
            ))}
        </select>
      </div>
      <button
        type="submit"
        disabled={busy}
        data-testid="assign-lead"
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
      >
        {current ? 'Reassign' : 'Assign'}
      </button>
      <p data-testid="lead-owner-current" className="pb-2 text-sm text-muted-foreground">
        Currently {current ? current.full_name : 'unassigned'}
      </p>
      {error ? (
        <p role="alert" data-testid="owner-error" className="w-full text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}
