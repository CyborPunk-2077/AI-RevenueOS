'use client';

import {
  BarChart3,
  Building2,
  CalendarClock,
  CheckSquare,
  Contact,
  Handshake,
  Inbox,
  LayoutList,
  Menu,
  Settings,
  Sun,
  Upload,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AccountMenu } from './account-menu';
import { cn } from './cn';
import { LabelChip } from './status';
import { ThemeToggle } from './theme-toggle';

/**
 * The application chrome: a persistent left sidebar and a slim utility bar.
 *
 * What this replaces was an eleven-item horizontal tab strip that scrolled
 * sideways at laptop width. Eleven peers in a scrolling strip is not navigation;
 * it is a menu bar that hides half of itself, and which half depends on the size
 * of the window. A salesperson could not learn where Follow-ups was, because it
 * was not anywhere in particular.
 *
 * Three rules hold this together:
 *
 * - **One list, one DOM.** The rail, the full sidebar and the overlay are the
 *   same markup at three widths, decided by CSS. Rendering a second copy for the
 *   collapsed state is how the previous header ended up duplicated across three
 *   layouts - and it would also mean two elements carrying every `nav-*` test id.
 * - **The group labels are not printed.** Five uppercase headings above twelve
 *   items is more chrome than navigation. Grouping is carried by spacing and a
 *   hairline, and named on each list for assistive technology.
 * - **The active item is a 2px rule**, plus foreground text and a sunken
 *   background. Never a filled pill.
 *
 * Widths follow section 24 of the UI/UX system: 240px with labels, a 64px icon
 * rail below 1200px, an overlay below 900px.
 */

export type SectionKey =
  | 'today'
  | 'leads'
  | 'follow-ups'
  | 'contacts'
  | 'accounts'
  | 'deals'
  | 'inbox'
  | 'appointments'
  | 'imports'
  | 'analytics'
  | 'test-center'
  | 'settings';

interface Item {
  key: SectionKey;
  href: string;
  label: string;
  icon: LucideIcon;
}

/**
 * Grouped in the order the working day runs, not in module order. Alphabetical
 * would put Accounts above the queue somebody opens first thing every morning.
 */
function groupsFor(tenantSlug: string): Array<{ name: string; items: Item[] }> {
  return [
    {
      name: 'Core work',
      items: [
        { key: 'today', href: '/today', label: 'Today', icon: Sun },
        { key: 'leads', href: '/leads', label: 'Prospects', icon: LayoutList },
        { key: 'follow-ups', href: '/follow-ups', label: 'Follow-ups', icon: CheckSquare },
      ],
    },
    {
      name: 'Customers',
      items: [
        { key: 'contacts', href: '/contacts', label: 'Contacts', icon: Contact },
        { key: 'accounts', href: '/accounts', label: 'Accounts', icon: Building2 },
        { key: 'deals', href: '/deals', label: 'Deals', icon: Handshake },
      ],
    },
    {
      name: 'Communication',
      items: [
        { key: 'inbox', href: '/inbox', label: 'Inbox', icon: Inbox },
        { key: 'appointments', href: '/appointments', label: 'Appointments', icon: CalendarClock },
      ],
    },
    {
      name: 'Operations',
      items: [
        { key: 'imports', href: `/${tenantSlug}/imports`, label: 'Import', icon: Upload },
        { key: 'analytics', href: '/analytics', label: 'Analytics', icon: BarChart3 },
      ],
    },
    {
      name: 'System',
      items: [
        { key: 'settings', href: '/settings/integrations', label: 'Settings', icon: Settings },
      ],
    },
  ];
}

/**
 * How each kind of workspace announces itself.
 *
 * The founders keep three of these open at once - their own prospecting
 * workspace, a pilot business's, and the one the browser tests write to - and
 * every screen in them looks identical. Getting it wrong means typing a real
 * customer into a test workspace, or reading a pilot's numbers as your own.
 *
 * `pilot` deliberately gets no warning colour. It holds a real business's real
 * data and should look completely ordinary to the people working in it.
 */
const WORKSPACE_LABELS: Record<
  string,
  { label: string; tone: 'neutral' | 'critical'; hint: string }
> = {
  founder: {
    label: 'our workspace',
    tone: 'neutral',
    hint: 'Sangam’s own prospecting workspace, including sample data.',
  },
  pilot: {
    label: 'pilot',
    tone: 'neutral',
    hint: 'A pilot business’s live workspace. Everything here is their real data.',
  },
  test: {
    label: 'test workspace',
    tone: 'critical',
    hint: 'Automated tests write here. Nothing in it is real, and it may be wiped.',
  },
  demo: {
    label: 'sample data',
    tone: 'neutral',
    hint: 'A reference workspace of invented records.',
  },
};

/**
 * The label is always in the DOM; below 1200px it is only visually hidden.
 *
 * That matters more than it looks. Giving the icon rail its accessible name with
 * `aria-label` instead made every sidebar link match `getByLabel`, and
 * `getByLabel('Follow-up')` - the task form's own field - suddenly resolved to
 * two elements. An accessible name that comes from the element's own text cannot
 * collide with a form label, and it needs no second source of truth.
 */
/*
 * Three widths, one element, no duplicated markers.
 *
 * The sidebar is full at 1200px and above, a 64px icon rail between 900 and
 * 1200, and an overlay below 900 - and it is the *same* `<aside>` in all three.
 * When the overlay opens, `data-open` goes on that one element and these
 * variants expand it, wherever the viewport happens to be.
 *
 * Rendering a second copy for the overlay is the obvious approach and it is
 * wrong twice over: two elements would carry every `nav-*` marker, so a locator
 * that is unambiguous on a laptop becomes a strict-mode failure on a tablet, and
 * two lists drift.
 */
const EXPANDED = 'sr-only min-[1200px]:not-sr-only group-data-[open=true]:not-sr-only';
const EXPANDED_BLOCK = 'hidden min-[1200px]:block group-data-[open=true]:block';
const COLLAPSED_ONLY = 'min-[1200px]:hidden group-data-[open=true]:hidden';
const ROW_LAYOUT =
  'justify-center px-0 min-[1200px]:justify-start min-[1200px]:px-2.5 group-data-[open=true]:justify-start group-data-[open=true]:px-2.5';

function SidebarPanel({
  tenantSlug,
  workspaceName,
  workspaceKind,
  active,
  onNavigate,
}: {
  tenantSlug: string;
  workspaceName?: string | null;
  workspaceKind?: string | null;
  active: SectionKey;
  onNavigate?: () => void;
}): JSX.Element {
  const groups = groupsFor(tenantSlug);
  const kind = workspaceKind ? WORKSPACE_LABELS[workspaceKind] : undefined;
  const name = workspaceName ?? tenantSlug;
  const expanded = EXPANDED;
  const expandedBlock = EXPANDED_BLOCK;
  const rowLayout = ROW_LAYOUT;

  return (
    <>
      <div
        className={cn(
          'flex h-[var(--utility-bar-height)] shrink-0 items-center border-b border-border',
          'justify-center min-[1200px]:justify-start min-[1200px]:px-3',
          'group-data-[open=true]:justify-start group-data-[open=true]:px-3',
        )}
      >
        <Link
          href="/today"
          onClick={onNavigate}
          className="text-base font-semibold tracking-[-0.01em] text-foreground"
        >
          <span className={expanded}>Sangam</span>
          <span className={COLLAPSED_ONLY} aria-hidden="true">
            S
          </span>
        </Link>
      </div>

      <nav aria-label="Sections" className="flex-1 overflow-y-auto px-2 py-3">
        {groups.map((group, index) => (
          <ul
            key={group.name}
            aria-label={group.name}
            className={cn(index > 0 && 'mt-2 border-t border-border pt-2')}
          >
            {group.items.map((item) => {
              const current = item.key === active;
              const Icon = item.icon;
              return (
                <li key={item.key}>
                  <Link
                    href={item.href}
                    data-testid={`nav-${item.key}`}
                    aria-current={current ? 'page' : undefined}
                    title={item.label}
                    onClick={onNavigate}
                    className={cn(
                      // 40px, not the global 44px. `li a[href]` is already exempt
                      // from that rule for prose and table links; a twelve-item
                      // sidebar at 44px pushes the workspace block off a 720px
                      // viewport, which is the height a laptop actually has.
                      'relative flex min-h-[40px] items-center gap-2.5 rounded text-sm transition-colors',
                      rowLayout,
                      current
                        ? 'bg-surface-sunken font-medium text-foreground'
                        : 'text-secondary-foreground hover:bg-surface-hover hover:text-foreground',
                    )}
                  >
                    {current ? (
                      <span
                        aria-hidden="true"
                        className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-accent"
                      />
                    ) : null}
                    <Icon size={17} strokeWidth={1.75} />
                    <span className={expanded}>{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ))}
      </nav>

      {/* Which workspace this is, said permanently and in one place. */}
      <div
        className={cn(
          'border-t border-border py-3 px-2',
          'min-[1200px]:px-3 group-data-[open=true]:px-3',
        )}
      >
        <p className={cn('text-[11px] uppercase tracking-[0.06em] text-muted-foreground', expandedBlock)}>
          Workspace
        </p>
        <p
          data-testid="workspace-name"
          title={kind?.hint}
          className={cn(
            'truncate text-center text-xs font-medium text-foreground',
            'min-[1200px]:mt-1 min-[1200px]:text-left min-[1200px]:text-sm',
            'group-data-[open=true]:mt-1 group-data-[open=true]:text-left group-data-[open=true]:text-sm',
          )}
        >
          {name}
        </p>
        {kind ? (
          <p className={cn('mt-1.5', expandedBlock)}>
            <LabelChip
              tone={kind.tone}
              data-testid="workspace-kind"
              data-kind={workspaceKind ?? undefined}
              title={kind.hint}
            >
              {kind.label}
            </LabelChip>
          </p>
        ) : null}
      </div>
    </>
  );
}

export function AppShell({
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
  active: SectionKey;
  children: React.ReactNode;
}): JSX.Element {
  const [overlayOpen, setOverlayOpen] = useState(false);

  // Escape closes it, the same contract every other overlay in the product has.
  useEffect(() => {
    if (!overlayOpen) return undefined;
    function onKey(event: KeyboardEvent): void {
      if (event.key === 'Escape') setOverlayOpen(false);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [overlayOpen]);

  return (
    <div className="flex min-h-screen">
      {/*
        One `<aside>` at all three widths.

        In the flow rather than `fixed`, with the panel inside it sticky: a fixed
        sidebar leaves the rest of the column blank on any page taller than the
        viewport - including in the full-page screenshots this product is
        reviewed with - and it takes the layout out of the flex row for no gain.

        Below 900px it is hidden until the hamburger opens it, at which point
        `data-open` turns this same element into the overlay. A second rendered
        copy would put two elements behind every `nav-*` marker, so a locator
        that is unambiguous on a laptop would fail on a tablet.
      */}
      <aside
        data-open={overlayOpen}
        className={cn(
          'group hidden w-[var(--sidebar-collapsed)] shrink-0 border-r border-border bg-surface',
          'min-[900px]:block min-[1200px]:w-[var(--sidebar-width)]',
          // `!block`, because Tailwind emits `hidden` after `block` and the two
          // have equal specificity - the plain utility would lose to the
          // `hidden` that keeps this off the screen below 900px.
          overlayOpen &&
            '!block fixed inset-y-0 left-0 z-50 w-[var(--sidebar-width)] shadow-drawer',
        )}
      >
        <div className="sticky top-0 flex h-screen flex-col">
          <SidebarPanel
            tenantSlug={tenantSlug}
            workspaceName={workspaceName}
            workspaceKind={workspaceKind}
            active={active}
            onNavigate={overlayOpen ? () => setOverlayOpen(false) : undefined}
          />
        </div>
      </aside>

      {overlayOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setOverlayOpen(false)}
          className="fixed inset-0 z-40 animate-overlay-in bg-foreground/25 min-[900px]:hidden"
        />
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-[var(--utility-bar-height)] shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
          <button
            type="button"
            aria-label="Open navigation"
            aria-expanded={overlayOpen}
            onClick={() => setOverlayOpen(true)}
            className="-ml-2 inline-flex w-11 items-center justify-center rounded text-secondary-foreground hover:bg-surface-hover min-[900px]:hidden"
          >
            <Menu size={18} strokeWidth={1.75} />
          </button>

          {/*
            The slug, visible at every width. It is the one fact that says which
            of three identical-looking workspaces this is; behind a menu it would
            only be true while somebody had the menu open.
          */}
          <span className="truncate text-sm text-muted-foreground" data-testid="tenant-badge">
            {tenantSlug}
          </span>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <AccountMenu email={email} tenantSlug={tenantSlug} />
          </div>
        </header>

        <main id="main-content" className="flex-1 px-5 py-6 min-[900px]:px-8 min-[900px]:py-7">
          <div className="max-w-page">{children}</div>
        </main>
      </div>
    </div>
  );
}
