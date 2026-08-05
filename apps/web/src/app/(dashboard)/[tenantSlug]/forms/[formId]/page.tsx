import { notFound } from 'next/navigation';
import { apiFetch } from '@/lib/session';
import { PageHeader } from '@/features/ui/primitives';
import { FormBuilder, type CaptureForm } from '@/features/forms/form-builder';

export const dynamic = 'force-dynamic';

export default async function FormPage({
  params,
}: {
  params: { formId: string };
}): Promise<JSX.Element> {
  const result = await apiFetch<CaptureForm>(`/forms/${params.formId}`);
  if (!result.ok || !result.data) notFound();

  return (
    <div className="space-y-6">
      <PageHeader title={result.data.name} description="Draft and published are separate." />
      <FormBuilder form={result.data} />
    </div>
  );
}
