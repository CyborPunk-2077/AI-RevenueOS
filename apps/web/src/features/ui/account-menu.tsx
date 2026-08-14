'use client';

import { ChevronDown, LogOut } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { Avatar } from './avatar';
import { cn } from './cn';

/**
 * Who is signed in, and the one thing you can do about it.
 *
 * The email used to sit in the header as loose text beside a bare "Sign out"
 * button. Both belong to the same fact, so they live in the same control: the
 * trigger states the account, the menu states the workspace it is in and offers
 * sign-out.
 *
 * Escape closes it, a click outside closes it, and focus returns to the trigger -
 * a menu that traps somebody at the top of the page is worse than no menu.
 */
export function AccountMenu({
  email,
  tenantSlug,
}: {
  email: string;
  tenantSlug: string;
}): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;

    function onKey(event: KeyboardEvent): void {
      if (event.key !== 'Escape') return;
      setOpen(false);
      trigger.current?.focus();
    }
    function onPointer(event: MouseEvent): void {
      if (container.current?.contains(event.target as Node)) return;
      setOpen(false);
    }

    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onPointer);
    };
  }, [open]);

  async function signOut(): Promise<void> {
    setBusy(true);
    await fetch('/api/auth/logout', { method: 'POST' });
    router.push('/login');
    router.refresh();
  }

  return (
    <div ref={container} className="relative">
      <button
        ref={trigger}
        type="button"
        data-testid="account-menu"
        aria-label={`Account: ${email}`}
        aria-expanded={open}
        aria-controls="account-panel"
        onClick={() => setOpen((current) => !current)}
        className={cn(
          'inline-flex max-w-[15rem] items-center gap-2 rounded px-2 text-sm transition-colors',
          open ? 'bg-surface-sunken' : 'hover:bg-surface-hover',
        )}
      >
        <Avatar name={email.split('@')[0] ?? email} size="md" tinted={false} />
        <span className="hidden truncate text-secondary-foreground lg:inline">{email}</span>
        <ChevronDown aria-hidden="true" size={14} strokeWidth={1.75} className="text-muted-foreground" />
      </button>

      {open ? (
        // A labelled panel rather than ARIA menu semantics. `role="menu"`
        // requires every child to be a `menuitem` and full arrow-key roving
        // focus; a two-line account summary is not a menuitem, and claiming the
        // role without the behaviour is worse for a screen reader than not
        // claiming it.
        <div
          id="account-panel"
          className="absolute right-0 top-full z-40 mt-1 w-64 animate-overlay-in rounded-lg border border-border bg-surface p-1 shadow-overlay"
        >
          <div className="px-3 py-2">
            <p className="truncate text-sm font-medium text-foreground">{email}</p>
            {/* The workspace this account is signed into, said in the same place
                the account is. Getting this wrong means typing a real customer
                into a test workspace. */}
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              Signed in to {tenantSlug}
            </p>
          </div>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            disabled={busy}
            data-testid="sign-out"
            onClick={() => void signOut()}
            className="flex w-full items-center gap-2 rounded px-3 text-left text-sm text-foreground transition-colors hover:bg-surface-hover disabled:opacity-55"
          >
            <LogOut aria-hidden="true" size={15} strokeWidth={1.75} />
            {busy ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      ) : null}
    </div>
  );
}
