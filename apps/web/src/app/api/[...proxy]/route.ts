/**
 * The BFF proxy. It is the only component that holds tokens: the browser sees a
 * host-only, Secure, HttpOnly, SameSite=Lax refresh-session cookie and nothing else.
 */
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

import {
  API_BASE,
  cookieNames,
  readAccessCookie,
  readSessionCookie,
  rotateSession,
} from '@/lib/session';

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'host', 'cookie',
]);

async function handler(request: NextRequest): Promise<NextResponse> {
  // /api/auth/* is handled by dedicated routes that manage cookies.
  if (request.nextUrl.pathname.startsWith('/api/auth/')) {
    return NextResponse.json(
      { error: { code: 'NOT_FOUND', message: 'Not found.' } },
      { status: 404 },
    );
  }

  // Double-submit CSRF plus a strict Origin check for every unsafe request.
  if (UNSAFE.has(request.method)) {
    const headerToken = request.headers.get('x-csrf-token');
    const cookieToken =
      request.cookies.get(cookieNames(true).csrf)?.value ??
      request.cookies.get(cookieNames(false).csrf)?.value;
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

  const secure = request.nextUrl.protocol === 'https:';
  const names = cookieNames(secure);

  let accessToken = readAccessCookie(request.cookies) ?? null;
  let rotated: Awaited<ReturnType<typeof rotateSession>> = null;

  if (!accessToken) {
    const session = readSessionCookie(request.cookies);
    rotated = session ? await rotateSession(session) : null;
    accessToken = rotated?.accessToken ?? null;
  }

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
  // If the session was rotated during this request, persist both new values.
  if (rotated) {
    const options = {
      httpOnly: true,
      secure,
      sameSite: 'lax' as const,
      path: '/',
    };
    out.cookies.set(names.session, rotated.refreshToken, {
      ...options,
      maxAge: 60 * 60 * 24 * 7,
    });
    out.cookies.set(names.access, rotated.accessToken, {
      ...options,
      maxAge: rotated.expiresIn,
    });
  }

  // A token is never written into a response body or a readable cookie.
  return out;
}

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const PUT = handler;
export const DELETE = handler;
