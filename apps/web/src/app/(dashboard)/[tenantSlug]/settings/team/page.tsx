import { apiFetch } from '@/lib/session';
import { InviteMemberForm } from '@/features/tenants/invite-member-form';
import { InvitationList, type InvitationRow } from '@/features/tenants/invitation-list';

export const dynamic = 'force-dynamic';

export const metadata = { title: 'Team' };

export default async function TeamSettingsPage(): Promise<JSX.Element> {
  const result = await apiFetch<{ items: InvitationRow[] }>('/users/invitations?include_settled=true');
  const invitations = result.data?.items ?? [];

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold">Team</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Invite people and manage outstanding invitations. An invitation creates no account until
          the person accepts it.
        </p>
      </section>

      <InviteMemberForm />

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Invitations</h2>
        <InvitationList invitations={invitations} />
      </section>
    </div>
  );
}
