import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewContactForm, type AccountOption } from '@/features/crm/new-contact-form';
import { Avatar } from '@/features/ui/avatar';
import { Button, controlClass } from '@/features/ui/controls';
import { DataTable, TableEmpty, type Column } from '@/features/ui/data-table';
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

const COLUMNS: Array<Column<Contact>> = [
  {
    key: 'name',
    header: 'Name',
    width: '30%',
    cell: (contact) => {
      const name = `${contact.first_name} ${contact.last_name ?? ''}`.trim();
      return (
        <span className="flex items-center gap-2">
          <Avatar name={name} />
          <span className="min-w-0">
            <Link
              href={`/contacts/${contact.id}`}
              data-testid={`contact-link-${contact.id}`}
              className="block truncate font-medium text-foreground underline-offset-2 hover:underline"
            >
              {name}
            </Link>
            {contact.title ? (
              <span className="block truncate text-[13px] text-muted-foreground">
                {contact.title}
              </span>
            ) : null}
          </span>
        </span>
      );
    },
  },
  {
    key: 'account',
    header: 'Account',
    width: '24%',
    cell: (contact) => (
      <span className="block truncate text-secondary-foreground">
        {contact.account_name ?? '—'}
      </span>
    ),
  },
  {
    key: 'email',
    header: 'Email',
    width: '26%',
    dropAt: 900,
    cell: (contact) => (
      <span className="block truncate text-secondary-foreground" title={contact.email ?? undefined}>
        {contact.email ?? '—'}
      </span>
    ),
  },
  {
    key: 'phone',
    header: 'Phone',
    width: '12%',
    dropAt: 1100,
    cell: (contact) => (
      <span className="block truncate tabular text-secondary-foreground">
        {contact.phone ?? '—'}
      </span>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    width: '8%',
    cell: (contact) => <span className="text-muted-foreground">{contact.status}</span>,
  },
];

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
    <div className="space-y-5">
      <PageHeader
        title="Contacts"
        description="Only your organisation’s records are visible here."
        actions={<NewContactForm accounts={accounts} />}
      />

      {/* A real search, backed by a real server-side query. The one place in the
          product where a search box exists, because it is the one place with an
          endpoint behind it. */}
      <form method="get" role="search" className="flex flex-wrap items-center gap-2">
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
          className={`${controlClass(false)} max-w-sm`}
        />
        <Button variant="secondary" type="submit">
          Search
        </Button>
        {search ? (
          <Link
            href="/contacts"
            className="text-[13px] text-accent underline-offset-2 hover:underline"
          >
            Clear
          </Link>
        ) : null}
      </form>

      {!result.ok ? (
        <p
          role="alert"
          className="max-w-reading rounded border border-critical/40 bg-critical-soft px-3 py-2 text-sm text-critical"
        >
          {result.error ?? 'Could not load contacts.'}
        </p>
      ) : null}

      <section aria-labelledby="contact-list-heading">
        <h2 id="contact-list-heading" className="sr-only">
          Contact list
        </h2>
        <DataTable
          caption="Contacts for your organisation"
          columns={COLUMNS}
          rows={contacts}
          rowKey={(contact) => contact.id}
          bodyTestId="contact-rows"
          empty={
            <TableEmpty
              data-testid="contacts-empty"
              title={search ? 'Nothing matches that search' : 'No contacts yet'}
              description={
                search
                  ? `No contacts match “${search}”. Try a phone number or part of a company name.`
                  : 'A contact is a named person at an account. Create one, or convert a prospect.'
              }
            />
          }
        />
      </section>
    </div>
  );
}
