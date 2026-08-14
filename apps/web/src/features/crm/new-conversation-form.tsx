'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { channelLabel } from '@/features/ui/channel-icon';
import { Button, controlClass } from '@/features/ui/controls';
import { Drawer } from '@/features/ui/drawer';

interface Option {
  readonly id: string;
  readonly name: string;
}

/**
 * Opening a thread from this side.
 *
 * Most conversations arrive from a customer; this is for the case where somebody
 * starts one. A drawer for the same reason Add a business is one - the Inbox is
 * a queue people read, and a form permanently occupying the top of it taxes
 * every visit for the sake of an occasional action.
 *
 * The channel list states which channels cannot actually send, on the option
 * itself, so nobody chooses one expecting delivery.
 */
export function NewConversationForm({
  contacts,
  channels,
}: {
  contacts: Option[];
  channels: { readonly channel: string; readonly ready: boolean }[];
}): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const response = await mutate('/api/conversations', {
      method: 'POST',
      body: {
        primary_channel: String(form.get('primary_channel') ?? 'web_chat'),
        subject: String(form.get('subject') ?? '') || null,
        contact_id: String(form.get('contact_id') ?? '') || null,
      },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not open the conversation.');
      setBusy(false);
      return;
    }
    setBusy(false);
    setOpen(false);
    router.refresh();
  }

  const label = 'block text-[13px] font-medium text-foreground';

  return (
    <>
      <Button variant="primary" data-testid="new-conversation" onClick={() => setOpen(true)}>
        New conversation
      </Button>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Open a conversation"
        description="For a thread you are starting. Most arrive from the customer instead."
        footer={
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              type="submit"
              form="new-conversation-form"
              disabled={busy}
              data-testid="create-conversation"
            >
              {busy ? 'Opening…' : 'Open conversation'}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        }
      >
        <form id="new-conversation-form" onSubmit={onSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="conv_subject" className={label}>
              Subject
            </label>
            <input id="conv_subject" name="subject" className={`${controlClass(false)} mt-1`} />
          </div>
          <div>
            <label htmlFor="conv_channel" className={label}>
              Channel
            </label>
            <select
              id="conv_channel"
              name="primary_channel"
              defaultValue="web_chat"
              className={`${controlClass(false)} mt-1`}
            >
              {channels.map((c) => (
                <option key={c.channel} value={c.channel}>
                  {channelLabel(c.channel)}
                  {c.ready ? '' : ' — not configured'}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="conv_contact" className={label}>
              Contact
            </label>
            <select
              id="conv_contact"
              name="contact_id"
              defaultValue=""
              className={`${controlClass(false)} mt-1`}
            >
              <option value="">None</option>
              {contacts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {error ? (
            <p role="alert" data-testid="conversation-error" className="text-[13px] text-critical">
              {error}
            </p>
          ) : null}
        </form>
      </Drawer>
    </>
  );
}
