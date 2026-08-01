import { redirect } from 'next/navigation';
import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { SignOutButton } from '@/features/auth/sign-out-button';

export const dynamic = 'force-dynamic';

interface MeResponse {
  readonly email: string;
  readonly name: string;
  readonly tenant_slug: string;
}

export default async function LeadsLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<JSX.Element> {
  // The tenant guard is the server rejecting an unauthenticated call, not a
  // client-side check that could be skipped.
  const me = await apiFetch<MeResponse>('/auth/me');
  if (!me.ok || !me.data) redirect('/login');

  return (
    <div className="min-h-screen">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <Link href="/leads" className="font-semibold">
            AI RevenueOS
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-muted-foreground" data-testid="tenant-badge">
              {me.data.tenant_slug} &middot; {me.data.email}
            </span>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main id="main-content" className="mx-auto max-w-5xl px-6 py-8">
        {children}
      </main>
    </div>
  );
}
