import Link from 'next/link';
import { SignOutButton } from '@/features/auth/sign-out-button';
import { ThemeToggle } from '@/features/ui/theme-toggle';

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
    | 'today'
    | 'leads'
    | 'follow-ups'
    | 'contacts'
    | 'accounts'
    | 'deals'
    | 'inbox'
    | 'appointments'
    | 'analytics'
    | 'imports'
    | 'test-center'
    | 'settings';
  children: React.ReactNode;
}): JSX.Element {
  // Ordered as the working day runs: what is slipping, who enquired, what was
  // promised, then the records behind them. Alphabetical or module order would
  // put Accounts before the queue somebody opens first thing every morning.
  const tabs = [
    { key: 'today', href: '/today', label: 'Today' },
    { key: 'leads', href: '/leads', label: 'Prospects' },
    { key: 'follow-ups', href: '/follow-ups', label: 'Follow-ups' },
    { key: 'contacts', href: '/contacts', label: 'Contacts' },
    { key: 'accounts', href: '/accounts', label: 'Accounts' },
    { key: 'deals', href: '/deals', label: 'Deals' },
    { key: 'inbox', href: '/inbox', label: 'Inbox' },
    { key: 'appointments', href: '/appointments', label: 'Appointments' },
    { key: 'imports', href: `/${tenantSlug}/imports`, label: 'Import' },
    { key: 'analytics', href: '/analytics', label: 'Analytics' },
    { key: 'settings', href: '/settings/integrations', label: 'Settings' },
  ];

  return (
    <div className="min-h-screen">
      {/* Two rows rather than one. Eleven sections and an email address do not fit
          on a single line at laptop width: they wrapped, and the wrapped nav
          climbed over the wordmark. Identity on top, navigation beneath it as a
          proper tab strip that scrolls sideways instead of reflowing. */}
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 pt-3">
          <Link href="/today" className="heading text-lg">
            Sangam
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <span className="truncate text-muted-foreground" data-testid="tenant-badge">
              {tenantSlug} &middot; {email}
            </span>
            <ThemeToggle />
            <SignOutButton />
          </div>
        </div>
        <div className="mx-auto max-w-6xl px-6">
          <nav aria-label="Sections" className="-mb-px flex gap-1 overflow-x-auto">
            {tabs.map((tab) => (
              <Link
                key={tab.key}
                href={tab.href}
                data-testid={`nav-${tab.key}`}
                aria-current={active === tab.key ? 'page' : undefined}
                className={`whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition-colors ${
                  active === tab.key
                    ? 'border-primary font-medium text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label}
              </Link>
            ))}
          </nav>
        </div>
        {active === 'settings' && (
          <div className="border-t bg-muted/20">
            <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-2">
              <nav aria-label="Settings Sections" className="flex flex-wrap gap-4 text-sm">
                <Link
                  href="/settings/integrations"
                  className="text-muted-foreground hover:text-foreground"
                >
                  Integrations
                </Link>
                <Link
                  href={`/${tenantSlug}/settings/webchat`}
                  className="text-muted-foreground hover:text-foreground"
                >
                  Web Chat
                </Link>
                <Link
                  href={`/${tenantSlug}/settings/team`}
                  className="text-muted-foreground hover:text-foreground"
                >
                  Team
                </Link>
                {/* Development only. The route itself refuses to render outside a
                    local build, so this link cannot expose it in production. */}
                <Link
                  href="/test-center"
                  className="text-muted-foreground hover:text-foreground"
                >
                  Test Centre
                </Link>
              </nav>
            </div>
          </div>
        )}
      </header>
      <main id="main-content" className="mx-auto max-w-6xl px-6 py-8">
        {children}
      </main>
    </div>
  );
}
