'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export interface ThreadMessage {
  readonly id: string;
  readonly direction: string;
  readonly channel: string;
  readonly sender_name: string | null;
  readonly content: string | null;
  readonly status: string;
  readonly failure_reason: string | null;
  readonly redacted: boolean;
  readonly created_at: string | null;
}

export interface ChannelReadiness {
  readonly channel: string;
  readonly ready: boolean;
}

/**
 * A conversation thread with a reply box.
 *
 * The reply box never claims a message was sent. The API answers `queued`, and
 * when the channel has no provider credential the UI says so in plain words --
 * an operator believing a customer received something that never left the
 * building is the failure mode this whole gating design exists to prevent.
 */
export function ConversationThread({
  conversationId,
  channel,
  messages,
  channels,
}: {
  conversationId: string;
  channel: string;
  messages: ThreadMessage[];
  channels: ChannelReadiness[];
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const ready = channels.find((c) => c.channel === channel)?.ready ?? false;

  async function post(path: string, content: string): Promise<boolean> {
    setBusy(true);
    setError(null);
    setNotice(null);
    const response = await mutate(path, { method: 'POST', body: { content } });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not save the message.');
      setBusy(false);
      return false;
    }
    const body = (await response.json().catch(() => ({}))) as {
      data?: { delivery_note?: string };
    };
    if (body.data?.delivery_note) setNotice(body.data.delivery_note);
    setBusy(false);
    router.refresh();
    return true;
  }

  async function onReply(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    const content = String(new FormData(form).get('reply') ?? '');
    if (await post(`/api/conversations/${conversationId}/messages`, content)) form.reset();
  }

  async function onSimulateInbound(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    const content = String(new FormData(form).get('inbound') ?? '');
    if (await post(`/api/conversations/${conversationId}/inbound`, content)) form.reset();
  }

  return (
    <section aria-labelledby="thread-heading" className="space-y-4">
      <h2 id="thread-heading" className="font-medium">Messages</h2>

      {messages.length === 0 ? (
        <p data-testid="thread-empty" className="rounded border border-dashed p-6 text-sm text-muted-foreground">
          Nothing in this thread yet.
        </p>
      ) : (
        <ol className="space-y-3" data-testid="thread-messages">
          {messages.map((message) => (
            <li key={message.id}
              className={`rounded border p-3 text-sm ${message.direction === 'outbound' ? 'ml-8 bg-muted' : 'mr-8'}`}>
              <div className="flex items-baseline justify-between gap-4 text-xs text-muted-foreground">
                <span>
                  {message.direction === 'outbound' ? (message.sender_name ?? 'Agent') : 'Customer'}
                  {' · '}{message.channel}
                </span>
                <span>{message.created_at ? new Date(message.created_at).toLocaleString() : ''}</span>
              </div>
              <p className="mt-1 whitespace-pre-wrap">
                {message.redacted ? <em className="text-muted-foreground">Message redacted</em> : message.content}
              </p>
              {message.direction === 'outbound' ? (
                <p className="mt-1 text-xs" data-testid={`status-${message.id}`}>
                  <span className="rounded bg-background px-2 py-0.5 uppercase">{message.status}</span>
                  {message.failure_reason ? (
                    <span className="ml-2 text-muted-foreground">{message.failure_reason}</span>
                  ) : null}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}

      {!ready ? (
        <p data-testid="channel-gated" className="rounded border border-dashed p-3 text-sm text-muted-foreground">
          <strong>{channel}</strong> has no provider credential configured. Replies are recorded and
          held as <code>queued</code>; nothing is delivered until the channel is activated.
        </p>
      ) : null}

      <form onSubmit={onReply} className="space-y-2 rounded border p-4" noValidate>
        <label htmlFor="reply" className="block text-sm font-medium">Reply</label>
        <textarea id="reply" name="reply" rows={3} required className="w-full rounded border px-3 py-2" />
        <button type="submit" disabled={busy} data-testid="send-reply"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
          {ready ? 'Send' : 'Queue reply'}
        </button>
      </form>

      <form onSubmit={onSimulateInbound} className="space-y-2 rounded border border-dashed p-4" noValidate>
        <label htmlFor="inbound" className="block text-sm font-medium">
          Record an inbound message
        </label>
        <p className="text-xs text-muted-foreground">
          Inbound needs no provider credential — the message already arrived. Real traffic lands on
          this same path after webhook signature verification.
        </p>
        <textarea id="inbound" name="inbound" rows={2} required className="w-full rounded border px-3 py-2" />
        <button type="submit" disabled={busy} data-testid="record-inbound"
          className="rounded border px-4 py-2 disabled:opacity-50">
          Record inbound
        </button>
      </form>

      {error ? (<p role="alert" data-testid="thread-error" className="text-sm text-destructive">{error}</p>) : null}
      {notice ? (<p role="status" data-testid="delivery-note" className="text-sm text-muted-foreground">{notice}</p>) : null}
    </section>
  );
}
