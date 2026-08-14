'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { Drawer } from '@/features/ui/drawer';

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

  const label = 'block text-[13px] font-medium text-foreground';

  return (
    <>
      <Button variant="primary" data-testid="new-contact" onClick={() => setOpen(true)}>
        New contact
      </Button>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="New contact"
        description="A named person at an account. An email address or a phone number is required."
        footer={
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              type="submit"
              form="new-contact-form"
              disabled={busy}
              data-testid="create-contact"
            >
              {busy ? 'Creating…' : 'Create contact'}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        }
      >
        <form id="new-contact-form" onSubmit={onSubmit} className="space-y-4" noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="first_name" className={label}>
                First name
              </label>
              <input
                id="first_name"
                name="first_name"
                required
                className={`${controlClass(false)} mt-1`}
              />
            </div>
            <div>
              <label htmlFor="last_name" className={label}>
                Last name
              </label>
              <input id="last_name" name="last_name" className={`${controlClass(false)} mt-1`} />
            </div>
          </div>

          <div>
            <label htmlFor="title" className={label}>
              Job title
            </label>
            <input id="title" name="title" className={`${controlClass(false)} mt-1`} />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="email" className={label}>
                Email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                className={`${controlClass(false)} mt-1`}
              />
            </div>
            <div>
              <label htmlFor="phone" className={label}>
                Phone
              </label>
              <input id="phone" name="phone" className={`${controlClass(false)} mt-1`} />
            </div>
          </div>

          <div>
            <label htmlFor="account_id" className={label}>
              Account
            </label>
            <select
              id="account_id"
              name="account_id"
              defaultValue=""
              className={`${controlClass(false)} mt-1`}
            >
              <option value="">No account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
            </select>
          </div>

          {error ? (
            <p role="alert" data-testid="contact-error" className="text-[13px] text-critical">
              {error}
            </p>
          ) : null}
        </form>
      </Drawer>
    </>
  );
}
