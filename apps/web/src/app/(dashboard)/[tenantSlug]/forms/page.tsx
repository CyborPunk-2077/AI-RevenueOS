import { apiFetch } from '@/lib/session';
import { PageHeader } from '@/features/ui/primitives';
import { FormList, type CaptureForm } from '@/features/forms/form-builder';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Capture forms' };

export default async function FormsPage({
  params,
}: {
  params: { tenantSlug: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<{ items: CaptureForm[] }>('/forms');
  const forms = result.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Capture forms"
        description="A form collects leads from your website. Editing a draft never changes what is live until you publish."
      />
      <FormList forms={forms} tenantSlug={params.tenantSlug} />
    </div>
  );
}
