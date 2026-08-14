import { AppShell, type SectionKey } from '@/features/ui/app-shell';

/**
 * The signed-in chrome, shared by every dashboard route.
 *
 * Thirteen layouts import this and pass exactly these five props, so the shell
 * itself moved to `features/ui/app-shell.tsx` (layer 3 of the component system)
 * and this stayed as the adapter. Keeping the name and the signature meant the
 * eleven-tab strip could be replaced by the persistent sidebar in one file
 * rather than in fourteen, and the tenant guard stays in each layout - a guard
 * that lives in a shared component is easy to forget to call.
 */
export function WorkspaceShell({
  tenantSlug,
  email,
  workspaceName,
  workspaceKind,
  active,
  children,
}: {
  tenantSlug: string;
  email: string;
  workspaceName?: string | null;
  workspaceKind?: string | null;
  active: SectionKey;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <AppShell
      tenantSlug={tenantSlug}
      email={email}
      workspaceName={workspaceName}
      workspaceKind={workspaceKind}
      active={active}
    >
      {children}
    </AppShell>
  );
}
