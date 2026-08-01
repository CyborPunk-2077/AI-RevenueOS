import { cookies } from 'next/headers';

/**
 * The browser holds a session cookie and nothing else. Access tokens live only in
 * this server process; JavaScript in the page can never read one.
 *
 * The `Secure` flag and the `__Host-` prefix follow the actual request scheme
 * rather than NODE_ENV. A production build served over http://localhost -- which
 * is exactly what `npm run build && npm start` does -- would otherwise set a
 * Secure cookie that the client discards, and sign-in would silently fail.
 * Over HTTPS the strict `__Host-` form is used.
 */
export const SESSION_COOKIE_BASE = 'airev-session';
export const CSRF_COOKIE_BASE = 'airev-csrf';
export const ACCESS_COOKIE_BASE = 'airev-access';

export function cookieNames(secure: boolean): {
  session: string;
  csrf: string;
  access: string;
} {
  const prefix = secure ? '__Host-' : '';
  return {
    session: `${prefix}${SESSION_COOKIE_BASE}`,
    csrf: `${prefix}${CSRF_COOKIE_BASE}`,
    access: `${prefix}${ACCESS_COOKIE_BASE}`,
  };
}

export function cookieOptionsFor(secure: boolean) {
  return {
    httpOnly: true,
    secure,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: 60 * 60 * 24 * 7,
  };
}

type Jar = { get(name: string): { value: string } | undefined };

/** Read whichever cookie form is present, prefixed or not. */
function read(jar: Jar, base: string): string | undefined {
  return jar.get(`__Host-${base}`)?.value ?? jar.get(base)?.value;
}

export const readSessionCookie = (jar: Jar): string | undefined =>
  read(jar, SESSION_COOKIE_BASE);
export const readAccessCookie = (jar: Jar): string | undefined =>
  read(jar, ACCESS_COOKIE_BASE);

export const API_BASE = process.env.API_INTERNAL_URL ?? 'http://localhost:8000';

export interface SessionUser {
  readonly id: string;
  readonly email: string;
  readonly name: string;
  readonly tenant_id: string;
  readonly tenant_slug: string;
  readonly tenant_name: string;
  readonly roles: readonly string[];
}

/**
 * The short-lived access token, held in its own HttpOnly cookie.
 *
 * Refreshing on every render would rotate the refresh token on each request while
 * the browser still held the previous one -- the second request then looks like
 * token replay and the server correctly revokes the whole family. So the access
 * token is minted once at sign-in and refreshed only by a route handler, which is
 * the only place Next.js permits writing a cookie.
 */
export async function getAccessToken(): Promise<string | null> {
  return readAccessCookie(cookies()) ?? null;
}

export interface RefreshedSession {
  readonly accessToken: string;
  readonly refreshToken: string;
  readonly expiresIn: number;
}

/** Rotate the refresh token. Only route handlers may call this. */
export async function rotateSession(refreshToken: string): Promise<RefreshedSession | null> {
  const response = await fetch(`${API_BASE}/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: 'no-store',
  });
  if (!response.ok) return null;

  const payload = (await response.json()) as {
    data?: { access_token?: string; refresh_token?: string; expires_in?: number };
  };
  if (!payload.data?.access_token || !payload.data.refresh_token) return null;

  return {
    accessToken: payload.data.access_token,
    refreshToken: payload.data.refresh_token,
    expiresIn: payload.data.expires_in ?? 900,
  };
}

/** Server-side fetch against the API with the caller's own token. */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<{ ok: boolean; status: number; data: T | null; error?: string }> {
  const token = await getAccessToken();
  if (!token) return { ok: false, status: 401, data: null, error: 'Not signed in.' };

  const response = await fetch(`${API_BASE}/v1${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      authorization: `Bearer ${token}`,
      ...(init.body ? { 'content-type': 'application/json' } : {}),
    },
    cache: 'no-store',
  });

  const payload = (await response.json().catch(() => null)) as
    | { success: boolean; data?: T; error?: { message: string } }
    | null;

  return {
    ok: response.ok && Boolean(payload?.success),
    status: response.status,
    data: (payload?.data as T) ?? null,
    error: payload?.error?.message,
  };
}
