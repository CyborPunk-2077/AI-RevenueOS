import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewContactForm, type AccountOption } from '@/features/crm/new-contact-form';
import { PageHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

interface Contact {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly phone: string | null;
  readonly title: string | null;
  readonly status: string;
  readonly account_name: string | null;
}

export default async function ContactsPage({
  searchParams,
}: {
  searchParams?: { search?: string };
}): Promise<JSX.Element> {
  const search = (searchParams?.search ?? '').trim();
  // Search runs on the server, inside the tenant- and scope-filtered query.
  const query = search ? `&search=${encodeURIComponent(search)}` : '';

  const [result, accountResult] = await Promise.all([
    apiFetch<{ contacts: Contact[] }>(`/contacts?page_size=50${query}`),
    apiFetch<{ accounts: AccountOption[] }>('/accounts?page_size=200'),
  ]);
  const contacts = result.data?.contacts ?? [];
  const accounts = accountResult.data?.accounts ?? [];

  return (
    <div className="space-y-8">
      <PageHeader title="Contacts" description="Only your organisation&rsquo;s records are visible here." />

      <form method="get" role="search" className="flex gap-2">
        <label htmlFor="search" className="sr-only">
          Search contacts
        </label>
        <input
          id="search"
          name="search"
          type="search"
          defaultValue={search}
          placeholder="Name, email, company or phone"
          data-testid="contact-search"
          className="w-full max-w-sm rounded border px-3 py-2"
        />
        <button type="submit" className="rounded border px-4 py-2">
          Search
        </button>
        {search ? (
          <Link href="/contacts" className="rounded border px-4 py-2">
            Clear
          </Link>
        ) : null}
      </form>

      <NewContactForm accounts={accounts} />

      {!result.ok ? (
        <p role="alert" className="rounded border border-destructive p-4 text-sm text-destructive">
          {result.error ?? 'Could not load contacts.'}
        </p>
      ) : null}

      <section aria-labelledby="contact-list-heading">
        <h2 id="contact-list-heading" className="sr-only">
          Contact list
        </h2>

        {contacts.length === 0 ? (
          <p
            data-testid="contacts-empty"
            className="surface border-dashed p-6 text-center text-sm text-muted-foreground"
          >
            {search
              ? `No contacts match “${search}”.`
              : 'No contacts yet. Create one above.'}
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Contacts for your organisation</caption>
            <thead>
              <tr className="row-hover border-b border-border/60">
                <th scope="col" className="py-2">
                  Name
                </th>
                <th scope="col" className="py-2">
                  Email
                </th>
                <th scope="col" className="py-2">
                  Account
                </th>
                <th scope="col" className="py-2">
                  Status
                </th>
              </tr>
            </thead>
            <tbody data-testid="contact-rows">
              {contacts.map((contact) => (
                <tr key={contact.id} className="border-b">
                  <td className="py-2">
                    <Link
                      href={`/contacts/${contact.id}`}
                      data-testid={`contact-link-${contact.id}`}
                      className="underline"
                    >
                      {contact.first_name} {contact.last_name ?? ''}
                    </Link>
                    {contact.title ? (
                      <span className="block text-xs text-muted-foreground">{contact.title}</span>
                    ) : null}
                  </td>
                  <td className="py-2">{contact.email ?? '—'}</td>
                  <td className="py-2">{contact.account_name ?? '—'}</td>
                  <td className="py-2">{contact.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
