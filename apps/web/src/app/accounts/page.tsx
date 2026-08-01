import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewAccountForm } from '@/features/crm/new-account-form';

export const dynamic = 'force-dynamic';

interface Account {
  readonly id: string;
  readonly name: string;
  readonly industry: string | null;
  readonly website: string | null;
  readonly contact_count: number | null;
}

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
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold">Accounts</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Companies you work with. Contacts can be linked to one.
        </p>
      </section>

      <form method="get" role="search" className="flex gap-2">
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
          className="w-full max-w-sm rounded border px-3 py-2"
        />
        <button type="submit" className="rounded border px-4 py-2">
          Search
        </button>
        {search ? (
          <Link href="/accounts" className="rounded border px-4 py-2">
            Clear
          </Link>
        ) : null}
      </form>

      <NewAccountForm />

      {!result.ok ? (
        <p role="alert" className="rounded border border-destructive p-4 text-sm text-destructive">
          {result.error ?? 'Could not load accounts.'}
        </p>
      ) : null}

      <section aria-labelledby="account-list-heading">
        <h2 id="account-list-heading" className="sr-only">
          Account list
        </h2>

        {accounts.length === 0 ? (
          <p
            data-testid="accounts-empty"
            className="rounded border border-dashed p-6 text-sm text-muted-foreground"
          >
            {search ? `No accounts match “${search}”.` : 'No accounts yet. Create one above.'}
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Accounts for your organisation</caption>
            <thead>
              <tr className="border-b">
                <th scope="col" className="py-2">
                  Name
                </th>
                <th scope="col" className="py-2">
                  Industry
                </th>
                <th scope="col" className="py-2">
                  Contacts
                </th>
              </tr>
            </thead>
            <tbody data-testid="account-rows">
              {accounts.map((account) => (
                <tr key={account.id} className="border-b">
                  <td className="py-2">
                    <Link
                      href={`/accounts/${account.id}`}
                      data-testid={`account-link-${account.id}`}
                      className="underline"
                    >
                      {account.name}
                    </Link>
                  </td>
                  <td className="py-2">{account.industry ?? '—'}</td>
                  <td className="py-2">{account.contact_count ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
