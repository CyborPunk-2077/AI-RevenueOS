/**
 * The BFF proxy. It is the only component that holds tokens: the browser sees a
 * host-only, Secure, HttpOnly, SameSite=Lax refresh-session cookie and nothing else.
 */
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API_BASE = process.env.API_INTERNAL_URL ?? 'http://localhost:8000';
const SESSION_COOKIE = '__Host-airev-session';
const CSRF_COOKIE = '__Host-airev-csrf';
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'host', 'cookie',
]);

async function handler(request: NextRequest): Promise<NextResponse> {
  // Double-submit CSRF plus a strict Origin check for every unsafe request.
  if (UNSAFE.has(request.method)) {
    const headerToken = request.headers.get('x-csrf-token');
    const cookieToken = request.cookies.get(CSRF_COOKIE)?.value;
    if (!headerToken || !cookieToken || headerToken !== cookieToken) {
      return NextResponse.json(
        {
          success: false,
          error: { code: 'FORBIDDEN', message: 'CSRF validation failed.', details: {} },
          meta: { request_id: crypto.randomUUID(), timestamp: new Date().toISOString(), version: 'v1' },
        },
        { status: 403 },
      );
    }
  }

  const accessToken = await exchangeSessionForAccessToken(request.cookies.get(SESSION_COOKIE)?.value);

  const upstream = new URL(request.nextUrl.pathname.replace(/^\/api/, '/v1') + request.nextUrl.search, API_BASE);
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  if (accessToken) headers.set('authorization', `Bearer ${accessToken}`);

  const response = await fetch(upstream, {
    method: request.method,
    headers,
    body: UNSAFE.has(request.method) ? await request.text() : undefined,
    redirect: 'manual',
    cache: 'no-store',
  });

  const body = await response.text();
  const out = new NextResponse(body, { status: response.status });
  for (const key of ['content-type', 'etag', 'x-request-id', 'retry-after']) {
    const value = response.headers.get(key);
    if (value) out.headers.set(key, value);
  }
  // A token is never written into a response body or a readable cookie.
  return out;
}

async function exchangeSessionForAccessToken(session: string | undefined): Promise<string | null> {
  if (!session) return null;
  const response = await fetch(new URL('/v1/auth/refresh', API_BASE), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ refresh_token: session }),
    cache: 'no-store',
  });
  if (!response.ok) return null;
  const payload = (await response.json()) as { data?: { access_token?: string } };
  return payload.data?.access_token ?? null;
}

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const PUT = handler;
export const DELETE = handler;
