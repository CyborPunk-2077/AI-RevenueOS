import { NextRequest, NextResponse } from 'next/server';
import { randomUUID } from 'crypto';
import { API_BASE, cookieNames, cookieOptionsFor } from '@/lib/session';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Sign-in happens here rather than through the generic proxy because the refresh
 * token must be written into an HttpOnly cookie and never returned to the page.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const { email, password } = (await request.json()) as {
    email?: string;
    password?: string;
  };

  const upstream = await fetch(`${API_BASE}/v1/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
    cache: 'no-store',
  });

  // Read the body once as text. A failing upstream may answer plain text rather
  // than JSON -- `Invalid host header` is exactly that -- and the raw form is the
  // only thing that identifies the cause.
  const raw = await upstream.text().catch(() => '');
  const payload = (() => {
    try {
      return JSON.parse(raw) as {
        success?: boolean;
        data?: {
          refresh_token?: string;
          access_token?: string;
          expires_in?: number;
          user?: unknown;
        };
        error?: { message?: string };
      };
    } catch {
      return null;
    }
  })();

  if (!upstream.ok || !payload?.success || !payload.data?.refresh_token || !payload.data.access_token) {
    // 401 is a wrong credential and needs no explanation. Anything else is a
    // misconfiguration the operator has to be able to see: without this line every
    // such cause collapsed into an indistinguishable "Sign in failed." in the
    // browser. The request body is never logged, so no credential is written out.
    if (upstream.status !== 401) {
      console.error(
        `[auth] upstream ${API_BASE}/v1/auth/login returned ${upstream.status}: ${raw.slice(0, 300)}`,
      );
    }
    return NextResponse.json(
      { error: payload?.error?.message ?? 'Sign in failed.' },
      { status: upstream.status === 401 ? 401 : 400 },
    );
  }

  // Only the user profile crosses back to the browser. No token, ever.
  const secure = request.nextUrl.protocol === 'https:';
  const names = cookieNames(secure);
  const options = cookieOptionsFor(secure);

  const response = NextResponse.json({ user: payload.data.user });
  response.cookies.set(names.session, payload.data.refresh_token, options);
  // Short-lived and HttpOnly: the page can use it, the browser cannot read it.
  response.cookies.set(names.access, payload.data.access_token, {
    ...options,
    maxAge: payload.data.expires_in ?? 900,
  });
  // Readable by design: the double-submit CSRF token must be echoed as a header.
  response.cookies.set(names.csrf, randomUUID(), { ...options, httpOnly: false });
  return response;
}
