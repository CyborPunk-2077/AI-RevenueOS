import Link from 'next/link';
import { SignOutButton } from '@/features/auth/sign-out-button';

/**
 * The signed-in chrome, shared by leads, contacts and accounts.
 *
 * Extracted from the leads layout rather than copied: three layouts drifting
 * apart is how a "Contacts" tab ends up missing from one page and not another.
 * The tenant guard stays in each layout, because a guard that lives in a shared
 * component is easy to forget to call.
 */
export function WorkspaceShell({
  tenantSlug,
  email,
  active,
  children,
}: {
  tenantSlug: string;
  email: string;
  active:
    | 'leads'
    | 'contacts'
    | 'accounts'
    | 'deals'
    | 'inbox'
    | 'appointments'
    | 'analytics'
    | 'settings';
  children: React.ReactNode;
}): JSX.Element {
  const tabs = [
    { key: 'leads', href: '/leads', label: 'Leads' },
    { key: 'contacts', href: '/contacts', label: 'Contacts' },
    { key: 'accounts', href: '/accounts', label: 'Accounts' },
    { key: 'deals', href: '/deals', label: 'Deals' },
    { key: 'inbox', href: '/inbox', label: 'Inbox' },
    { key: 'appointments', href: '/appointments', label: 'Appointments' },
    { key: 'analytics', href: '/analytics', label: 'Analytics' },
    { key: 'settings', href: '/settings/integrations', label: 'Settings' },
  ] as const;

  return (
    <div className="min-h-screen">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-6">
            <Link href="/leads" className="font-semibold">
              AI RevenueOS
            </Link>
            <nav aria-label="Sections" className="flex flex-wrap gap-4 text-sm">
              {tabs.map((tab) => (
                <Link
                  key={tab.key}
                  href={tab.href}
                  data-testid={`nav-${tab.key}`}
                  aria-current={active === tab.key ? 'page' : undefined}
                  className={active === tab.key ? 'font-medium underline' : 'text-muted-foreground'}
                >
                  {tab.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-muted-foreground" data-testid="tenant-badge">
              {tenantSlug} &middot; {email}
            </span>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main id="main-content" className="mx-auto max-w-5xl px-6 py-8">
        {children}
      </main>
    </div>
  );
}
