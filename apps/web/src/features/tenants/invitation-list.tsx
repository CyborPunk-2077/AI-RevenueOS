'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { mutate } from '@/lib/csrf';

export interface InvitationRow {
  readonly id: string;
  readonly email: string;
  readonly role: string | null;
  readonly expires_at: string;
  readonly status: 'pending' | 'accepted' | 'revoked' | 'expired';
}

const STATUS_LABEL: Record<InvitationRow['status'], string> = {
  pending: 'Pending',
  accepted: 'Accepted',
  revoked: 'Revoked',
  expired: 'Expired',
};

function when(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/**
 * Outstanding invitations.
 *
 * Status is conveyed by text, not colour alone: "Expired" in red and "Pending"
 * in amber read identically to a person who cannot distinguish them, and the
 * accessibility gate fails a story that leans on the badge colour.
 */
export function InvitationList({ invitations }: { invitations: InvitationRow[] }): JSX.Element {
  const router = useRouter();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function revoke(id: string): Promise<void> {
    setBusyId(id);
    setError(null);
    const response = await mutate(`/api/users/invitations/${id}`, { method: 'DELETE' });
    if (!response.ok) {
      setError('That invitation could not be revoked.');
      setBusyId(null);
      return;
    }
    setBusyId(null);
    router.refresh();
  }

  if (invitations.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-6 text-center">
        <p className="text-sm text-muted-foreground">
          No outstanding invitations. Everyone invited has either joined or been revoked.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <table className="w-full text-left text-sm">
        <caption className="sr-only">Outstanding invitations</caption>
        <thead>
          <tr className="border-b border-border text-xs uppercase text-muted-foreground">
            <th scope="col" className="py-2">
              Email
            </th>
            <th scope="col" className="py-2">
              Role
            </th>
            <th scope="col" className="py-2">
              Status
            </th>
            <th scope="col" className="py-2">
              Expires
            </th>
            <th scope="col" className="py-2">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {invitations.map((invitation) => (
            <tr key={invitation.id} className="border-b border-border/60">
              <td className="py-2">{invitation.email}</td>
              <td className="py-2 capitalize">{invitation.role ?? '—'}</td>
              <td className="py-2">{STATUS_LABEL[invitation.status]}</td>
              <td className="py-2">{when(invitation.expires_at)}</td>
              <td className="py-2 text-right">
                {invitation.status === 'pending' ? (
                  <button
                    type="button"
                    onClick={() => void revoke(invitation.id)}
                    disabled={busyId === invitation.id}
                    className="rounded border border-border px-3 py-1 text-xs disabled:opacity-60"
                  >
                    {busyId === invitation.id ? 'Revoking…' : 'Revoke'}
                    <span className="sr-only"> the invitation for {invitation.email}</span>
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
