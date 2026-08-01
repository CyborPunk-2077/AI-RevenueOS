import Link from 'next/link';
import { notFound } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { EditContactForm } from '@/features/crm/edit-contact-form';
import { Timeline, type TimelineEntry } from '@/features/crm/timeline';
import type { AccountOption } from '@/features/crm/new-contact-form';

export const dynamic = 'force-dynamic';

interface Contact {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly phone: string | null;
  readonly company: string | null;
  readonly title: string | null;
  readonly status: string;
  readonly account_id: string | null;
  readonly account_name: string | null;
  readonly version: number;
  readonly created_at: string | null;
}

export default async function ContactDetailPage({
  params,
}: {
  params: { contactId: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<Contact>(`/contacts/${params.contactId}`);
  // A record belonging to another tenant is a 404 here, exactly as the API
  // reports it -- the UI must not hint that the id exists somewhere else.
  if (!result.ok || !result.data) notFound();
  const contact = result.data;

  const [accountResult, timelineResult] = await Promise.all([
    apiFetch<{ accounts: AccountOption[] }>('/accounts?page_size=200'),
    apiFetch<{ timeline: TimelineEntry[] }>(`/contacts/${params.contactId}/timeline`),
  ]);
  const accounts = accountResult.data?.accounts ?? [];
  const timeline = timelineResult.data?.timeline ?? [];

  return (
    <div className="space-y-8">
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/contacts" className="underline">
          Contacts
        </Link>
      </nav>

      <section>
        <h1 className="text-xl font-semibold" data-testid="contact-name">
          {contact.first_name} {contact.last_name ?? ''}
        </h1>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">Email</dt>
            <dd>{contact.email ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Phone</dt>
            <dd>{contact.phone ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Job title</dt>
            <dd>{contact.title ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Company</dt>
            <dd>{contact.company ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Account</dt>
            <dd data-testid="contact-account-name">
              {contact.account_id && contact.account_name ? (
                <Link href={`/accounts/${contact.account_id}`} className="underline">
                  {contact.account_name}
                </Link>
              ) : (
                '—'
              )}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Status</dt>
            <dd data-testid="contact-status">{contact.status}</dd>
          </div>
        </dl>
      </section>

      <EditContactForm contact={contact} accounts={accounts} />

      <Timeline parent="contacts" parentId={contact.id} entries={timeline} />
    </div>
  );
}
