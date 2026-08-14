'use client';

import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { SettingsShell, type SettingsSection } from './settings-shell';

/**
 * The settings section list for the tenant-scoped routes.
 *
 * `/{tenant}/settings/webchat` and `/{tenant}/settings/team` share one layout, so
 * which section is current has to come from the path rather than from a prop.
 * That is the only reason this is a client component; the list itself is the
 * same one every other settings route uses.
 */
export function TenantSettingsSections({
  tenantSlug,
  children,
}: {
  tenantSlug: string;
  children: ReactNode;
}): JSX.Element {
  const pathname = usePathname() ?? '';
  const active: SettingsSection = pathname.includes('/settings/team') ? 'team' : 'webchat';

  return (
    <SettingsShell tenantSlug={tenantSlug} active={active}>
      {children}
    </SettingsShell>
  );
}
