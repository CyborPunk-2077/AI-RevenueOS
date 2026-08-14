'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';

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
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      {/*
        Renaming only. The business name lives in `capture.company` and is not
        editable here yet, which is stated rather than implied by an input that
        would silently write to the wrong field.
      */}
      <SectionHeader
        title="Contact name"
        description="The person on this record. The business name is not editable here."
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="edit_first_name" className="block text-[13px] font-medium text-foreground">
            First name
          </label>
          <input
            id="edit_first_name"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            required
            className={`${controlClass(false)} mt-1`}
          />
        </div>
        <div>
          <label htmlFor="edit_last_name" className="block text-[13px] font-medium text-foreground">
            Last name
          </label>
          <input
            id="edit_last_name"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            className={`${controlClass(false)} mt-1`}
          />
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-[13px] text-critical">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p role="status" data-testid="saved" className="text-[13px] text-positive">
          Saved.
        </p>
      ) : null}

      <Button variant="secondary" type="submit" disabled={busy} data-testid="save-lead">
        {busy ? 'Saving…' : 'Save changes'}
      </Button>
    </form>
  );
}
