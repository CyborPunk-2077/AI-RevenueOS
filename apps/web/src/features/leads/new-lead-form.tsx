'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export function NewLeadForm(): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    const response = await mutate('/api/leads', {
      method: 'POST',
      body: {
        first_name: String(form.get('first_name') ?? ''),
        last_name: String(form.get('last_name') ?? '') || null,
        email: String(form.get('email') ?? '') || null,
        source: 'manual',
      },
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(body.error?.message ?? 'Could not create the lead.');
      setBusy(false);
      return;
    }
    setBusy(false);
    setOpen(false);
    router.refresh();
  }

  if (!open) {
    return (
      <button
        type="button"
        data-testid="new-lead"
        onClick={() => setOpen(true)}
        className="rounded bg-primary px-4 py-2 text-primary-foreground"
      >
        New lead
      </button>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded border p-4" noValidate>
      <h2 className="font-medium">New lead</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="first_name" className="block text-sm font-medium">First name</label>
          <input id="first_name" name="first_name" required className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="last_name" className="block text-sm font-medium">Last name</label>
          <input id="last_name" name="last_name" className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="email" className="block text-sm font-medium">Email</label>
          <input id="email" name="email" type="email" className="mt-1 w-full rounded border px-3 py-2" />
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-destructive">{error}</p>
      ) : null}

      <div className="flex gap-2">
        <button type="submit" disabled={busy} data-testid="create-lead"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
          {busy ? 'Creating...' : 'Create lead'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded border px-4 py-2">
          Cancel
        </button>
      </div>
    </form>
  );
}
