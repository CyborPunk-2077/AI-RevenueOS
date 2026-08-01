import Link from 'next/link';
import { notFound } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { Timeline, type TimelineEntry } from '@/features/crm/timeline';

export const dynamic = 'force-dynamic';

interface Account {
  readonly id: string;
  readonly name: string;
  readonly industry: string | null;
  readonly website: string | null;
  readonly phone: string | null;
  readonly employee_count: number | null;
  readonly contact_count: number | null;
  readonly version: number;
}

interface LinkedContact {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly title: string | null;
}

export default async function AccountDetailPage({
  params,
}: {
  params: { accountId: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<Account>(`/accounts/${params.accountId}`);
  if (!result.ok || !result.data) notFound();
  const account = result.data;

  const [linked, timelineResult] = await Promise.all([
    apiFetch<{ contacts: LinkedContact[] }>(`/accounts/${params.accountId}/contacts`),
    apiFetch<{ timeline: TimelineEntry[] }>(`/accounts/${params.accountId}/timeline`),
  ]);
  const contacts = linked.data?.contacts ?? [];
  const timeline = timelineResult.data?.timeline ?? [];

  return (
    <div className="space-y-8">
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/accounts" className="underline">
          Accounts
        </Link>
      </nav>

      <section>
        <h1 className="text-xl font-semibold" data-testid="account-name">
          {account.name}
        </h1>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">Industry</dt>
            <dd>{account.industry ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Website</dt>
            <dd>{account.website ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Phone</dt>
            <dd>{account.phone ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Employees</dt>
            <dd>{account.employee_count ?? '—'}</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="linked-contacts-heading">
        <h2 id="linked-contacts-heading" className="font-medium">
          Contacts at this account
        </h2>

        {contacts.length === 0 ? (
          <p
            data-testid="account-contacts-empty"
            className="mt-3 rounded border border-dashed p-6 text-sm text-muted-foreground"
          >
            No contacts are linked yet. Open a contact and choose this account.
          </p>
        ) : (
          <ul className="mt-3 divide-y" data-testid="account-contact-rows">
            {contacts.map((contact) => (
              <li key={contact.id} className="py-2 text-sm">
                <Link href={`/contacts/${contact.id}`} className="underline">
                  {contact.first_name} {contact.last_name ?? ''}
                </Link>
                <span className="ml-2 text-muted-foreground">
                  {contact.title ?? contact.email ?? ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    <Timeline parent="accounts" parentId={account.id} entries={timeline} />
    </div>
  );
}
