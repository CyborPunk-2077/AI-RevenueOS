import { redirect } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { WorkspaceShell } from '@/features/crm/workspace-shell';

export const dynamic = 'force-dynamic';

interface MeResponse {
  readonly email: string;
  readonly tenant_slug: string;
  readonly workspace_name: string | null;
  readonly workspace_kind: string | null;
}

export default async function AppointmentsLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<JSX.Element> {
  const me = await apiFetch<MeResponse>('/auth/me');
  if (!me.ok || !me.data) redirect('/login');

  return (
    <WorkspaceShell
      tenantSlug={me.data.tenant_slug}
      email={me.data.email}
      workspaceName={me.data.workspace_name}
      workspaceKind={me.data.workspace_kind}
      active="appointments"
    >
      {children}
    </WorkspaceShell>
  );
}
