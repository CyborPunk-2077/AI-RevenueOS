import { ImportWizard } from '@/features/imports/import-wizard';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Import leads' };

export default function ImportsPage(): JSX.Element {
  return <ImportWizard />;
}
