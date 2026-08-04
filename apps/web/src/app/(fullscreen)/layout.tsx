/**
 * Chrome-free surfaces: public booking, hosted forms, document signing, print.
 *
 * These are reached by people who are not users of the product and never will
 * be, so there is no navigation, no tenant switcher and nothing that implies an
 * account. The skip link in the root layout still applies.
 */
export default function FullscreenLayout({
  children,
}: {
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className="min-h-screen bg-background">
      <main id="main-content" className="mx-auto max-w-2xl px-4 py-10">
        {children}
      </main>
    </div>
  );
}
