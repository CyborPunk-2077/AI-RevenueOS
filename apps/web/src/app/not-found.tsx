import Link from 'next/link';

export default function NotFound(): JSX.Element {
  return (
    <main id="main-content" className="mx-auto max-w-md px-6 py-16">
      <h1 className="text-xl font-semibold">Not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        This record does not exist, or it belongs to another organisation.
      </p>
      <Link href="/leads" className="mt-4 inline-block underline">
        Back to leads
      </Link>
    </main>
  );
}
