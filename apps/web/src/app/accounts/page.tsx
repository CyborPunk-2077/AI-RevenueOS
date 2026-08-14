import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewAccountForm } from '@/features/crm/new-account-form';
import { Avatar } from '@/features/ui/avatar';
import { Button, controlClass } from '@/features/ui/controls';
import { DataTable, TableEmpty, type Column } from '@/features/ui/data-table';
import { PageHeader } from '@/features/ui/primitives';

export const dynamic = 'force-dynamic';

interface Account {
  readonly id: string;
  readonly name: string;
  readonly industry: string | null;
  readonly website: string | null;
  readonly contact_count: number | null;
}

const COLUMNS: Array<Column<Account>> = [
  {
    key: 'name',
    header: 'Account',
    width: '42%',
    cell: (account) => (
      <span className="flex items-center gap-2">
        <Avatar name={account.name} />
        <Link
          href={`/accounts/${account.id}`}
          data-testid={`account-link-${account.id}`}
          title={account.name}
          className="truncate font-medium text-foreground underline-offset-2 hover:underline"
        >
          {account.name}
        </Link>
      </span>
    ),
  },
  {
    key: 'industry',
    header: 'Industry',
    width: '26%',
    cell: (account) => (
      <span className="block truncate text-secondary-foreground">{account.industry ?? '—'}</span>
    ),
  },
  {
    key: 'website',
    header: 'Website',
    width: '20%',
    dropAt: 900,
    cell: (account) => (
      <span className="block truncate text-muted-foreground" title={account.website ?? undefined}>
        {account.website ?? '—'}
      </span>
    ),
  },
  {
    key: 'contacts',
    header: 'Contacts',
    align: 'right',
    width: '12%',
    cell: (account) => (
      <span className="text-secondary-foreground">{account.contact_count ?? 0}</span>
    ),
  },
];

export default async function AccountsPage({
  searchParams,
}: {
  searchParams?: { search?: string };
}): Promise<JSX.Element> {
  const search = (searchParams?.search ?? '').trim();
  const query = search ? `&search=${encodeURIComponent(search)}` : '';
  const result = await apiFetch<{ accounts: Account[] }>(`/accounts?page_size=50${query}`);
  const accounts = result.data?.accounts ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Accounts"
        description="Companies you work with. Contacts can be linked to one."
        actions={<NewAccountForm />}
      />

      <form method="get" role="search" className="flex flex-wrap items-center gap-2">
        <label htmlFor="account_search" className="sr-only">
          Search accounts
        </label>
        <input
          id="account_search"
          name="search"
          type="search"
          defaultValue={search}
          placeholder="Name or industry"
          data-testid="account-search"
          className={`${controlClass(false)} max-w-sm`}
        />
        <Button variant="secondary" type="submit">
          Search
        </Button>
        {search ? (
          <Link
            href="/accounts"
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
          {result.error ?? 'Could not load accounts.'}
        </p>
      ) : null}

      <section aria-labelledby="account-list-heading">
        <h2 id="account-list-heading" className="sr-only">
          Account list
        </h2>
        <DataTable
          caption="Accounts for your organisation"
          columns={COLUMNS}
          rows={accounts}
          rowKey={(account) => account.id}
          bodyTestId="account-rows"
          empty={
            <TableEmpty
              data-testid="accounts-empty"
              title={search ? 'Nothing matches that search' : 'No accounts yet'}
              description={
                search
                  ? `No accounts match “${search}”. Try part of the company name or its industry.`
                  : 'An account is a company. Create one, or it appears when a prospect converts.'
              }
            />
          }
        />
      </section>
    </div>
  );
}
