'use client';

import { useRouter } from 'next/navigation';

export function SignOutButton(): JSX.Element {
  const router = useRouter();
  return (
    <button
      type="button"
      data-testid="sign-out"
      onClick={async () => {
        await fetch('/api/auth/logout', { method: 'POST' });
        router.push('/login');
        router.refresh();
      }}
      className="rounded border px-3 py-1"
    >
      Sign out
    </button>
  );
}
