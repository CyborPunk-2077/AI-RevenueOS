'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

interface Option { readonly id: string; readonly name: string }

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

  if (!open) {
    return (
      <button type="button" data-testid="new-conversation" onClick={() => setOpen(true)}
        className="rounded bg-primary px-4 py-2 text-primary-foreground">
        New conversation
      </button>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded border p-4" noValidate>
      <h2 className="font-medium">New conversation</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="conv_subject" className="block text-sm font-medium">Subject</label>
          <input id="conv_subject" name="subject" className="mt-1 w-full rounded border px-3 py-2" />
        </div>
        <div>
          <label htmlFor="conv_channel" className="block text-sm font-medium">Channel</label>
          <select id="conv_channel" name="primary_channel" defaultValue="web_chat"
            className="mt-1 w-full rounded border px-3 py-2">
            {channels.map((c) => (
              <option key={c.channel} value={c.channel}>
                {c.channel}{c.ready ? '' : ' (not configured)'}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="conv_contact" className="block text-sm font-medium">Contact</label>
          <select id="conv_contact" name="contact_id" defaultValue=""
            className="mt-1 w-full rounded border px-3 py-2">
            <option value="">None</option>
            {contacts.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
          </select>
        </div>
      </div>

      {error ? (<p role="alert" data-testid="conversation-error" className="text-sm text-destructive">{error}</p>) : null}

      <div className="flex gap-2">
        <button type="submit" disabled={busy} data-testid="create-conversation"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">
          {busy ? 'Opening...' : 'Open conversation'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded border px-4 py-2">Cancel</button>
      </div>
    </form>
  );
}
