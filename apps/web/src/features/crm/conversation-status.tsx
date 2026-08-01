'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export function ConversationStatus({
  conversationId,
  status,
  version,
}: {
  conversationId: string;
  status: string;
  version: number;
}): JSX.Element {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change(next: string): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/conversations/${conversationId}`, {
      method: 'PATCH',
      ifMatch: version,
      body: { status: next },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not update the conversation.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  return (
    <div className="flex items-center gap-2">
      <label htmlFor="conv_status" className="text-sm text-muted-foreground">Status</label>
      <select id="conv_status" data-testid="conversation-status" value={status} disabled={busy}
        onChange={(e) => void change(e.target.value)}
        className="rounded border px-2 py-1 text-sm">
        <option value="active">Active</option>
        <option value="resolved">Resolved</option>
        <option value="archived">Archived</option>
        <option value="spam">Spam</option>
      </select>
      {error ? (<span role="alert" className="text-xs text-destructive">{error}</span>) : null}
    </div>
  );
}
