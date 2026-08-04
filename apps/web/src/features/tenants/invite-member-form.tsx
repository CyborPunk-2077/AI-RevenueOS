'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { mutate } from '@/lib/csrf';

const ROLES = [
  { value: 'admin', label: 'Admin - manages people and settings' },
  { value: 'manager', label: 'Manager - runs a team and its pipeline' },
  { value: 'member', label: 'Member - works their own records' },
  { value: 'viewer', label: 'Viewer - read only' },
] as const;

/**
 * Invite someone to the organisation.
 *
 * The role list is not filtered client-side by the inviter's own role: the
 * server owns that ceiling and will refuse an over-reach with a 403 naming what
 * the actor may assign. Hiding options here as well would be a nicety, not a
 * control, and it would drift from the server's matrix.
 */
export function InviteMemberForm(): JSX.Element {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<string>('member');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);

    const response = await mutate('/api/users/invitations', {
      method: 'POST',
      body: { email, role },
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      setError(payload.error?.message ?? 'That invitation could not be sent.');
      setBusy(false);
      return;
    }

    // Email delivery is externally gated, so the invitation exists but nothing
    // has been sent. Saying so is the difference between a working product and
    // one that silently drops invitations.
    setNotice(
      `Invitation created for ${email}. Email delivery is not enabled yet, so copy the link from the invitation list and send it yourself.`,
    );
    setEmail('');
    setBusy(false);
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-border p-4">
      <h2 className="text-sm font-semibold">Invite someone</h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="invite_email" className="block text-sm font-medium">
            Email
          </label>
          <input
            id="invite_email"
            type="email"
            required
            maxLength={320}
            autoComplete="off"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label htmlFor="invite_role" className="block text-sm font-medium">
            Role
          </label>
          <select
            id="invite_role"
            value={role}
            onChange={(event) => setRole(event.target.value)}
            className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
          >
            {ROLES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
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
      {notice ? (
        <p role="status" className="text-sm text-muted-foreground">
          {notice}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
      >
        {busy ? 'Creating…' : 'Send invitation'}
      </button>
    </form>
  );
}
