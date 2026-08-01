'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import type { AccountOption } from './new-contact-form';

interface EditableContact {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly title: string | null;
  readonly status: string;
  readonly account_id: string | null;
  readonly version: number;
}

export function EditContactForm({
  contact,
  accounts,
}: {
  contact: EditableContact;
  accounts: AccountOption[];
}): JSX.Element {
  const router = useRouter();
  const [firstName, setFirstName] = useState(contact.first_name);
  const [lastName, setLastName] = useState(contact.last_name ?? '');
  const [title, setTitle] = useState(contact.title ?? '');
  const [status, setStatus] = useState(contact.status);
  const [accountId, setAccountId] = useState(contact.account_id ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);

    const response = await mutate(`/api/contacts/${contact.id}`, {
      method: 'PATCH',
      // Optimistic concurrency: a stale edit is refused, never silently applied.
      ifMatch: contact.version,
      body: {
        first_name: firstName,
        last_name: lastName || null,
        title: title || null,
        status,
        // Empty select means "no account", which the API reads as unlink.
        account_id: accountId || null,
      },
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(
        body.error?.message ??
          (response.status === 412
            ? 'This contact changed since you opened it. Refresh and try again.'
            : 'Could not save.'),
      );
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
          <label htmlFor="edit_first_name" className="block text-sm font-medium">
            First name
          </label>
          <input
            id="edit_first_name"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            required
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <div>
          <label htmlFor="edit_last_name" className="block text-sm font-medium">
            Last name
          </label>
          <input
            id="edit_last_name"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <div>
          <label htmlFor="edit_title" className="block text-sm font-medium">
            Job title
          </label>
          <input
            id="edit_title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <div>
          <label htmlFor="edit_status" className="block text-sm font-medium">
            Status
          </label>
          <select
            id="edit_status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2"
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="archived">Archived</option>
          </select>
        </div>
        <div>
          <label htmlFor="edit_account" className="block text-sm font-medium">
            Account
          </label>
          <select
            id="edit_account"
            data-testid="contact-account"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
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

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p role="status" data-testid="saved" className="text-sm text-muted-foreground">
          Saved.
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        data-testid="save-contact"
        className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        {busy ? 'Saving...' : 'Save changes'}
      </button>
    </form>
  );
}
