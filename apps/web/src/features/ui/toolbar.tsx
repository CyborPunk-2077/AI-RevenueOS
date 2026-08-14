'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { cn } from './cn';

/**
 * The strip directly above a table: filters on the left, actions on the right.
 *
 * Filters are text links carrying counts, with the active one at weight 500 and
 * a 2px underline. That is the model the Inbox and Follow-ups already use and it
 * is the right one: a count that leads to the rows behind it is the difference
 * between a dashboard and a decoration, and a link is navigable, shareable and
 * back-buttonable in a way a dropdown is not.
 */

export interface FilterLink {
  key: string;
  href: string;
  label: string;
  /** Omitted where the count is not known rather than shown as zero. */
  count?: number;
  testId?: string;
}

export function FilterLinks({
  links,
  active,
  className = '',
  'aria-label': ariaLabel = 'Filters',
}: {
  links: FilterLink[];
  active: string;
  className?: string;
  'aria-label'?: string;
}): JSX.Element {
  return (
    <nav aria-label={ariaLabel} className={cn('flex flex-wrap items-center gap-1', className)}>
      {links.map((link) => {
        const current = link.key === active;
        return (
          <Link
            key={link.key}
            href={link.href}
            data-testid={link.testId}
            aria-current={current ? 'page' : undefined}
            className={cn(
              'inline-flex min-h-[32px] items-center gap-1.5 border-b-2 px-2 py-1 text-[13px] transition-colors',
              current
                ? 'border-accent font-medium text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {link.label}
            {/*
              Parenthesised, because a bare number beside a word reads as part of
              the label at a glance ("Overdue 3" looks like a heading). It is also
              the shape the Inbox's counts already had, and the browser suite that
              proves an empty view can be told apart from an empty inbox asserts
              on it.
            */}
            {link.count === undefined ? null : (
              <span
                className={cn(
                  'tabular',
                  current ? 'text-secondary-foreground' : 'text-muted-foreground',
                )}
              >
                ({link.count})
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

export function Toolbar({
  children,
  actions,
  className = '',
}: {
  children?: ReactNode;
  actions?: ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <div className={cn('flex flex-wrap items-end justify-between gap-3', className)}>
      <div className="min-w-0">{children}</div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
