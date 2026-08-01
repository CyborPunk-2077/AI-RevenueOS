import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import {
  ACCESS_COOKIE_BASE,
  CSRF_COOKIE_BASE,
  SESSION_COOKIE_BASE,
  cookieNames,
  cookieOptionsFor,
  readAccessCookie,
  readSessionCookie,
  rotateSession,
} from '../session';

/**
 * These cover the two BFF rules that have already broken sign-in once each:
 *
 *  - the `Secure` flag and `__Host-` prefix must follow the request scheme, not
 *    NODE_ENV, or a production build served over http://localhost sets a cookie
 *    the browser silently discards (audit D5);
 *  - a rotation response missing either token must be treated as a failure, not
 *    as a half-session, because a half-session sends the browser back with a
 *    refresh token the server has already retired (audit D4).
 */

type Jar = { get(name: string): { value: string } | undefined };

function jar(entries: Record<string, string>): Jar {
  return {
    get: (name: string) => (name in entries ? { value: entries[name] as string } : undefined),
  };
}

describe('cookie naming', () => {
  it('uses the strict __Host- prefix only over https', () => {
    expect(cookieNames(true)).toEqual({
      session: `__Host-${SESSION_COOKIE_BASE}`,
      csrf: `__Host-${CSRF_COOKIE_BASE}`,
      access: `__Host-${ACCESS_COOKIE_BASE}`,
    });
  });

  it('drops the prefix over plain http, which local development uses', () => {
    // __Host- requires Secure; a prefixed cookie without it is rejected outright,
    // which is what made a local production build unable to sign in.
    expect(cookieNames(false)).toEqual({
      session: SESSION_COOKIE_BASE,
      csrf: CSRF_COOKIE_BASE,
      access: ACCESS_COOKIE_BASE,
    });
  });
});

describe('cookie options', () => {
  it('is always HttpOnly, so page JavaScript can never read a token', () => {
    expect(cookieOptionsFor(true).httpOnly).toBe(true);
    expect(cookieOptionsFor(false).httpOnly).toBe(true);
  });

  it('ties Secure to the request scheme rather than the build mode', () => {
    expect(cookieOptionsFor(true).secure).toBe(true);
    expect(cookieOptionsFor(false).secure).toBe(false);
  });

  it('uses SameSite=lax and a root path', () => {
    const options = cookieOptionsFor(true);
    expect(options.sameSite).toBe('lax');
    expect(options.path).toBe('/');
    expect(options.maxAge).toBeGreaterThan(0);
  });
});

describe('reading cookies', () => {
  it('finds the prefixed form', () => {
    expect(readSessionCookie(jar({ [`__Host-${SESSION_COOKIE_BASE}`]: 'abc' }))).toBe('abc');
    expect(readAccessCookie(jar({ [`__Host-${ACCESS_COOKIE_BASE}`]: 'xyz' }))).toBe('xyz');
  });

  it('falls back to the unprefixed form', () => {
    expect(readSessionCookie(jar({ [SESSION_COOKIE_BASE]: 'plain' }))).toBe('plain');
  });

  it('prefers the prefixed form when both are somehow present', () => {
    const both = jar({
      [`__Host-${SESSION_COOKIE_BASE}`]: 'secure-one',
      [SESSION_COOKIE_BASE]: 'plain-one',
    });
    expect(readSessionCookie(both)).toBe('secure-one');
  });

  it('returns undefined when there is no session at all', () => {
    expect(readSessionCookie(jar({}))).toBeUndefined();
    expect(readAccessCookie(jar({}))).toBeUndefined();
  });
});

describe('rotateSession', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function respond(status: number, body: unknown): void {
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as unknown as Response);
  }

  it('returns both tokens on success', async () => {
    respond(200, {
      data: { access_token: 'access-1', refresh_token: 'refresh-1', expires_in: 900 },
    });
    await expect(rotateSession('old-token')).resolves.toEqual({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      expiresIn: 900,
    });
  });

  it('returns null when the server refuses the token', async () => {
    respond(401, { error: { message: 'This session is no longer valid.' } });
    await expect(rotateSession('retired-token')).resolves.toBeNull();
  });

  it('returns null rather than a half-session when a token is missing', async () => {
    // A response carrying only an access token would leave the browser holding a
    // refresh token the server has already rotated away; the next request then
    // looks like replay and the whole family is revoked.
    respond(200, { data: { access_token: 'access-only' } });
    await expect(rotateSession('old-token')).resolves.toBeNull();
  });

  it('defaults the lifetime when the server omits it', async () => {
    respond(200, { data: { access_token: 'a', refresh_token: 'r' } });
    await expect(rotateSession('old')).resolves.toMatchObject({ expiresIn: 900 });
  });

  it('sends the token as JSON to the refresh endpoint', async () => {
    respond(200, { data: { access_token: 'a', refresh_token: 'r', expires_in: 60 } });
    await rotateSession('the-token');

    const [url, init] = vi.mocked(globalThis.fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/v1/auth/refresh');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ refresh_token: 'the-token' });
    expect(init.cache).toBe('no-store');
  });
});
