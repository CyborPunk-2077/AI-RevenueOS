'use client';

import { useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Card, EmptyState, PageHeader, StatusPill } from '@/features/ui/primitives';

/**
 * CSV import: upload, confirm the mapping, review, commit.
 *
 * Three decisions the UI has to honour, because the server already does:
 *
 * **The preview is the commit, minus the writing.** Both call the same planner
 * with the same inputs, so what is shown here is exactly what will happen. That
 * is only true if the same file and mapping are sent to both, which is why the
 * File object is held rather than re-read.
 *
 * **Rejections are shown per row, not summarised.** "352 rows rejected" tells a
 * user nothing actionable. "Row 47: duplicate of row 12 in this file" tells them
 * what to fix. Burying that behind a count is how people import 1,600 rows and
 * never learn why 352 vanished.
 *
 * **The import key is generated once, when the file is chosen.** It rides along
 * with the commit, so a double-clicked button, an impatient retry, or a
 * connection that drops after the server committed all replay to the same
 * result instead of importing twice.
 */

interface Rejection {
  readonly row: number;
  readonly reasons: string[];
}

interface Preview {
  readonly headers: string[];
  readonly suggested_mapping: Record<string, string | null>;
  readonly mapping: Record<string, string>;
  readonly total_rows: number;
  readonly accepted: number;
  readonly rejected: number;
  readonly rejections: Rejection[];
  readonly already_in_crm: string[];
  readonly sample: { row: number; values: Record<string, string> }[];
}

interface Committed {
  readonly batch_id: string;
  readonly created_ids: string[];
  readonly accepted: number;
  readonly rejected: number;
  readonly rejections: Rejection[];
}

/** Fields the server will accept a column mapped to. */
const TARGETS = [
  '',
  'first_name',
  'last_name',
  'email',
  'phone',
  'company',
  'title',
  'city',
  'source',
  'notes',
] as const;

type Step = 'upload' | 'mapping' | 'result';

export function ImportWizard(): JSX.Element {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [importKey, setImportKey] = useState('');
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [committed, setCommitted] = useState<Committed | null>(null);
  const [assign, setAssign] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const step: Step = committed ? 'result' : preview ? 'mapping' : 'upload';

  const mappedTargets = useMemo(
    () => new Set(Object.values(mapping).filter(Boolean)),
    [mapping],
  );
  const contactable = mappedTargets.has('email') || mappedTargets.has('phone');
  const named = mappedTargets.has('first_name');

  function body(withKey: boolean): FormData {
    const form = new FormData();
    if (file) form.append('file', file);
    form.append('mapping', JSON.stringify(mapping));
    if (withKey) {
      form.append('import_key', importKey);
      form.append('assign', String(assign));
    }
    return form;
  }

  async function choose(chosen: File): Promise<void> {
    setBusy(true);
    setError(null);
    setFile(chosen);
    // One key per chosen file, so re-picking the same file starts a new import
    // but retrying a failed submit does not.
    setImportKey(`csv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`);

    const form = new FormData();
    form.append('file', chosen);

    const response = await fetch('/api/imports/leads/preview', { method: 'POST', body: form });
    if (!response.ok) {
      setError(await message(response, 'That file could not be read.'));
      setFile(null);
      setBusy(false);
      return;
    }

    const payload = (await response.json()) as { data: Preview };
    setPreview(payload.data);
    setMapping(payload.data.mapping);
    setBusy(false);
  }

  async function reprice(next: Record<string, string>): Promise<void> {
    setMapping(next);
    if (!file) return;
    setBusy(true);
    setError(null);

    const form = new FormData();
    form.append('file', file);
    form.append('mapping', JSON.stringify(next));

    const response = await fetch('/api/imports/leads/preview', { method: 'POST', body: form });
    if (!response.ok) {
      setError(await message(response, 'That mapping is not usable.'));
      setBusy(false);
      return;
    }
    const payload = (await response.json()) as { data: Preview };
    setPreview(payload.data);
    setBusy(false);
  }

  async function commit(): Promise<void> {
    if (!file || busy) return;
    setBusy(true);
    setError(null);

    const response = await fetch('/api/imports/leads', { method: 'POST', body: body(true) });
    if (!response.ok) {
      setError(await message(response, 'That import could not be committed.'));
      setBusy(false);
      return;
    }

    const payload = (await response.json()) as { data: Committed };
    setCommitted(payload.data);
    setBusy(false);
    router.refresh();
  }

  function restart(): void {
    setFile(null);
    setPreview(null);
    setCommitted(null);
    setMapping({});
    setError(null);
    if (fileRef.current) fileRef.current.value = '';
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Import leads"
        description="Nothing is written until you review what the file contains and confirm."
      />

      <Steps current={step} />

      {error ? (
        <p role="alert" className="rounded border border-destructive/40 bg-destructive-soft p-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {step === 'upload' ? (
        <Card>
          <label htmlFor="csv" className="block text-sm font-medium">
            CSV file
          </label>
          <p id="csv-help" className="mt-1 text-xs text-muted-foreground">
            Up to 10,000 rows and 5 MB. The first row must be the column headers. UTF-8 or
            Windows-1252, which is what Excel writes by default.
          </p>
          <input
            ref={fileRef}
            id="csv"
            type="file"
            accept=".csv,text/csv"
            aria-describedby="csv-help"
            disabled={busy}
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              if (chosen) void choose(chosen);
            }}
            className="field mt-3 block"
          />
          {busy ? (
            <p role="status" className="mt-3 text-sm text-muted-foreground">
              Reading the file…
            </p>
          ) : null}
        </Card>
      ) : null}

      {step === 'mapping' && preview ? (
        <>
          <Card>
            <h2 className="heading text-base">Columns</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              We matched these from your headers. Change anything we got wrong. Columns left
              unmapped are kept on the lead as captured data rather than discarded.
            </p>

            <table className="mt-4 w-full text-left text-sm">
              <caption className="sr-only">Column mapping</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                  <th scope="col" className="py-2">
                    Your column
                  </th>
                  <th scope="col" className="py-2">
                    Imports as
                  </th>
                </tr>
              </thead>
              <tbody>
                {preview.headers.map((header) => (
                  <tr key={header} className="border-b border-border/60">
                    <td className="py-2 font-mono text-xs">{header}</td>
                    <td className="py-2">
                      <label htmlFor={`map-${header}`} className="sr-only">
                        Field for column {header}
                      </label>
                      <select
                        id={`map-${header}`}
                        value={mapping[header] ?? ''}
                        disabled={busy}
                        onChange={(event) => {
                          const next = { ...mapping };
                          if (event.target.value) next[header] = event.target.value;
                          else delete next[header];
                          void reprice(next);
                        }}
                        className="field w-auto py-1"
                      >
                        {TARGETS.map((target) => (
                          <option key={target} value={target}>
                            {target === '' ? 'Keep as captured data' : target}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {!named || !contactable ? (
              <p role="alert" className="mt-3 text-sm text-destructive">
                {!named ? 'Map a column to first_name. ' : ''}
                {!contactable
                  ? 'Map a column to email or phone, or the leads created cannot be contacted.'
                  : ''}
              </p>
            ) : null}
          </Card>

          <ReviewPanel preview={preview} />

          <Card>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={assign}
                onChange={(event) => setAssign(event.target.checked)}
              />
              Run assignment rules on the imported leads
            </label>

            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void commit()}
                disabled={busy || preview.accepted === 0 || !named || !contactable}
                className="btn btn-primary"
              >
                {busy ? 'Importing…' : `Import ${preview.accepted} leads`}
              </button>
              <button
                type="button"
                onClick={restart}
                className="btn btn-ghost"
              >
                Choose a different file
              </button>
            </div>
          </Card>
        </>
      ) : null}

      {step === 'result' && committed ? (
        <>
          <Card>
            <h2 className="heading text-base">Import complete</h2>
            <p className="mt-2 text-sm">
              <StatusPill tone="success">{committed.accepted} imported</StatusPill>{' '}
              {committed.rejected > 0 ? (
                <StatusPill tone="warning">{committed.rejected} skipped</StatusPill>
              ) : null}
            </p>
            <p className="mt-3 text-xs text-muted-foreground">Batch {committed.batch_id}</p>
            <div className="mt-4 flex gap-3">
              <a
                href="/leads"
                className="btn btn-primary"
              >
                View leads
              </a>
              <button
                type="button"
                onClick={restart}
                className="btn btn-ghost"
              >
                Import another file
              </button>
            </div>
          </Card>

          {committed.rejections.length > 0 ? (
            <RejectionTable rejections={committed.rejections} total={committed.rejected} />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function Steps({ current }: { current: Step }): JSX.Element {
  const steps: { key: Step; label: string }[] = [
    { key: 'upload', label: 'Choose file' },
    { key: 'mapping', label: 'Confirm columns' },
    { key: 'result', label: 'Done' },
  ];
  const index = steps.findIndex((s) => s.key === current);

  return (
    <ol className="flex flex-wrap gap-2 text-sm">
      {steps.map((step, position) => (
        <li key={step.key} className="flex items-center gap-2">
          <span
            className="step-dot"
            data-state={position === index ? 'current' : position < index ? 'done' : 'todo'}
            aria-hidden="true"
          >
            {position < index ? '\u2713' : position + 1}
          </span>
          <span
            aria-current={position === index ? 'step' : undefined}
            className={position === index ? 'font-medium' : 'text-muted-foreground'}
          >
            {step.label}
            {position < index ? <span className="sr-only"> (completed)</span> : null}
          </span>
          {position < steps.length - 1 ? (
            <span aria-hidden="true" className="mx-1 h-px w-6 bg-border" />
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function ReviewPanel({ preview }: { preview: Preview }): JSX.Element {
  return (
    <>
      <Card>
        <h2 className="heading text-base">What will happen</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          <StatusPill tone="success">{preview.accepted} will be imported</StatusPill>
          {preview.rejected > 0 ? (
            <StatusPill tone="warning">{preview.rejected} will be skipped</StatusPill>
          ) : null}
          {preview.already_in_crm.length > 0 ? (
            <StatusPill tone="neutral">
              {preview.already_in_crm.length} already in your CRM
            </StatusPill>
          ) : null}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          {preview.total_rows} rows read.{' '}
          {preview.already_in_crm.length > 0
            ? 'Addresses already in the CRM are still imported: a newer row for an existing person is normal.'
            : ''}
        </p>
      </Card>

      {preview.rejected > 0 ? (
        <RejectionTable rejections={preview.rejections} total={preview.rejected} />
      ) : null}
    </>
  );
}

/**
 * Every rejection, with its row number and reason. The server caps the list at
 * 100; say so rather than letting the count and the table disagree.
 */
function RejectionTable({
  rejections,
  total,
}: {
  rejections: Rejection[];
  total: number;
}): JSX.Element {
  if (rejections.length === 0) {
    return (
      <EmptyState title="Nothing skipped" description="Every row in the file can be imported." />
    );
  }

  return (
    <Card>
      <h2 className="heading text-base">Rows that will not be imported</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Fix these in the file and import again, or import without them.
      </p>

      <table className="mt-4 w-full text-left text-sm">
        <caption className="sr-only">Rejected rows and the reason for each</caption>
        <thead>
          <tr className="border-b border-border text-xs uppercase text-muted-foreground">
            <th scope="col" className="w-20 py-2">
              Row
            </th>
            <th scope="col" className="py-2">
              Why
            </th>
          </tr>
        </thead>
        <tbody className="stagger">
          {rejections.map((rejection) => (
            <tr key={rejection.row} className="border-b border-border/60 align-top">
              <th scope="row" className="py-2 font-normal tabular">
                {rejection.row}
              </th>
              <td className="py-2">
                <ul className="list-inside list-disc">
                  {rejection.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {total > rejections.length ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Showing the first {rejections.length} of {total}.
        </p>
      ) : null}
    </Card>
  );
}

async function message(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => ({}))) as {
    error?: { message?: string; details?: { problems?: string[] } };
  };
  const problems = payload.error?.details?.problems;
  if (problems?.length) return problems.join(' ');
  return payload.error?.message ?? fallback;
}
