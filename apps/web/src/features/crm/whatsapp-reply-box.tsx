'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';
import { LabelChip } from '@/features/ui/status';

/**
 * Sending a WhatsApp reply from Sangam, through the real Cloud API.
 *
 * This is the one place in the product that actually sends something to a
 * customer, so it is written to be pessimistic about its own success.
 *
 * The rule it exists to respect: **the provider decides whether a message was
 * sent, and the screen shows what the provider decided.** A 201 back from our
 * own API means "the attempt was recorded", not "it arrived". So the panel
 * reports the provider's own answer, shows its error text when there is one,
 * and never renders a hopeful "sent" that nobody has confirmed. Delivered and
 * read appear on the timeline later, if and only if Meta tells us.
 *
 * Deliberately plain: no templates, no bulk, no scheduling. One person writing
 * one reply to one customer who messaged first.
 */

interface ReplyResult {
  readonly sent: boolean;
  readonly status: string;
  readonly provider_message_id: string | null;
  readonly recorded_first_response: boolean;
  readonly error_code: string | null;
  readonly error_message: string | null;
}

export function WhatsAppReplyBox({
  leadId,
  phone,
}: {
  leadId: string;
  phone: string | null;
}): JSX.Element {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReplyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    // Captured before the await: React nulls `currentTarget` once a handler
    // yields, and reading it afterwards threw a TypeError that swallowed the
    // refresh elsewhere in this codebase.
    const element = event.currentTarget;
    const text = String(new FormData(element).get('reply_text') ?? '').trim();
    if (!text) return;

    setBusy(true);
    setError(null);
    setResult(null);

    const response = await mutate(`/api/leads/${leadId}/whatsapp-reply`, {
      method: 'POST',
      body: { text },
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      setError(body.error?.message ?? 'Could not send that reply.');
      setBusy(false);
      return;
    }

    const body = (await response.json()) as { data: ReplyResult };
    setResult(body.data);
    setBusy(false);
    if (body.data.sent) element.reset();
    router.refresh();
  }

  if (!phone) {
    return (
      <p className="text-[13px] text-muted-foreground" data-testid="whatsapp-reply-unavailable">
        This prospect has no phone number, so there is nothing to reply to on WhatsApp.
      </p>
    );
  }

  return (
    // No `aria-labelledby` here either: "Reply on WhatsApp" as a region name
    // collides with the textarea's own "Reply" label under a substring match.
    <section className="space-y-3">
      <SectionHeader
        title="Reply on WhatsApp"
        description={`This one really does send, through WhatsApp, to ${phone}. Everything else in Sangam only records contact you made yourself.`}
      />

      <form onSubmit={onSubmit} className="max-w-reading space-y-3" noValidate>
        <label htmlFor="reply_text" className="sr-only">
          Reply
        </label>
        <textarea
          id="reply_text"
          name="reply_text"
          rows={3}
          required
          maxLength={4096}
          placeholder="Type your reply…"
          data-testid="whatsapp-reply-text"
          className={controlClass(false)}
        />
        <Button variant="primary" type="submit" disabled={busy} data-testid="send-whatsapp-reply">
          {busy ? 'Sending…' : 'Send WhatsApp reply'}
        </Button>
      </form>

      {error ? (
        <p role="alert" data-testid="whatsapp-reply-error" className="text-[13px] text-critical">
          {error}
        </p>
      ) : null}

      {result ? (
        <div
          role="status"
          data-testid="whatsapp-reply-result"
          data-sent={result.sent ? 'yes' : 'no'}
          className={`max-w-reading rounded border p-3 text-[13px] ${
            result.sent ? 'border-border' : 'border-critical/50'
          }`}
        >
          {result.sent ? (
            <>
              <p className="font-medium text-foreground">WhatsApp accepted it.</p>
              <p className="mt-1 text-muted-foreground">
                Provider reference {result.provider_message_id ?? 'unknown'}. Accepted is not the
                same as read — delivery and read receipts appear on the timeline only when WhatsApp
                actually reports them.
              </p>
              {result.recorded_first_response ? (
                <p className="mt-1 text-muted-foreground">
                  This was the first genuine reply to this prospect, so the response time has been
                  recorded.
                </p>
              ) : null}
            </>
          ) : (
            <>
              {/* Failure is the one delivery state that earns a chip: it means
                  the customer never received it. */}
              <p>
                <LabelChip tone="critical">not sent</LabelChip>
              </p>
              <p className="mt-1.5 text-muted-foreground">
                {result.error_message ?? 'WhatsApp did not accept it.'}
                {result.error_code ? ` (${result.error_code})` : ''}
              </p>
              <p className="mt-1 text-muted-foreground">
                This prospect is still counted as waiting, because nothing reached them.
              </p>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}
