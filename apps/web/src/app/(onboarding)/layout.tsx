/**
 * Onboarding: a signed-in tenant that is not yet ready to work.
 *
 * Separate from the dashboard shell on purpose. Showing the full navigation to
 * someone whose tenant has no pipeline, no users and no data invites them to
 * click into eight empty screens and conclude the product is broken.
 */
export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <p className="text-sm font-semibold">AI RevenueOS</p>
          <p className="text-xs text-muted-foreground">Setting up your workspace</p>
        </div>
      </header>
      <main id="main-content" className="mx-auto max-w-3xl px-4 py-10">
        {children}
      </main>
    </div>
  );
}
