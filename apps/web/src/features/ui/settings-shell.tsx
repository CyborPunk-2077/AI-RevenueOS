import Link from 'next/link';
import type { ReactNode } from 'react';
import { cn } from './cn';

/**
 * The settings layout: a section list on the left, content on the right.
 *
 * The sections used to live in a third row of the application header, appearing
 * only once you were already inside Settings - so there was no way to see what
 * Settings contained without going there and looking. A persistent list is both
 * the map and the navigation.
 *
 * The Test Centre is listed only outside production. The route itself refuses to
 * render there, so this is not the security boundary; it is just not offering a
 * door that is locked.
 */

export type SettingsSection = 'integrations' | 'webchat' | 'team' | 'test-center';

export function SettingsShell({
  tenantSlug,
  active,
  children,
}: {
  tenantSlug: string;
  active: SettingsSection;
  children: ReactNode;
}): JSX.Element {
  const sections: Array<{ key: SettingsSection; href: string; label: string; hint: string }> = [
    {
      key: 'integrations',
      href: '/settings/integrations',
      label: 'Integrations',
      hint: 'What each channel can and cannot do',
    },
    {
      key: 'webchat',
      href: `/${tenantSlug}/settings/webchat`,
      label: 'Web chat',
      hint: 'The widget on your site',
    },
    { key: 'team', href: `/${tenantSlug}/settings/team`, label: 'Team', hint: 'People and invitations' },
  ];

  if (process.env.NODE_ENV !== 'production') {
    sections.push({
      key: 'test-center',
      href: '/test-center',
      label: 'Test Centre',
      hint: 'Development only',
    });
  }

  return (
    <div className="flex flex-col gap-8 min-[900px]:flex-row min-[900px]:items-start">
      <nav
        aria-label="Settings sections"
        className="w-full shrink-0 min-[900px]:w-[13.5rem] min-[900px]:border-r min-[900px]:border-border min-[900px]:pr-4"
      >
        <ul>
          {sections.map((section) => {
            const current = section.key === active;
            return (
              <li key={section.key}>
                <Link
                  href={section.href}
                  aria-current={current ? 'page' : undefined}
                  className={cn(
                    'relative block rounded px-2.5 py-2 text-sm transition-colors',
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
                  {section.label}
                  <span className="mt-0.5 block text-[13px] font-normal text-muted-foreground">
                    {section.hint}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
