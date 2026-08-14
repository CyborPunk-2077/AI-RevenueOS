import { notFound, redirect } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { WorkspaceShell } from '@/features/crm/workspace-shell';
import { SettingsShell } from '@/features/ui/settings-shell';

export const dynamic = 'force-dynamic';

interface MeResponse {
  readonly email: string;
  readonly tenant_slug: string;
  readonly workspace_name: string | null;
  readonly workspace_kind: string | null;
}

export default async function TestCenterLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<JSX.Element> {
  // Development only, and enforced here rather than by hiding the link. A page
  // that states which integrations are unconfigured is an internal document, not
  // something a customer should ever be able to reach by typing the URL.
  if (process.env.NODE_ENV === 'production') notFound();

  const me = await apiFetch<MeResponse>('/auth/me');
  if (!me.ok || !me.data) redirect('/login');

  return (
    <WorkspaceShell
      tenantSlug={me.data.tenant_slug}
      email={me.data.email}
      workspaceName={me.data.workspace_name}
      workspaceKind={me.data.workspace_kind}
      active="test-center"
    >
      <SettingsShell tenantSlug={me.data.tenant_slug} active="test-center">
        {children}
      </SettingsShell>
    </WorkspaceShell>
  );
}
