'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, controlClass } from '@/features/ui/controls';

/**
 * The first screen anybody sees, and deliberately the plainest.
 *
 * No illustration, no gradient, no marketing copy. Somebody arriving here at
 * 9:40am wants two fields and a button, and a sign-in page that tries to sell
 * the product to the person already using it is a page that wastes their time.
 */
export default function LoginPage(): JSX.Element {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: string };
      setError(body.error ?? 'Sign in failed.');
      setBusy(false);
      return;
    }
    router.push('/today');
    router.refresh();
  }

  return (
    <main
      id="main-content"
      className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-6"
    >
      <div className="rounded-lg border border-border bg-surface p-7">
        <h1 className="text-2xl font-semibold tracking-[-0.01em] text-foreground">Sangam</h1>
        <p className="mt-1 text-sm text-muted-foreground">Sign in to your organisation.</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
          <div>
            <label htmlFor="email" className="block text-[13px] font-medium text-foreground">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={`${controlClass(false)} mt-1`}
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-[13px] font-medium text-foreground">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={`${controlClass(false)} mt-1`}
            />
          </div>

          {error ? (
            <p
              role="alert"
              className="rounded border border-critical/40 bg-critical-soft px-3 py-2 text-[13px] text-critical"
            >
              {error}
            </p>
          ) : null}

          <Button
            variant="primary"
            type="submit"
            disabled={busy}
            data-testid="sign-in"
            className="w-full"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      </div>
    </main>
  );
}
