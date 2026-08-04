'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { ChatWidget, type ChatMessage } from './chat-widget';

const API = process.env.NEXT_PUBLIC_API_URL ?? '';
const POLL_MS = 5_000;

interface Config {
  greeting: string;
  consent_copy: string;
  handoff_enabled: boolean;
}

/**
 * Session lifecycle and transport for the hosted widget.
 *
 * Polling rather than a socket, deliberately: a websocket per idle visitor is a
 * connection the API has to hold open for a page that is mostly abandoned, and
 * five seconds is well inside what a chat feels like. It also degrades to
 * nothing on a flaky mobile connection instead of thrashing reconnects.
 *
 * The session token is held in component state, never in localStorage. It is a
 * bearer credential for a stranger's browser on someone else's site; persisting
 * it would outlive the tab and survive into whatever else that browser does.
 */
export function ChatHost({ publicKey }: { publicKey: string }): JSX.Element {
  const [config, setConfig] = useState<Config | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [consent, setConsent] = useState(false);
  const [state, setState] = useState<'ready' | 'connecting' | 'ended' | 'unavailable'>(
    'connecting',
  );
  const tokenRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function open(): Promise<void> {
      const configResponse = await fetch(
        `${API}/v1/public/webchat/config?public_key=${encodeURIComponent(publicKey)}`,
        { cache: 'no-store' },
      );
      if (!configResponse.ok) {
        if (!cancelled) setState('unavailable');
        return;
      }
      const configPayload = (await configResponse.json()) as { data: Config };

      const sessionResponse = await fetch(`${API}/v1/public/webchat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ public_key: publicKey, consent_granted: false }),
      });
      if (!sessionResponse.ok) {
        if (!cancelled) setState('unavailable');
        return;
      }
      const sessionPayload = (await sessionResponse.json()) as {
        data: { session_token: string };
      };

      if (cancelled) return;
      tokenRef.current = sessionPayload.data.session_token;
      setConfig(configPayload.data);
      setState('ready');
    }

    void open();
    return () => {
      cancelled = true;
    };
  }, [publicKey]);

  const refresh = useCallback(async (): Promise<void> => {
    const token = tokenRef.current;
    if (!token) return;
    const response = await fetch(
      `${API}/v1/public/webchat/transcript?session_token=${encodeURIComponent(token)}`,
      { cache: 'no-store' },
    );
    if (response.status === 404) {
      // The session expired or was ended by the tenant. Saying so beats a widget
      // that silently swallows everything typed into it.
      setState('ended');
      return;
    }
    if (!response.ok) return;
    const payload = (await response.json()) as { data: { messages: ChatMessage[] } };
    setMessages(payload.data.messages);
  }, []);

  useEffect(() => {
    if (state !== 'ready') return undefined;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [state, refresh]);

  async function send(body: string): Promise<void> {
    const token = tokenRef.current;
    if (!token) return;

    // Optimistic, with a local id: waiting a round trip to echo your own words
    // reads as a dropped message.
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      author: 'you',
      content: body,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);

    const response = await fetch(`${API}/v1/public/webchat/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_token: token, body }),
    });

    if (!response.ok) {
      setMessages((current) => current.filter((message) => message.id !== optimistic.id));
      if (response.status === 404) setState('ended');
      return;
    }
    await refresh();
  }

  return (
    <ChatWidget
      greeting={config?.greeting ?? ''}
      consentCopy={config?.consent_copy ?? ''}
      messages={messages}
      onSend={send}
      onConsent={setConsent}
      consentGranted={consent}
      state={state}
    />
  );
}
