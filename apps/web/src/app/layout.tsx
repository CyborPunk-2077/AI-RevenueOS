import type { Metadata, Viewport } from 'next';
import { Inter, Outfit } from 'next/font/google';
import { Providers } from '@/providers/providers';
import './globals.css';

/**
 * Self-hosted by next/font: no render-blocking request to Google, no layout
 * shift, and no third-party origin in the critical path of a product that makes
 * data-residency claims.
 */
const sans = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
});

const display = Outfit({
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
  weight: ['500', '600', '700'],
});

export const metadata: Metadata = {
  title: { default: 'AI RevenueOS', template: '%s | AI RevenueOS' },
  description: 'RevenueOS for Indian SMEs',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // Never disable zoom: WCAG 2.2 AA reflow and magnification depend on it.
  maximumScale: 5,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}): JSX.Element {
  return (
    <html lang="en-IN" className={`${sans.variable} ${display.variable}`} suppressHydrationWarning>
      <head>
        {/*
         * Blocking and inline on purpose. Any deferred script - including a
         * client component's effect - runs after first paint, which is exactly
         * when a dark-mode user sees a white flash. Reading localStorage
         * synchronously costs well under a millisecond and removes it entirely.
         */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{var t=localStorage.getItem('airev-theme');" +
              "if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}" +
              "if(t==='dark'){document.documentElement.classList.add('dark');}}catch(e){}})();",
          }}
        />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        {/* Skip link is the first focusable element on every page. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
        >
          Skip to main content
        </a>
        <Providers>{children}</Providers>
        {/* Polite live region for status announcements. */}
        <div id="status-announcer" role="status" aria-live="polite" className="sr-only" />
        {/* Assertive live region reserved for errors. */}
        <div id="error-announcer" role="alert" aria-live="assertive" className="sr-only" />
      </body>
    </html>
  );
}
