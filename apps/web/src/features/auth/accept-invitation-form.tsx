'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export interface InvitationPreview {
  readonly email: string;
  readonly role: string | null;
  readonly organisation: string | null;
  readonly tenant_slug: string | null;
  readonly expires_at: string;
}

/**
 * Redeeming an invitation.
 *
 * The email is shown but not editable: the link was issued to one address, and
 * letting the recipient change it would turn a forwarded invitation into an
 * account for whoever received the forward.
 *
 * No session is issued on success. The account exists and the address is proven,
 * but the first sign-in goes through /login so MFA and session caps apply to it
 * exactly as they do to every later one.
 */
export function AcceptInvitationForm({
  token,
  preview,
}: {
  token: string;
  preview: InvitationPreview;
}): JSX.Element {
  const router = useRouter();
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [problems, setProblems] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setProblems([]);

    const response = await fetch('/api/invitations/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, full_name: fullName, password }),
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string; details?: { problems?: string[] } };
      };
      setProblems(payload.error?.details?.problems ?? []);
      setError(payload.error?.message ?? 'That did not work. Please try again.');
      setBusy(false);
      return;
    }

    router.push('/login?joined=1');
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">
          Join {preview.organisation ?? 'the organisation'}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          You were invited as <strong>{preview.role ?? 'a member'}</strong>.
        </p>
      </div>

      <div>
        <span className="block text-sm font-medium">Email</span>
        {/* Not an input: the link was issued to this address specifically. */}
        <p className="mt-1 rounded border border-border bg-muted/30 px-3 py-2 text-sm">
          {preview.email}
        </p>
      </div>

      <div>
        <label htmlFor="full_name" className="block text-sm font-medium">
          Your name
        </label>
        <input
          id="full_name"
          name="full_name"
          required
          maxLength={200}
          autoComplete="name"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
        />
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium">
          Choose a password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          required
          minLength={12}
          autoComplete="new-password"
          aria-describedby="password-help"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
        />
        <p id="password-help" className="mt-1 text-xs text-muted-foreground">
          At least 12 characters. Avoid your name or email address.
        </p>
      </div>

      {error ? (
        <div role="alert" className="rounded border border-destructive/40 bg-destructive/5 p-3">
          <p className="text-sm text-destructive">{error}</p>
          {problems.length > 0 ? (
            <ul className="mt-2 list-inside list-disc text-xs text-destructive">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
      >
        {busy ? 'Creating your account…' : 'Create account'}
      </button>
    </form>
  );
}
