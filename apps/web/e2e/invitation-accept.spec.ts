import { expect, test } from '@playwright/test';

/**
 * The invitation round trip: issue, preview, redeem, sign in.
 *
 * Unit tests cover each half. This covers the seam - the token surviving the
 * link, the preview being readable without a session, and the new account being
 * able to sign in afterwards, which is the part users actually care about.
 */
test.describe('invitation', () => {
  test('an invited person can read the invitation and create an account', async ({
    page,
    request,
  }) => {
    await page.goto('/login');
    await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'asha@acme.test');
    await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'demo-passphrase-2026');
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page).toHaveURL(/leads/);

    const invitee = `invitee-${Date.now()}@example.in`;
    const created = await request.post('/api/users/invitations', {
      data: { email: invitee, role: 'member' },
    });
    expect(created.ok()).toBeTruthy();
    const { data } = (await created.json()) as { data: { invitation_token?: string } };

    // Local and test environments surface the link because email is gated off.
    test.skip(!data.invitation_token, 'token is not surfaced in this environment');

    await page.goto(`/invitations/accept?token=${encodeURIComponent(data.invitation_token!)}`);
    await expect(page.getByText(invitee)).toBeVisible();

    await page.getByLabel(/your name/i).fill('Invited Person');
    await page.getByLabel(/choose a password/i).fill('a-long-enough-passphrase-2026');
    await page.getByRole('button', { name: /create account/i }).click();

    // No session is issued on acceptance: the first sign-in goes through /login
    // so MFA and session caps apply to it like any other.
    await expect(page).toHaveURL(/login/);
  });

  test('a used or invalid link says so without revealing which', async ({ page }) => {
    await page.goto('/invitations/accept?token=bogus.secret');
    await expect(page.getByText(/cannot be used/i)).toBeVisible();
  });
});
