import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewLeadForm } from '@/features/leads/new-lead-form';

export const dynamic = 'force-dynamic';

interface Lead {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly phone: string | null;
  readonly status: string;
  readonly source: string;
}

export default async function LeadsPage(): Promise<JSX.Element> {
  const result = await apiFetch<{ leads: Lead[] }>('/leads?page_size=50');
  const leads = result.data?.leads ?? [];

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold">Leads</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Only your organisation&rsquo;s records are visible here.
        </p>
      </section>

      <NewLeadForm />

      <section aria-labelledby="lead-list-heading">
        <h2 id="lead-list-heading" className="sr-only">
          Lead list
        </h2>

        {leads.length === 0 ? (
          <p data-testid="empty-state" className="rounded border border-dashed p-6 text-sm text-muted-foreground">
            No leads yet. Create one above.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Leads for your organisation</caption>
            <thead>
              <tr className="border-b">
                <th scope="col" className="py-2">Name</th>
                <th scope="col" className="py-2">Email</th>
                <th scope="col" className="py-2">Source</th>
                <th scope="col" className="py-2">Status</th>
              </tr>
            </thead>
            <tbody data-testid="lead-rows">
              {leads.map((lead) => (
                <tr key={lead.id} className="border-b">
                  <td className="py-2">
                    <Link
                      href={`/leads/${lead.id}`}
                      data-testid={`lead-link-${lead.id}`}
                      className="underline"
                    >
                      {lead.first_name} {lead.last_name ?? ''}
                    </Link>
                  </td>
                  <td className="py-2">{lead.email ?? '\u2014'}</td>
                  <td className="py-2">{lead.source}</td>
                  <td className="py-2">{lead.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
