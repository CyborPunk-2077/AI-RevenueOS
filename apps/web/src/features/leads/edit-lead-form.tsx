'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

interface EditableLead {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly version: number;
}

export function EditLeadForm({ lead }: { lead: EditableLead }): JSX.Element {
  const router = useRouter();
  const [firstName, setFirstName] = useState(lead.first_name);
  const [lastName, setLastName] = useState(lead.last_name ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);

    const response = await mutate(`/api/leads/${lead.id}`, {
      method: 'PATCH',
      // Optimistic concurrency: a stale edit is refused, never silently applied.
      ifMatch: lead.version,
      body: { first_name: firstName, last_name: lastName || null },
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(body.error?.message ?? 'Could not save.');
      setBusy(false);
      return;
    }
    setBusy(false);
    setSaved(true);
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded border p-4" noValidate>
      <h2 className="font-medium">Edit</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="edit_first_name" className="block text-sm font-medium">First name</label>
          <input id="edit_first_name" value={firstName} onChange={(e) => setFirstName(e.target.value)}
            required className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="edit_last_name" className="block text-sm font-medium">Last name</label>
          <input id="edit_last_name" value={lastName} onChange={(e) => setLastName(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2" />
        </div>
      </div>

      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      {saved ? (
        <p role="status" data-testid="saved" className="text-sm">
          Saved.
        </p>
      ) : null}

      <button type="submit" disabled={busy} data-testid="save-lead"
        className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
        {busy ? 'Saving...' : 'Save changes'}
      </button>
    </form>
  );
}
