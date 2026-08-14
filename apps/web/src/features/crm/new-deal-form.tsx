'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { Drawer } from '@/features/ui/drawer';

interface Option {
  readonly id: string;
  readonly name: string;
}

/**
 * A new deal, in the same right-hand drawer every other "create a record from a
 * list" action uses. One pattern across the product beats four screens each
 * pushing their list down by a different amount when a form opens.
 */
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

  const label = 'block text-[13px] font-medium text-foreground';

  return (
    <>
      <Button variant="primary" data-testid="new-deal" onClick={() => setOpen(true)}>
        New deal
      </Button>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="New deal"
        description="A named opportunity with a value, on the pipeline board."
        footer={
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              type="submit"
              form="new-deal-form"
              disabled={busy}
              data-testid="create-deal"
            >
              {busy ? 'Creating…' : 'Create deal'}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        }
      >
        <form id="new-deal-form" onSubmit={onSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="deal_title" className={label}>
              Title
            </label>
            <input
              id="deal_title"
              name="title"
              required
              className={`${controlClass(false)} mt-1`}
            />
          </div>
          <div className="max-w-[12rem]">
            <label htmlFor="deal_amount" className={label}>
              Amount (₹)
            </label>
            <input
              id="deal_amount"
              name="amount"
              type="number"
              min="0"
              step="1"
              defaultValue="0"
              className={`${controlClass(false)} mt-1`}
            />
          </div>
          <div>
            <label htmlFor="deal_account" className={label}>
              Account
            </label>
            <select
              id="deal_account"
              name="account_id"
              defaultValue=""
              className={`${controlClass(false)} mt-1`}
            >
              <option value="">None</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="deal_contact" className={label}>
              Contact
            </label>
            <select
              id="deal_contact"
              name="contact_id"
              defaultValue=""
              className={`${controlClass(false)} mt-1`}
            >
              <option value="">None</option>
              {contacts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {error ? (
            <p role="alert" data-testid="deal-error" className="text-[13px] text-critical">
              {error}
            </p>
          ) : null}
        </form>
      </Drawer>
    </>
  );
}
