'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { channelLabel } from '@/features/ui/channel-icon';
import { cn } from '@/features/ui/cn';
import { Button, controlClass } from '@/features/ui/controls';
import { LabelChip } from '@/features/ui/status';
import { formatDateTime } from '@/lib/dates';

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
 * A conversation transcript with a reply box.
 *
 * **Readability first, and not a chat app.** One column, capped at a comfortable
 * measure, left-aligned. Inbound and outbound are told apart by a surface step, a
 * 2px accent rule on our own messages, and a stated sender - not by coloured
 * balloons with tails on alternating sides, which is a consumer messaging idiom
 * and reads as a toy in an operations screen.
 *
 * **Provider truth is visually quiet and never invented.** `queued`, `sent`,
 * `delivered` and `read` are small muted words under the message, exactly as the
 * provider reported them. There is no tick system, because a tick implies a
 * state machine richer than the one Meta actually gives us. `failed` is the one
 * that earns critical treatment and a chip: it means the customer never received
 * it, and that is not a detail.
 *
 * The reply box never claims a message was sent. The API answers `queued`, and
 * when a channel has no provider credential the UI says so in plain words - an
 * operator believing a customer received something that never left the building
 * is the failure mode this whole gating design exists to prevent.
 */

/** What the provider has told us, in the words it told us. */
const DELIVERY_WORDS: Record<string, string> = {
  queued: 'queued — not sent yet',
  sent: 'sent',
  delivered: 'delivered',
  read: 'read',
  failed: 'failed',
};

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
    <div className="flex flex-col">
      <h2 className="sr-only">Messages</h2>

      {/*
        The transcript sits on the canvas, not on the panel surface. Inbound
        messages are `--surface` and outbound `--surface-sunken`, and that step is
        only a step if the paper behind them is a third value - on a surface
        background the inbound messages would simply disappear.
      */}
      <div className="bg-canvas px-5 py-4">
        {messages.length === 0 ? (
          <p data-testid="thread-empty" className="py-8 text-center text-sm text-muted-foreground">
            Nothing in this thread yet.
          </p>
        ) : (
          <ol className="max-w-reading space-y-3" data-testid="thread-messages">
            {messages.map((message) => {
              const outbound = message.direction === 'outbound';
              const failed = message.status === 'failed';
              return (
                <li
                  key={message.id}
                  className={cn(
                    'rounded border px-3.5 py-2.5',
                    outbound
                      ? 'border-l-2 border-border border-l-accent bg-surface-sunken'
                      : 'border-border bg-surface',
                  )}
                >
                  <p className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                    {/* Said in words. Which side of the screen something is on is
                        not information a screen reader can use. */}
                    <span>
                      {outbound
                        ? `${message.sender_name ?? 'Us'} · ${channelLabel(message.channel)}`
                        : `Customer · ${channelLabel(message.channel)}`}
                    </span>
                    <span className="tabular">
                      {message.created_at ? formatDateTime(message.created_at) : ''}
                    </span>
                  </p>

                  <p className="mt-1 whitespace-pre-wrap text-sm leading-[21px] text-foreground">
                    {message.redacted ? (
                      <em className="text-muted-foreground">Message redacted</em>
                    ) : (
                      message.content
                    )}
                  </p>

                  {outbound ? (
                    <p className="mt-1.5 text-xs" data-testid={`status-${message.id}`}>
                      {failed ? (
                        <>
                          <LabelChip tone="critical">failed</LabelChip>
                          <span className="ml-2 text-muted-foreground">
                            {message.failure_reason ?? 'the provider rejected it'} &mdash; the
                            customer did not receive this.
                          </span>
                        </>
                      ) : (
                        <span className="text-muted-foreground">
                          {DELIVERY_WORDS[message.status] ?? message.status}
                          {message.failure_reason ? ` · ${message.failure_reason}` : ''}
                        </span>
                      )}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </div>

      <div className="space-y-3 border-t border-border px-5 py-4">
        {!ready ? (
          <p data-testid="channel-gated" className="max-w-reading text-[13px] text-muted-foreground">
            <strong className="text-foreground">{channelLabel(channel)}</strong> has no provider
            credential configured. Replies are recorded and held as <code>queued</code>; nothing is
            delivered until the channel is activated.
          </p>
        ) : null}

        <form onSubmit={onReply} className="max-w-reading space-y-2" noValidate>
          <label htmlFor="reply" className="block text-[13px] font-medium text-foreground">
            Reply
          </label>
          <textarea
            id="reply"
            name="reply"
            rows={3}
            required
            className={controlClass(false)}
          />
          <Button variant="primary" type="submit" disabled={busy} data-testid="send-reply">
            {ready ? 'Send' : 'Queue reply'}
          </Button>
        </form>

        {/* Manufacturing a customer message by hand.

            This existed so the thread could be exercised before any provider was
            connected. Once one is, it becomes a way for an ordinary employee to
            invent a message a customer never sent - on the same screen, in the
            same list, indistinguishable afterwards from the real thing. Every
            number this product reports is built from those records.

            So it disappears the moment the channel can genuinely receive. The
            endpoint stays: the browser suites still drive channels that have no
            provider, and that is exactly the case this control still serves. */}
        {!ready ? (
          <form
            onSubmit={onSimulateInbound}
            className="max-w-reading space-y-2 border-t border-dashed border-border pt-3"
            noValidate
          >
            <label htmlFor="inbound" className="block text-[13px] font-medium text-foreground">
              Record an inbound message
            </label>
            <p className="text-[13px] text-muted-foreground">
              Development only, and shown because <strong className="text-foreground">{channelLabel(channel)}</strong>{' '}
              has no provider connected. Real traffic lands on this same path after webhook
              signature verification, and this control disappears once the channel is live.
            </p>
            <textarea
              id="inbound"
              name="inbound"
              rows={2}
              required
              className={controlClass(false)}
            />
            <Button variant="ghost" type="submit" disabled={busy} data-testid="record-inbound">
              Record inbound
            </Button>
          </form>
        ) : null}

        {error ? (
          <p role="alert" data-testid="thread-error" className="text-[13px] text-critical">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" data-testid="delivery-note" className="text-[13px] text-muted-foreground">
            {notice}
          </p>
        ) : null}
      </div>
    </div>
  );
}
