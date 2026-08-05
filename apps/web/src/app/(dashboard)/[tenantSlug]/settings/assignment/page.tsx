import { apiFetch } from '@/lib/session';
import { PageHeader } from '@/features/ui/primitives';
import { AssignmentRules, type AssignmentRule } from '@/features/leads/assignment-rules';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Assignment rules' };

export default async function AssignmentPage(): Promise<JSX.Element> {
  const result = await apiFetch<{ items: AssignmentRule[] }>('/assignment-rules');
  const rules = result.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Assignment rules"
        description="Who gets a new lead, and in what order the rules are tried."
      />
      <AssignmentRules rules={rules} />
    </div>
  );
}
