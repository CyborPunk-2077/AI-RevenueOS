/**
 * The unauthenticated shell: sign-in, sign-up, password reset, invitation
 * acceptance.
 *
 * Deliberately has no navigation. Every link out of here would either 401 or
 * bounce back to /login, and offering a person a menu they cannot use is worse
 * than offering none.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
      <main id="main-content" className="w-full max-w-md">
        <div className="mb-8 text-center">
          <p className="text-lg font-semibold tracking-tight">Sangam</p>
        </div>
        <div className="rounded-lg border border-border bg-background p-6 shadow-sm">{children}</div>
      </main>
    </div>
  );
}
