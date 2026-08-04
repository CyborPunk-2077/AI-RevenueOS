import { ChatHost } from '@/features/webchat/chat-host';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Chat' };

/**
 * The hosted chat page.
 *
 * Lives under `(fullscreen)` because whoever opens it is not a user of the
 * product: no navigation, no tenant switcher, nothing implying an account. The
 * public key arrives in the query string, which is fine - it is public by
 * design; the `Origin` check on the API is what actually authorises the page.
 */
export default function HostedChatPage({
  searchParams,
}: {
  searchParams: { k?: string };
}): JSX.Element {
  const publicKey = searchParams.k ?? '';

  if (!publicKey) {
    return (
      <p className="text-sm text-muted-foreground">
        This chat link is incomplete. Please use the chat button on the website you came from.
      </p>
    );
  }

  return <ChatHost publicKey={publicKey} />;
}
