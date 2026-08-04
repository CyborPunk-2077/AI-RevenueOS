import { API_BASE } from '@/lib/session';
import {
  AcceptInvitationForm,
  type InvitationPreview,
} from '@/features/auth/accept-invitation-form';

export const dynamic = 'force-dynamic';

/**
 * The invitation landing page.
 *
 * The preview is fetched server-side and unauthenticated - the recipient has no
 * account yet, so there is no session to attach. An invalid, expired or already
 * used link produces one indistinguishable message: telling them apart would let
 * anyone with a link generator learn which invitations exist.
 */
export default async function AcceptInvitationPage({
  searchParams,
}: {
  searchParams: { token?: string };
}): Promise<JSX.Element> {
  const token = searchParams.token ?? '';

  if (!token) {
    return <InvalidLink />;
  }

  const response = await fetch(
    `${API_BASE}/v1/invitations/preview?token=${encodeURIComponent(token)}`,
    { cache: 'no-store' },
  );

  if (!response.ok) {
    return <InvalidLink />;
  }

  const payload = (await response.json()) as { data?: InvitationPreview };
  if (!payload.data) {
    return <InvalidLink />;
  }

  return <AcceptInvitationForm token={token} preview={payload.data} />;
}

function InvalidLink(): JSX.Element {
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">This invitation cannot be used</h1>
      <p className="text-sm text-muted-foreground">
        The link is invalid, has expired, or has already been used. Ask whoever invited you to send
        a new one.
      </p>
      <a href="/login" className="inline-block text-sm font-medium text-primary underline">
        Go to sign in
      </a>
    </div>
  );
}
