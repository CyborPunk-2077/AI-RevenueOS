import type { Config } from 'tailwindcss';

/**
 * Every colour is a CSS variable, never a literal. That is what lets dark mode
 * be a class on `<html>` rather than a second set of utilities on every element,
 * and it is why changing a token propagates without a find-and-replace.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: 'hsl(var(--background))',
        surface: 'hsl(var(--surface))',
        'surface-sunken': 'hsl(var(--surface-sunken))',
        foreground: 'hsl(var(--foreground))',
        'muted-foreground': 'hsl(var(--muted-foreground))',
        primary: 'hsl(var(--primary))',
        'primary-foreground': 'hsl(var(--primary-foreground))',
        'primary-soft': 'hsl(var(--primary-soft))',
        accent: 'hsl(var(--accent))',
        'accent-foreground': 'hsl(var(--accent-foreground))',
        'accent-soft': 'hsl(var(--accent-soft))',
        success: 'hsl(var(--success))',
        'success-soft': 'hsl(var(--success-soft))',
        warning: 'hsl(var(--warning))',
        'warning-soft': 'hsl(var(--warning-soft))',
        destructive: 'hsl(var(--destructive))',
        'destructive-soft': 'hsl(var(--destructive-soft))',
        border: 'hsl(var(--border))',
        'border-strong': 'hsl(var(--border-strong))',
        ring: 'hsl(var(--ring))',
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['var(--font-display)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        DEFAULT: 'var(--radius)',
        lg: 'var(--radius-lg)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'none' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.97)' },
          to: { opacity: '1', transform: 'none' },
        },
      },
      animation: {
        // Fast enough not to delay the content, slow enough to be perceived.
        // Past roughly 250ms a list animation starts reading as sluggish.
        'fade-up': 'fade-up 220ms cubic-bezier(0.22, 1, 0.36, 1) both',
        'scale-in': 'scale-in 160ms cubic-bezier(0.22, 1, 0.36, 1) both',
      },
      transitionTimingFunction: {
        smooth: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
};

export default config;
