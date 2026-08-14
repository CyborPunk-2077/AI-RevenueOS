import { redirect } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { WorkspaceShell } from '@/features/crm/workspace-shell';
import { TenantSettingsSections } from '@/features/ui/tenant-settings-sections';

export const dynamic = 'force-dynamic';

interface MeResponse {
  readonly email: string;
  readonly tenant_slug: string;
  readonly workspace_name: string | null;
  readonly workspace_kind: string | null;
}

export default async function TenantSettingsLayout({
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
      active="settings"
    >
      <TenantSettingsSections tenantSlug={me.data.tenant_slug}>
        {children}
      </TenantSettingsSections>
    </WorkspaceShell>
  );
}
