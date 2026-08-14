'use client';

import { X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';

/**
 * A right-hand panel for creating or editing one thing.
 *
 * **Drawers are for writing, never for reading.** A record always opens as a page
 * with its own URL, because a customer somebody is looking at should be a thing
 * they can send to a colleague. A drawer exists only where it removes a
 * navigation step from a task somebody came to the list to perform once - adding
 * a business, editing a field, reviewing a duplicate.
 *
 * Escape closes it, focus moves into it on open and returns to whatever opened
 * it on close, and Tab is trapped while it is open. None of that is decoration:
 * a panel that leaves focus behind on the page underneath is a panel a keyboard
 * user cannot use and a screen-reader user cannot find.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  'data-testid': testId,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  'data-testid'?: string;
}): JSX.Element | null {
  const panel = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;

    returnTo.current = document.activeElement as HTMLElement | null;
    // The first real control, not the close button: somebody who opened "Add a
    // business" wants to be typing the name.
    const focusables = (): HTMLElement[] =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
    const first = focusables().find((element) => element.tagName !== 'BUTTON') ?? focusables()[0];
    first?.focus();

    function onKey(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const firstItem = items[0]!;
      const lastItem = items[items.length - 1]!;
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    }

    document.addEventListener('keydown', onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      returnTo.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 animate-overlay-in bg-foreground/25"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        data-testid={testId}
        className="relative flex h-full w-full max-w-[30rem] animate-drawer-in flex-col border-l border-border bg-surface shadow-drawer"
      >
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="drawer-title" className="text-[15px] font-semibold text-foreground">
              {title}
            </h2>
            {description ? (
              <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-2 -mt-2 inline-flex w-11 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground"
          >
            <X size={17} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer ? (
          <footer className="border-t border-border px-5 py-3.5">{footer}</footer>
        ) : null}
      </div>
    </div>
  );
}
