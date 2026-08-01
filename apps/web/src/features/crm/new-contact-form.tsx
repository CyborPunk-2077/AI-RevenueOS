'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export interface AccountOption {
  readonly id: string;
  readonly name: string;
}

/**
 * Create a contact, optionally against an account.
 *
 * The account list is passed in from the server component rather than fetched
 * here: it is already scoped to the caller's tenant, and re-fetching in the
 * browser would be a second round trip for data the page already has.
 */
export function NewContactForm({ accounts }: { accounts: AccountOption[] }): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    const accountId = String(form.get('account_id') ?? '');
    const response = await mutate('/api/contacts', {
      method: 'POST',
      body: {
        first_name: String(form.get('first_name') ?? ''),
        last_name: String(form.get('last_name') ?? '') || null,
        email: String(form.get('email') ?? '') || null,
        phone: String(form.get('phone') ?? '') || null,
        title: String(form.get('title') ?? '') || null,
        account_id: accountId || null,
        source: 'manual',
      },
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(body.error?.message ?? 'Could not create the contact.');
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
        data-testid="new-contact"
        onClick={() => setOpen(true)}
        className="rounded bg-primary px-4 py-2 text-primary-foreground"
      >
        New contact
      </button>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded border p-4" noValidate>
      <h2 className="font-medium">New contact</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="first_name" className="block text-sm font-medium">
            First name
          </label>
          <input
            id="first_name"
            name="first_name"
            required
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <div>
          <label htmlFor="last_name" className="block text-sm font-medium">
            Last name
          </label>
          <input id="last_name" name="last_name" className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="title" className="block text-sm font-medium">
            Job title
          </label>
          <input id="title" name="title" className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="email" className="block text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <div>
          <label htmlFor="phone" className="block text-sm font-medium">
            Phone
          </label>
          <input id="phone" name="phone" className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="account_id" className="block text-sm font-medium">
            Account
          </label>
          <select
            id="account_id"
            name="account_id"
            defaultValue=""
            className="mt-1 w-full rounded border px-3 py-2"
          >
            <option value="">No account</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">An email address or a phone number is required.</p>

      {error ? (
        <p role="alert" data-testid="contact-error" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          data-testid="create-contact"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
        >
          {busy ? 'Creating...' : 'Create contact'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded border px-4 py-2">
          Cancel
        </button>
      </div>
    </form>
  );
}
