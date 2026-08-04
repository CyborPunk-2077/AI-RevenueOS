'use client';

import { useEffect, useRef, useState } from 'react';

export interface ChatMessage {
  readonly id: string;
  readonly author: 'you' | 'agent';
  readonly content: string | null;
  readonly created_at: string;
}

export interface ChatWidgetProps {
  readonly greeting: string;
  readonly consentCopy: string;
  readonly messages: ChatMessage[];
  readonly onSend: (body: string) => Promise<void> | void;
  readonly onConsent?: (granted: boolean) => void;
  readonly consentGranted?: boolean;
  readonly state?: 'ready' | 'connecting' | 'ended' | 'unavailable';
}

/**
 * The visitor-facing chat panel.
 *
 * Accessibility decisions that are load-bearing rather than decorative:
 *
 * - The transcript is a `log` with `aria-live="polite"`, so a screen reader
 *   announces replies without stealing focus from the composer mid-sentence.
 * - Sending does not move focus. A visitor typing a follow-up while a reply
 *   arrives must not lose their place.
 * - The consent line is a real checkbox with a label, not a sentence with a
 *   clickable span, because consent that cannot be operated by keyboard is not
 *   consent.
 * - "Agent" is deliberately generic: the tenant's staffing is not the visitor's
 *   business, and naming a person invites contact outside the channel.
 */
export function ChatWidget({
  greeting,
  consentCopy,
  messages,
  onSend,
  onConsent,
  consentGranted = false,
  state = 'ready',
}: ChatWidgetProps): JSX.Element {
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = transcriptRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length]);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    const body = draft.trim();
    if (!body || busy) return;
    setBusy(true);
    setDraft('');
    await onSend(body);
    setBusy(false);
  }

  if (state === 'unavailable') {
    return (
      <section
        aria-label="Chat"
        className="w-full max-w-sm rounded-lg border border-border bg-background p-4"
      >
        <p className="text-sm text-muted-foreground">
          Chat is not available right now. Please use the contact form instead.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="Chat with us"
      className="flex h-[28rem] w-full max-w-sm flex-col rounded-lg border border-border bg-background shadow-sm"
    >
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Chat with us</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {state === 'connecting' ? 'Connecting…' : 'We usually reply within a few minutes.'}
        </p>
      </header>

      <div
        ref={transcriptRef}
        role="log"
        aria-live="polite"
        aria-label="Conversation"
        className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
      >
        {greeting ? (
          <p className="max-w-[85%] rounded-lg bg-muted/40 px-3 py-2 text-sm">{greeting}</p>
        ) : null}

        {messages.map((message) => (
          <div
            key={message.id}
            className={message.author === 'you' ? 'flex justify-end' : 'flex justify-start'}
          >
            <p
              className={
                message.author === 'you'
                  ? 'max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground'
                  : 'max-w-[85%] rounded-lg bg-muted/40 px-3 py-2 text-sm'
              }
            >
              {/* Named for assistive tech: alignment and colour carry no meaning
                  to a screen reader. */}
              <span className="sr-only">{message.author === 'you' ? 'You said: ' : 'Agent said: '}</span>
              {message.content}
            </p>
          </div>
        ))}

        {state === 'ended' ? (
          <p role="status" className="text-center text-xs text-muted-foreground">
            This conversation has ended. Refresh the page to start a new one.
          </p>
        ) : null}
      </div>

      {consentCopy && onConsent ? (
        <div className="border-t border-border px-4 py-2">
          <label className="flex items-start gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={consentGranted}
              onChange={(event) => onConsent(event.target.checked)}
              className="mt-0.5"
            />
            <span>{consentCopy}</span>
          </label>
        </div>
      ) : null}

      <form onSubmit={submit} className="flex items-end gap-2 border-t border-border p-3">
        <label htmlFor="chat_message" className="sr-only">
          Your message
        </label>
        <textarea
          id="chat_message"
          rows={2}
          maxLength={2000}
          value={draft}
          disabled={state !== 'ready'}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Type your message"
          className="flex-1 resize-none rounded border border-border px-3 py-2 text-sm disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || state !== 'ready' || draft.trim().length === 0}
          className="rounded bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
        >
          Send
        </button>
      </form>
    </section>
  );
}
