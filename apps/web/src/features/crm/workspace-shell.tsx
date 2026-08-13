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
/**
 * How each kind of workspace announces itself.
 *
 * The founders now keep three of these open at once - their own prospecting
 * workspace, a pilot business's, and the one the browser tests write to - and
 * every screen in them looks identical. Getting this wrong means typing a real
 * customer into a test workspace, or worse, treating a pilot's numbers as your
 * own. A quiet, permanent label in the header is enough; a banner on every page
 * would be ignored within a day.
 *
 * `pilot` deliberately gets no warning colour. It is the one that holds a real
 * business's real data, and it should look completely ordinary to the people
 * working in it.
 */
const WORKSPACE_LABELS: Record<string, { label: string; className: string; hint: string }> = {
  founder: {
    label: 'our workspace',
    className: 'bg-muted text-muted-foreground',
    hint: 'Sangam’s own prospecting workspace, including sample data.',
  },
  pilot: {
    label: 'pilot',
    className: 'bg-primary/10 text-primary',
    hint: 'A pilot business’s live workspace. Everything here is their real data.',
  },
  test: {
    label: 'test workspace',
    className: 'bg-destructive/10 text-destructive',
    hint: 'Automated tests write here. Nothing in it is real, and it may be wiped.',
  },
  demo: {
    label: 'sample data',
    className: 'bg-muted text-muted-foreground',
    hint: 'A reference workspace of invented records.',
  },
};

export function WorkspaceShell({
  tenantSlug,
  email,
  workspaceName,
  workspaceKind,
  active,
  children,
}: {
  tenantSlug: string;
  email: string;
  workspaceName?: string | null;
  workspaceKind?: string | null;
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
          <div className="flex min-w-0 items-baseline gap-3">
            <Link href="/today" className="heading text-lg">
              Sangam
            </Link>
            {/* Whose workspace this is, said once and always in the same place. */}
            <span
              className="truncate text-sm font-medium"
              data-testid="workspace-name"
              title={workspaceKind ? WORKSPACE_LABELS[workspaceKind]?.hint : undefined}
            >
              {workspaceName ?? tenantSlug}
            </span>
            {workspaceKind && WORKSPACE_LABELS[workspaceKind] ? (
              <span
                data-testid="workspace-kind"
                data-kind={workspaceKind}
                className={`whitespace-nowrap rounded px-2 py-0.5 text-xs ${WORKSPACE_LABELS[workspaceKind].className}`}
              >
                {WORKSPACE_LABELS[workspaceKind].label}
              </span>
            ) : null}
          </div>
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
