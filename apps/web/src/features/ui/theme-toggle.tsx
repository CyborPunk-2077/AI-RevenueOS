'use client';

import { useEffect, useState } from 'react';

type Theme = 'light' | 'dark';

/**
 * Dark mode is a class on `<html>`, set before paint by the inline script in the
 * root layout so there is no flash of the wrong theme. This control only records
 * the choice and flips the class.
 *
 * The button reports state through `aria-pressed` as well as its label; an icon
 * swap alone tells a screen reader nothing.
 */
export function ThemeToggle(): JSX.Element {
  const [theme, setTheme] = useState<Theme>('light');

  useEffect(() => {
    const stored = window.localStorage.getItem('airev-theme') as Theme | null;
    const preferred =
      stored ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(preferred);
  }, []);

  function apply(next: Theme): void {
    setTheme(next);
    document.documentElement.classList.toggle('dark', next === 'dark');
    window.localStorage.setItem('airev-theme', next);
  }

  return (
    <button
      type="button"
      aria-pressed={theme === 'dark'}
      onClick={() => apply(theme === 'dark' ? 'light' : 'dark')}
      className="interactive rounded border border-border px-3 py-1.5 text-sm"
    >
      {theme === 'dark' ? 'Light mode' : 'Dark mode'}
    </button>
  );
}
