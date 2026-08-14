import type { Config } from 'tailwindcss';

/**
 * Every colour is a CSS variable, never a literal. That is what lets dark mode
 * be a class on `<html>` rather than a second set of utilities on every element,
 * and it is why changing a token propagates without a find-and-replace.
 *
 * The canonical names come from `docs/SANGAM-UI-UX-SYSTEM.md` section 12. The
 * aliases beneath them (`background`, `primary`, `destructive`, `success`) are
 * the previous vocabulary, kept pointing at the new tokens so the whole product
 * inherits the system at once instead of drifting into two palettes while the
 * screens are rebuilt one at a time.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // surfaces
        canvas: 'hsl(var(--canvas))',
        surface: 'hsl(var(--surface))',
        'surface-sunken': 'hsl(var(--surface-sunken))',
        'surface-hover': 'hsl(var(--surface-hover))',

        // text
        foreground: 'hsl(var(--text-primary))',
        'secondary-foreground': 'hsl(var(--text-secondary))',
        'muted-foreground': 'hsl(var(--text-muted))',
        'disabled-foreground': 'hsl(var(--text-disabled))',

        // boundaries
        border: 'hsl(var(--border))',
        'border-strong': 'hsl(var(--border-strong))',
        ring: 'hsl(var(--border-focus))',

        // the Sangam accent
        accent: 'hsl(var(--accent))',
        'accent-hover': 'hsl(var(--accent-hover))',
        'accent-soft': 'hsl(var(--accent-soft))',
        'accent-foreground': 'hsl(var(--accent-fg))',

        // semantic, used only where the meaning is genuinely useful
        critical: 'hsl(var(--critical))',
        'critical-soft': 'hsl(var(--critical-soft))',
        warning: 'hsl(var(--warning))',
        'warning-soft': 'hsl(var(--warning-soft))',
        positive: 'hsl(var(--positive))',
        'positive-soft': 'hsl(var(--positive-soft))',

        // compatibility aliases — same tokens under the previous names
        background: 'hsl(var(--canvas))',
        muted: 'hsl(var(--surface-sunken))',
        primary: 'hsl(var(--accent))',
        'primary-foreground': 'hsl(var(--accent-fg))',
        'primary-soft': 'hsl(var(--accent-soft))',
        success: 'hsl(var(--positive))',
        'success-soft': 'hsl(var(--positive-soft))',
        destructive: 'hsl(var(--critical))',
        'destructive-soft': 'hsl(var(--critical-soft))',
      },
      fontFamily: {
        // One family. `display` resolves to the same stack: hierarchy comes from
        // size, weight and colour, not from a second typeface.
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        DEFAULT: 'var(--radius)',
        md: 'var(--radius)',
        lg: 'var(--radius-lg)',
      },
      boxShadow: {
        // Overlays only: menus, drawers, dialogs. Never a panel.
        overlay: 'var(--shadow-overlay)',
        drawer: 'var(--shadow-drawer)',
        sm: 'var(--shadow-overlay)',
        md: 'var(--shadow-overlay)',
        lg: 'var(--shadow-drawer)',
      },
      spacing: {
        sidebar: 'var(--sidebar-width)',
        'sidebar-rail': 'var(--sidebar-collapsed)',
        'utility-bar': 'var(--utility-bar-height)',
      },
      maxWidth: {
        page: 'var(--page-max)',
        reading: 'var(--reading-max)',
      },
      keyframes: {
        'overlay-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'drawer-in': {
          from: { opacity: '0', transform: 'translateX(12px)' },
          to: { opacity: '1', transform: 'none' },
        },
      },
      animation: {
        // 180ms for entry. Past roughly 250ms an interface starts reading as slow
        // to somebody who opens it forty times a day.
        'overlay-in': 'overlay-in 180ms ease-out both',
        'drawer-in': 'drawer-in 180ms cubic-bezier(0.22, 1, 0.36, 1) both',
      },
    },
  },
  plugins: [],
};

export default config;
