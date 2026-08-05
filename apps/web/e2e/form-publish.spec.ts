import { expect, test } from '@playwright/test';

/**
 * Publishing is a snapshot, so the test that matters is that editing the draft
 * afterwards does not change what the public endpoint serves.
 */
test('a published form serves its snapshot, not the draft', async ({ page, request }) => {
  await page.goto('/login');
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'asha@acme.test');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'demo-passphrase-2026');
  await page.getByRole('button', { name: /sign in/i }).click();

  const created = await request.post('/api/forms', {
    data: {
      name: `E2E form ${Date.now()}`,
      schema: {
        fields: [
          { name: 'first_name', type: 'text', required: true },
          { name: 'email', type: 'email', required: true },
        ],
      },
      allowed_origins: ['http://localhost:3000'],
    },
  });
  expect(created.ok()).toBeTruthy();
  const { data: form } = (await created.json()) as { data: { id: string } };

  const published = await request.post(`/api/forms/${form.id}/publish`);
  expect(published.ok()).toBeTruthy();

  // The draft moves on; the live snapshot must not.
  await request.patch(`/api/forms/${form.id}`, {
    data: {
      schema: {
        fields: [
          { name: 'first_name', type: 'text', required: true },
          { name: 'email', type: 'email', required: true },
          { name: 'budget', type: 'select', options: ['<5L', '5-20L'] },
        ],
      },
    },
  });

  const live = await request.get(`/api/public/forms/${form.id}/config`);
  expect(live.ok()).toBeTruthy();
  const { data: config } = (await live.json()) as {
    data: { schema: { fields: { name: string }[] } };
  };
  expect(config.schema.fields.map((field) => field.name)).toEqual(['first_name', 'email']);
});
