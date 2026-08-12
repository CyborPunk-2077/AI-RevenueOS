import { redirect } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { WorkspaceShell } from '@/features/crm/workspace-shell';

export const dynamic = 'force-dynamic';

interface MeResponse {
  readonly email: string;
  readonly tenant_slug: string;
}

export default async function TodayLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<JSX.Element> {
  // The tenant guard is the server rejecting an unauthenticated call, not a
  // client-side check that could be skipped.
  const me = await apiFetch<MeResponse>('/auth/me');
  if (!me.ok || !me.data) redirect('/login');

  return (
    <WorkspaceShell tenantSlug={me.data.tenant_slug} email={me.data.email} active="today">
      {children}
    </WorkspaceShell>
  );
}
