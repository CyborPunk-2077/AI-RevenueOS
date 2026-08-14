'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { Drawer } from '@/features/ui/drawer';

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

  const label = 'block text-[13px] font-medium text-foreground';

  return (
    <>
      <Button variant="primary" data-testid="new-account" onClick={() => setOpen(true)}>
        New account
      </Button>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="New account"
        description="A company you deal with. Contacts and deals hang off it."
        footer={
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              type="submit"
              form="new-account-form"
              disabled={busy}
              data-testid="create-account"
            >
              {busy ? 'Creating…' : 'Create account'}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        }
      >
        <form id="new-account-form" onSubmit={onSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="account_name" className={label}>
              Name
            </label>
            <input
              id="account_name"
              name="name"
              required
              className={`${controlClass(false)} mt-1`}
            />
          </div>
          <div>
            <label htmlFor="account_industry" className={label}>
              Industry
            </label>
            <input
              id="account_industry"
              name="industry"
              className={`${controlClass(false)} mt-1`}
            />
          </div>
          <div>
            <label htmlFor="account_website" className={label}>
              Website
            </label>
            <input
              id="account_website"
              name="website"
              className={`${controlClass(false)} mt-1`}
            />
          </div>

          {error ? (
            <p role="alert" data-testid="account-error" className="text-[13px] text-critical">
              {error}
            </p>
          ) : null}
        </form>
      </Drawer>
    </>
  );
}
