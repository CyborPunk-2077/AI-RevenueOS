'use client';

import { Moon, Sun } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from './cn';

type Theme = 'light' | 'dark';

/**
 * The theme control.
 *
 * Dark mode is a class on `<html>`, set before paint by the inline script in the
 * root layout so there is no flash of the wrong theme. **That architecture and
 * the `airev-theme` localStorage key are unchanged** - this control only records
 * the choice and flips the class, exactly as the text button it replaces did.
 *
 * Two explicit segments rather than one button that says the opposite of the
 * current state. "Dark mode" as a label is genuinely ambiguous: it reads as both
 * "you are in dark mode" and "switch to dark mode", and which one somebody
 * assumes depends on which product they used last. Two segments with
 * `aria-pressed` say what is on and what is available at the same time, and a
 * screen reader gets the same information the icons give.
 */
export function ThemeToggle(): JSX.Element {
  const [theme, setTheme] = useState<Theme>('light');
  // Until the effect runs, the server-rendered markup cannot know the stored
  // choice. Reporting "light is pressed" during that moment would be a lie half
  // the time, so neither segment claims to be pressed until it is known.
  const [known, setKnown] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem('airev-theme') as Theme | null;
    setTheme(
      stored ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
    );
    setKnown(true);
  }, []);

  function apply(next: Theme): void {
    setTheme(next);
    setKnown(true);
    document.documentElement.classList.toggle('dark', next === 'dark');
    window.localStorage.setItem('airev-theme', next);
  }

  const segment = (value: Theme, Icon: typeof Sun, label: string): JSX.Element => {
    const active = known && theme === value;
    return (
      <button
        type="button"
        aria-pressed={active}
        aria-label={label}
        title={label}
        onClick={() => apply(value)}
        // No explicit height: the global 44px minimum-target rule owns it, and
        // designing under that rule rather than around it is the whole reason
        // dense screens elsewhere get an exemption and this does not.
        className={cn(
          'inline-flex w-11 items-center justify-center rounded-sm transition-colors',
          active ? 'bg-surface text-foreground' : 'text-muted-foreground hover:text-foreground',
        )}
      >
        <Icon aria-hidden="true" size={15} strokeWidth={1.75} />
      </button>
    );
  };

  return (
    <div
      role="group"
      aria-label="Theme"
      className="inline-flex items-center gap-0.5 rounded border border-border bg-surface-sunken p-0.5"
    >
      {segment('light', Sun, 'Light theme')}
      {segment('dark', Moon, 'Dark theme')}
    </div>
  );
}
