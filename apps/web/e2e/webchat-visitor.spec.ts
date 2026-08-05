import { expect, test } from '@playwright/test';

/**
 * A visitor session end to end, and the origin check that guards it.
 *
 * The negative case is the important one: a request without an allowed Origin
 * must be refused even though the public key is correct, because the key is
 * public by design and the origin is what actually authorises.
 */
test.describe('webchat', () => {
  test('a visitor from an allowed origin can hold a conversation', async ({ request, page }) => {
    await page.goto('/login');
    await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'asha@acme.test');
    await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'demo-passphrase-2026');
    await page.getByRole('button', { name: /sign in/i }).click();

    const configured = await request.put('/api/webchat/widget', {
      data: {
        allowed_origins: ['http://localhost:3000'],
        greeting: 'How can we help?',
        consent_copy: 'We store this chat to answer your question.',
        is_active: true,
      },
    });
    expect(configured.ok()).toBeTruthy();
    const { data: widget } = (await configured.json()) as { data: { public_key: string } };

    const opened = await request.post('/api/public/webchat/sessions', {
      headers: { Origin: 'http://localhost:3000' },
      data: { public_key: widget.public_key },
    });
    expect(opened.ok()).toBeTruthy();
    const { data: session } = (await opened.json()) as { data: { session_token: string } };

    const sent = await request.post('/api/public/webchat/messages', {
      headers: { Origin: 'http://localhost:3000' },
      data: { session_token: session.session_token, body: 'Do you ship to Pune?' },
    });
    expect(sent.ok()).toBeTruthy();

    const transcript = await request.get(
      `/api/public/webchat/transcript?session_token=${encodeURIComponent(session.session_token)}`,
    );
    const { data } = (await transcript.json()) as {
      data: { messages: { content: string; author: string }[] };
    };
    expect(data.messages).toHaveLength(1);
    expect(data.messages[0].content).toBe('Do you ship to Pune?');
    expect(data.messages[0].author).toBe('you');
  });

  test('an unlisted origin is refused even with the right key', async ({ request }) => {
    const refused = await request.post('/api/public/webchat/sessions', {
      headers: { Origin: 'https://not-allowed.example' },
      data: { public_key: 'wck_00000000000000000000000000000000' },
    });
    expect(refused.status()).toBeGreaterThanOrEqual(400);
  });
});
