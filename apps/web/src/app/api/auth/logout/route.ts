import { NextRequest, NextResponse } from 'next/server';
import { API_BASE, cookieNames, readSessionCookie } from '@/lib/session';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest): Promise<NextResponse> {
  const session = readSessionCookie(request.cookies);
  if (session) {
    // Revoke the whole family server side, not just locally.
    await fetch(`${API_BASE}/v1/auth/logout`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ refresh_token: session }),
      cache: 'no-store',
    }).catch(() => undefined);
  }

  const response = NextResponse.json({ signedOut: true });
  for (const secure of [true, false]) {
    const names = cookieNames(secure);
    response.cookies.delete(names.session);
    response.cookies.delete(names.csrf);
    response.cookies.delete(names.access);
  }
  return response;
}
