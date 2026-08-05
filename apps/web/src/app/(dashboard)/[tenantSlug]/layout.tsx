import { redirect } from 'next/navigation';
import { apiFetch } from '@/lib/session';

export const dynamic = 'force-dynamic';

interface MeResponse {
  readonly email: string;
  readonly tenant_slug: string;
}

/**
 * The tenant guard for everything in this group.
 *
 * The slug in the URL is checked against the slug in the session and a mismatch
 * redirects rather than rendering. The server would refuse the data anyway - RLS
 * and the token's tenant claim see to that - but rendering another tenant's
 * chrome around an empty page looks like a leak even when nothing leaked.
 *
 * The chrome itself lives in each section's layout: a parent layout cannot see
 * which child segment is active, and hardcoding one here lights the wrong tab.
 */
export default async function TenantGuardLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { tenantSlug: string };
}): Promise<JSX.Element> {
  const me = await apiFetch<MeResponse>('/auth/me');
  if (!me.ok || !me.data) redirect('/login');
  if (me.data.tenant_slug !== params.tenantSlug) redirect(`/${me.data.tenant_slug}/settings/team`);

  return <>{children}</>;
}
