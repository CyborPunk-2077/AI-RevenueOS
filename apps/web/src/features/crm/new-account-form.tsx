'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export function NewAccountForm(): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    const response = await mutate('/api/accounts', {
      method: 'POST',
      body: {
        name: String(form.get('name') ?? ''),
        industry: String(form.get('industry') ?? '') || null,
        website: String(form.get('website') ?? '') || null,
      },
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      // 409 is the common one: account names are unique within a tenant.
      setError(body.error?.message ?? 'Could not create the account.');
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
        data-testid="new-account"
        onClick={() => setOpen(true)}
        className="rounded bg-primary px-4 py-2 text-primary-foreground"
      >
        New account
      </button>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded border p-4" noValidate>
      <h2 className="font-medium">New account</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="account_name" className="block text-sm font-medium">
            Name
          </label>
          <input
            id="account_name"
            name="name"
            required
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <div>
          <label htmlFor="account_industry" className="block text-sm font-medium">
            Industry
          </label>
          <input
            id="account_industry"
            name="industry"
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <div>
          <label htmlFor="account_website" className="block text-sm font-medium">
            Website
          </label>
          <input
            id="account_website"
            name="website"
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
      </div>

      {error ? (
        <p role="alert" data-testid="account-error" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          data-testid="create-account"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
        >
          {busy ? 'Creating...' : 'Create account'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded border px-4 py-2">
          Cancel
        </button>
      </div>
    </form>
  );
}
