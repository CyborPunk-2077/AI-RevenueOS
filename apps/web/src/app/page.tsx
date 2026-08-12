import { redirect } from 'next/navigation';
import { cookies } from 'next/headers';
import { readSessionCookie } from '@/lib/session';

export const dynamic = 'force-dynamic';

export default function Home(): never {
  redirect(readSessionCookie(cookies()) ? '/today' : '/login');
}
