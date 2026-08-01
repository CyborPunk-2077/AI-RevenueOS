'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

interface Option {
  readonly id: string;
  readonly name: string;
}

export function NewDealForm({
  accounts,
  contacts,
}: {
  accounts: Option[];
  contacts: Option[];
}): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    // The form takes rupees; the API stores paise. Converting here keeps the
    // integer-money rule intact without asking the user to think in paise.
    const rupees = Number(form.get('amount') ?? 0);
    const response = await mutate('/api/deals', {
      method: 'POST',
      body: {
        title: String(form.get('title') ?? ''),
        amount_minor: Number.isFinite(rupees) ? Math.round(rupees * 100) : 0,
        account_id: String(form.get('account_id') ?? '') || null,
        contact_id: String(form.get('contact_id') ?? '') || null,
      },
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not create the deal.');
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
        data-testid="new-deal"
        onClick={() => setOpen(true)}
        className="rounded bg-primary px-4 py-2 text-primary-foreground"
      >
        New deal
      </button>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded border p-4" noValidate>
      <h2 className="font-medium">New deal</h2>
      <div className="grid gap-4 sm:grid-cols-4">
        <div>
          <label htmlFor="deal_title" className="block text-sm font-medium">Title</label>
          <input id="deal_title" name="title" required className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="deal_amount" className="block text-sm font-medium">Amount (₹)</label>
          <input id="deal_amount" name="amount" type="number" min="0" step="1"
            defaultValue="0" className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="deal_account" className="block text-sm font-medium">Account</label>
          <select id="deal_account" name="account_id" defaultValue=""
            className="mt-1 w-full rounded border px-3 py-2">
            <option value="">None</option>
            {accounts.map((a) => (<option key={a.id} value={a.id}>{a.name}</option>))}
          </select>
        </div>
        <div>
          <label htmlFor="deal_contact" className="block text-sm font-medium">Contact</label>
          <select id="deal_contact" name="contact_id" defaultValue=""
            className="mt-1 w-full rounded border px-3 py-2">
            <option value="">None</option>
            {contacts.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
        </div>
      </div>

      {error ? (<p role="alert" data-testid="deal-error" className="text-sm text-destructive">{error}</p>) : null}

      <div className="flex gap-2">
        <button type="submit" disabled={busy} data-testid="create-deal"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
          {busy ? 'Creating...' : 'Create deal'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded border px-4 py-2">Cancel</button>
      </div>
    </form>
  );
}
