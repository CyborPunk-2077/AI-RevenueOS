import type { ReactNode } from 'react';

/**
 * Renders the same component twice, light beside dark.
 *
 * Dark mode in this product is a first-class theme designed alongside the light
 * one, not an inversion of it - so it has to be reviewed alongside, and the
 * accessibility gate has to scan it. The gate visits each story once with the
 * default globals, so a story that only rendered the light theme would leave
 * every dark-mode contrast pair unmeasured. Rendering both inside one story
 * means one axe pass covers both.
 *
 * `.dark` is a class on a container rather than on `<html>` here, which is
 * exactly how the tokens are written: they cascade from whichever element
 * carries the class.
 */
export function ThemePair({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-lg border border-border bg-canvas p-5 text-foreground">
        <p className="mb-4 text-[11px] uppercase tracking-[0.06em] text-muted-foreground">Light</p>
        {children}
      </div>
      <div className="dark rounded-lg border border-border bg-canvas p-5 text-foreground">
        <p className="mb-4 text-[11px] uppercase tracking-[0.06em] text-muted-foreground">Dark</p>
        {children}
      </div>
    </div>
  );
}
