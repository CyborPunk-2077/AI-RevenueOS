'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { mutate } from '@/lib/csrf';
import { channelLabel } from '@/features/ui/channel-icon';
import { cn } from '@/features/ui/cn';
import { Button, controlClass } from '@/features/ui/controls';
import { dayKey, formatDayHeading, formatDateTime, formatTime } from '@/lib/dates';

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
 * A customer conversation, in the grammar people already read conversations in.
 *
 * **This replaces a single left-aligned column of bordered records.** That column
 * was defensible - it was chosen to avoid looking like a consumer chat app - and
 * in use it was wrong. Every message was a full-width rectangle with a header
 * line, so a fourteen-message thread read as fourteen database rows and the one
 * question an operator actually asks a transcript, *who said this*, had to be
 * answered by reading rather than by looking.
 *
 * So: **inbound left, outbound right**, which is the one layout convention every
 * user of this product already knows. What is deliberately *not* borrowed is the
 * decoration - no tails, no provider green, no wallpaper, no ticks. The bubbles
 * are the same two surfaces the rest of the application uses, with the same 1px
 * borders and the same 6px radius. Direction is carried by position and surface;
 * everything else stays Sangam.
 *
 * Three things hold the density down:
 *
 * - **Runs group.** Consecutive messages from the same side are 2px apart with
 *   one attribution and one timestamp for the run, rather than each carrying its
 *   own header. Six rapid-fire customer messages become one visual paragraph.
 * - **Days separate.** A hairline with the date, so a thread spanning a week is
 *   legible without reading timestamps.
 * - **Status is quiet.** `sent` / `delivered` / `read` sit under the last message
 *   of an outbound run, muted and small.
 *
 * **Provider truth is never invented.** Those words are exactly what Meta
 * reported and nothing else; there is no tick system, because a tick implies a
 * state machine richer than the one we actually get. `queued` says plainly that
 * it has not been sent. `failed` is the one state that earns critical colour and
 * a full-width line, because it means the customer never received the message,
 * and an operator who misses that will follow up on a conversation that never
 * happened.
 */

/** What the provider has told us, in the words it told us. */
const DELIVERY_WORDS: Record<string, string> = {
  queued: 'queued — not sent yet',
  sent: 'sent',
  delivered: 'delivered',
  read: 'read',
  failed: 'failed',
};

interface Run {
  readonly outbound: boolean;
  readonly messages: ThreadMessage[];
}

interface DayGroup {
  readonly key: string;
  readonly iso: string;
  readonly runs: Run[];
}

/**
 * Messages into days, and each day into runs of one direction.
 *
 * Done here rather than in the markup because the alternative - comparing
 * against the previous element mid-render - is where off-by-one grouping bugs
 * live, and because a run needs to know its own last message to decide where the
 * timestamp and the delivery state go.
 */
function group(messages: ThreadMessage[]): DayGroup[] {
  const days: DayGroup[] = [];
  for (const message of messages) {
    const key = dayKey(message.created_at);
    let day = days[days.length - 1];
    if (!day || day.key !== key) {
      day = { key, iso: message.created_at ?? '', runs: [] };
      days.push(day);
    }
    const outbound = message.direction === 'outbound';
    const run = day.runs[day.runs.length - 1];
    // A failed message always starts its own run. Folding it into a group would
    // hide the one state that has to be seen, behind a shared status line that
    // describes a different message.
    const failed = message.status === 'failed';
    const previousFailed = run?.messages[run.messages.length - 1]?.status === 'failed';
    if (run && run.outbound === outbound && !failed && !previousFailed) {
      run.messages.push(message);
    } else {
      day.runs.push({ outbound, messages: [message] });
    }
  }
  return days;
}

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
  const foot = useRef<HTMLDivElement | null>(null);

  const ready = channels.find((c) => c.channel === channel)?.ready ?? false;
  const days = group(messages);

  /*
   * Open at the newest message, the way every transcript in the world opens.
   *
   * `block: 'nearest'` on a scroll container that is itself inside the page
   * scroller: without it the browser also scrolls the *page* to bring the
   * transcript into view, which throws the utility bar and the customer header
   * off the top of the screen on arrival.
   */
  useEffect(() => {
    foot.current?.scrollIntoView({ block: 'nearest' });
  }, [messages.length]);

  async function post(path: string, content: string): Promise<boolean> {
    setBusy(true);
    setError(null);
    setNotice(null);
    const response = await mutate(path, { method: 'POST', body: { content } });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
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
    <div className="flex min-h-0 flex-1 flex-col">
      <h2 className="sr-only">Messages</h2>

      {/*
        The transcript sits on the canvas, not on the panel surface. Inbound
        bubbles are `--surface` and outbound `--accent-soft`, and neither step is
        a step unless the paper behind them is a third value.
      */}
      <div className="min-h-[22rem] flex-1 overflow-y-auto bg-canvas px-5 py-5">
        {messages.length === 0 ? (
          <p data-testid="thread-empty" className="py-8 text-center text-sm text-muted-foreground">
            Nothing in this thread yet.
          </p>
        ) : (
          /*
            Capped and centred, which a transcript needs and a table does not.

            The pane itself takes whatever width the monitor gives it, and at
            1920 that put a customer's message against the left edge and the
            reply nearly 1200px away on the right - two columns of unrelated
            text rather than one exchange. Alternation only reads as alternation
            when both sides are inside one field of view.
          */
          <ol className="mx-auto max-w-[58rem] space-y-5" data-testid="thread-messages">
            {days.map((day) => (
              <li key={day.key}>
                {/* A hairline through the date, rather than a floating chip. */}
                <p className="flex items-center gap-3 pb-4 text-xs font-medium text-muted-foreground">
                  <span aria-hidden="true" className="h-px flex-1 bg-border" />
                  <span>{formatDayHeading(day.iso)}</span>
                  <span aria-hidden="true" className="h-px flex-1 bg-border" />
                </p>

                <ol className="space-y-3">
                  {day.runs.map((run) => {
                    const last = run.messages[run.messages.length - 1];
                    const failed = last.status === 'failed';
                    const who = run.outbound
                      ? (last.sender_name ?? 'Sangam')
                      : (last.sender_name ?? 'Customer');
                    return (
                      <li
                        key={run.messages[0].id}
                        className={cn(
                          'flex flex-col gap-0.5',
                          run.outbound ? 'items-end' : 'items-start',
                        )}
                      >
                        {/*
                          Said in words, above the run. Which side of the screen
                          something is on is not information a screen reader can
                          use, and `sr-only` here would mean the sighted reader
                          loses the sender's name on a shared inbox.
                        */}
                        <p className="px-1 text-xs text-muted-foreground">
                          {who} · {channelLabel(last.channel)}
                        </p>

                        {run.messages.map((message) => (
                          <div
                            key={message.id}
                            data-direction={run.outbound ? 'outbound' : 'inbound'}
                            data-testid={`message-${message.id}`}
                            className={cn(
                              'max-w-[min(34rem,78%)] rounded-lg border px-3.5 py-2 text-sm leading-[21px]',
                              run.outbound
                                ? 'border-accent-soft bg-accent-soft text-foreground'
                                : 'border-border bg-surface text-foreground',
                              // The one state that is allowed to shout.
                              message.status === 'failed' && 'border-critical/45 bg-critical-soft',
                            )}
                          >
                            <p className="whitespace-pre-wrap">
                              {message.redacted ? (
                                <em className="text-muted-foreground">Message redacted</em>
                              ) : (
                                message.content
                              )}
                            </p>
                          </div>
                        ))}

                        {/*
                          One timestamp and one delivery state for the run, under
                          its last message. Per-message stamps on a burst of four
                          replies is four lines of chrome describing ninety
                          seconds.
                        */}
                        <p
                          className={cn(
                            'flex flex-wrap items-baseline gap-x-2 px-1 text-xs',
                            run.outbound ? 'justify-end' : 'justify-start',
                          )}
                          data-testid={`status-${last.id}`}
                        >
                          <span
                            className="tabular text-muted-foreground"
                            title={formatDateTime(last.created_at)}
                          >
                            {formatTime(last.created_at)}
                          </span>
                          {run.outbound ? (
                            failed ? (
                              <span className="font-medium text-critical">
                                Failed — {last.failure_reason ?? 'the provider rejected it'}. The
                                customer did not receive this.
                              </span>
                            ) : (
                              <span className="text-muted-foreground">
                                · {DELIVERY_WORDS[last.status] ?? last.status}
                                {last.failure_reason ? ` · ${last.failure_reason}` : ''}
                              </span>
                            )
                          ) : null}
                        </p>
                      </li>
                    );
                  })}
                </ol>
              </li>
            ))}
          </ol>
        )}
        <div ref={foot} aria-hidden="true" />
      </div>

      {/*
        The composer, anchored to the bottom of the conversation column.

        `sticky` rather than `fixed`: it belongs to this pane, and a fixed
        composer would sit over the conversation list on the left as well.
      */}
      <div className="sticky bottom-0 shrink-0 border-t border-border bg-surface px-5 py-4">
        <div className="mx-auto max-w-[58rem] space-y-3">
          {!ready ? (
            <p
              data-testid="channel-gated"
              className="max-w-reading text-[13px] text-muted-foreground"
            >
              <strong className="text-foreground">{channelLabel(channel)}</strong> has no provider
              credential configured. Replies are recorded and held as <code>queued</code>; nothing
              is delivered until the channel is activated.
            </p>
          ) : null}

          <form onSubmit={onReply} className="space-y-2" noValidate>
            <label htmlFor="reply" className="sr-only">
              Reply
            </label>
            <textarea
              id="reply"
              name="reply"
              rows={2}
              required
              placeholder={ready ? 'Write a reply…' : 'Write a reply — it will be queued…'}
              className={cn(controlClass(false), 'min-h-[4.5rem] resize-y')}
            />
            <div className="flex items-center justify-end">
              <Button variant="primary" type="submit" disabled={busy} data-testid="send-reply">
                {ready ? 'Send' : 'Queue reply'}
              </Button>
            </div>
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
                Development only, and shown because{' '}
                <strong className="text-foreground">{channelLabel(channel)}</strong> has no provider
                connected. Real traffic lands on this same path after webhook signature
                verification.
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
            <p
              role="status"
              data-testid="delivery-note"
              className="text-[13px] text-muted-foreground"
            >
              {notice}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
