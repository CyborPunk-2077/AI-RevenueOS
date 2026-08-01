import type { Metadata, Viewport } from 'next';
import { Providers } from '@/providers/providers';
import './globals.css';

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
    <html lang="en-IN" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
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
