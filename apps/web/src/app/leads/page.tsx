import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { NewLeadForm } from '@/features/leads/new-lead-form';
import { Card, EmptyState, PageHeader, StatusPill } from '@/features/ui/primitives';

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
      <PageHeader
        title="Leads"
        description="Only your organisation&rsquo;s records are visible here."
      />

      <NewLeadForm />

      <section aria-labelledby="lead-list-heading">
        <h2 id="lead-list-heading" className="sr-only">
          Lead list
        </h2>

        {leads.length === 0 ? (
          <div data-testid="empty-state">
            <EmptyState
              title="No leads yet"
              description="Create one above, import a CSV, or publish a capture form and they will arrive here."
            />
          </div>
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Leads for your organisation</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th scope="col" className="px-5 py-3">
                    Name
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Email
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Source
                  </th>
                  <th scope="col" className="px-5 py-3">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody data-testid="lead-rows">
                {leads.map((lead) => (
                  <tr
                    key={lead.id}
                    className="border-b border-border/60 transition-colors hover:bg-surface-sunken"
                  >
                    <td className="px-5 py-3">
                      <Link
                        href={`/leads/${lead.id}`}
                        data-testid={`lead-link-${lead.id}`}
                        className="font-medium text-primary underline-offset-2 hover:underline"
                      >
                        {lead.first_name} {lead.last_name ?? ''}
                      </Link>
                    </td>
                    <td className="px-5 py-3">{lead.email ?? '\u2014'}</td>
                    <td className="px-5 py-3">{lead.source}</td>
                    <td className="px-5 py-3">
                      <StatusPill tone={lead.status === 'converted' ? 'success' : 'neutral'}>
                        {lead.status}
                      </StatusPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}
