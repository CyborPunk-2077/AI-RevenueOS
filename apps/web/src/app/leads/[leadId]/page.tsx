import { notFound } from 'next/navigation';
import Link from 'next/link';
import { apiFetch } from '@/lib/session';
import { EditLeadForm } from '@/features/leads/edit-lead-form';
import { DuplicateReview, type Candidate } from '@/features/leads/duplicate-review';

export const dynamic = 'force-dynamic';

interface Lead {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly phone: string | null;
  readonly status: string;
  readonly source: string;
  readonly version: number;
  readonly qualification_score: number | null;
  readonly category: string | null;
}

export default async function LeadDetailPage({
  params,
}: {
  params: { leadId: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<Lead>(`/leads/${params.leadId}`);

  // A record belonging to another tenant is indistinguishable from one that does
  // not exist -- the server decides, not the page.
  if (!result.ok || !result.data) notFound();
  const lead = result.data;

  // Recorded candidates, not a fresh scan: scanning on every page view would run
  // a 500-row comparison for a screen nobody asked to deduplicate. The button in
  // the panel triggers the scan.
  const duplicates = await apiFetch<{ candidates: Candidate[] }>(
    `/leads/${params.leadId}/duplicates`,
  );

  return (
    <div className="space-y-6">
      <Link href="/leads" className="text-sm underline">
        &larr; All leads
      </Link>

      <header>
        <h1 data-testid="lead-name" className="text-xl font-semibold">
          {lead.first_name} {lead.last_name ?? ''}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {lead.status} &middot; source {lead.source} &middot; version {lead.version}
        </p>
      </header>

      <dl className="grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-muted-foreground">Email</dt>
          <dd data-testid="lead-email">{lead.email ?? '\u2014'}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Phone</dt>
          <dd>{lead.phone ?? '\u2014'}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Qualification</dt>
          <dd>
            {lead.qualification_score === null
              ? 'Not scored'
              : `${lead.qualification_score} (${lead.category ?? 'n/a'})`}
          </dd>
        </div>
      </dl>

      <EditLeadForm lead={lead} />

      <DuplicateReview lead={lead} candidates={duplicates.data?.candidates ?? []} />
    </div>
  );
}
