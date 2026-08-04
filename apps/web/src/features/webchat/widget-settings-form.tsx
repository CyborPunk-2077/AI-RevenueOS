'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { mutate } from '@/lib/csrf';

export interface WidgetSettings {
  readonly public_key?: string;
  readonly allowed_origins: string[];
  readonly greeting: string;
  readonly consent_copy: string;
  readonly handoff_enabled: boolean;
  readonly is_active: boolean;
}

const SNIPPET = (key: string, origin: string): string =>
  `<script src="${origin}/webchat.js" data-key="${key}" async></script>`;

/**
 * Webchat is the one channel a tenant can turn on without an external provider,
 * so this form is the whole activation path: list the sites, write the greeting
 * and consent line, switch it on.
 *
 * Activation is refused server-side without at least one origin. The button is
 * disabled here too, but the server check is the one that counts - the widget
 * would otherwise be embeddable from any site that copied the public key out of
 * a page source, which is exactly what a public key invites.
 */
export function WidgetSettingsForm({ widget }: { widget: WidgetSettings | null }): JSX.Element {
  const router = useRouter();
  const [origins, setOrigins] = useState((widget?.allowed_origins ?? []).join('\n'));
  const [greeting, setGreeting] = useState(widget?.greeting ?? '');
  const [consentCopy, setConsentCopy] = useState(widget?.consent_copy ?? '');
  const [handoff, setHandoff] = useState(widget?.handoff_enabled ?? true);
  const [active, setActive] = useState(widget?.is_active ?? false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const originList = origins
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

  async function save(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);

    const response = await mutate('/api/webchat/widget', {
      method: 'PUT',
      body: {
        allowed_origins: originList,
        greeting,
        consent_copy: consentCopy,
        handoff_enabled: handoff,
        is_active: active,
      },
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string; details?: { problems?: string[] } };
      };
      setError(
        payload.error?.details?.problems?.join(' ') ??
          payload.error?.message ??
          'Those settings could not be saved.',
      );
      setBusy(false);
      return;
    }

    setNotice('Saved.');
    setBusy(false);
    router.refresh();
  }

  return (
    <form onSubmit={save} className="space-y-6">
      <div>
        <label htmlFor="origins" className="block text-sm font-medium">
          Sites allowed to show the chat
        </label>
        <p id="origins-help" className="mt-1 text-xs text-muted-foreground">
          One per line, scheme and domain only — <code>https://example.in</code>, not a full page
          URL. Subdomains are separate entries.
        </p>
        <textarea
          id="origins"
          rows={4}
          value={origins}
          aria-describedby="origins-help"
          onChange={(event) => setOrigins(event.target.value)}
          className="mt-2 w-full rounded border border-border px-3 py-2 font-mono text-sm"
        />
      </div>

      <div>
        <label htmlFor="greeting" className="block text-sm font-medium">
          Opening message
        </label>
        <input
          id="greeting"
          maxLength={500}
          value={greeting}
          onChange={(event) => setGreeting(event.target.value)}
          className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
        />
      </div>

      <div>
        <label htmlFor="consent" className="block text-sm font-medium">
          Consent line
        </label>
        <p id="consent-help" className="mt-1 text-xs text-muted-foreground">
          Shown beside a checkbox in the widget. Say what you store and why — this is the record
          you will rely on under DPDP.
        </p>
        <input
          id="consent"
          maxLength={1000}
          value={consentCopy}
          aria-describedby="consent-help"
          onChange={(event) => setConsentCopy(event.target.value)}
          className="mt-2 w-full rounded border border-border px-3 py-2 text-sm"
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Behaviour</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={handoff}
            onChange={(event) => setHandoff(event.target.checked)}
          />
          Allow visitors to ask for a person
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            disabled={originList.length === 0}
            onChange={(event) => setActive(event.target.checked)}
          />
          Live on the sites listed above
        </label>
        {originList.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Add at least one site before switching the widget on.
          </p>
        ) : null}
      </fieldset>

      {widget?.public_key ? (
        <div className="rounded border border-border bg-muted/20 p-3">
          <p className="text-sm font-medium">Embed snippet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            The key is public by design. The site list above is what restricts who may use it.
          </p>
          <pre className="mt-2 overflow-x-auto text-xs">
            <code>{SNIPPET(widget.public_key, originList[0] ?? 'https://your-site.in')}</code>
          </pre>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-sm text-muted-foreground">
          {notice}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
      >
        {busy ? 'Saving…' : 'Save settings'}
      </button>
    </form>
  );
}
