'use client';

import { useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Button, Checkbox, controlClass } from '@/features/ui/controls';
import { DataTable, type Column } from '@/features/ui/data-table';
import { PageHeader, SectionHeader } from '@/features/ui/primitives';
import { mutate } from '@/lib/csrf';

/**
 * CSV import: upload, review, confirm.
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
 *
 * The redesign deliberately changed the presentation only. This flow was already
 * the right shape and its safety model - nothing is written before the confirm -
 * is the most valuable thing on the screen.
 */

interface Rejection {
  readonly row: number;
  readonly reasons: string[];
}

interface DuplicateMatch {
  readonly row: number;
  readonly incoming: string;
  readonly lead_id: string;
  readonly name: string;
  readonly matched_on: string;
  readonly evidence: string;
  readonly status: string;
}

interface SampleRow {
  readonly row: number;
  readonly values: Record<string, string>;
  readonly normalized: Record<string, string | null>;
}

interface Preview {
  readonly headers: string[];
  readonly suggested_mapping: Record<string, string | null>;
  readonly mapping: Record<string, string>;
  readonly total_rows: number;
  readonly accepted: number;
  readonly rejected: number;
  readonly rejections: Rejection[];
  readonly duplicates: DuplicateMatch[];
  readonly will_create: number;
  readonly sample: SampleRow[];
}

interface Committed {
  readonly batch_id: string;
  readonly created_ids: string[];
  readonly created: number;
  readonly accepted: number;
  readonly rejected: number;
  readonly rejections: Rejection[];
  readonly duplicates: DuplicateMatch[];
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
  'website',
  'industry',
  'requirement',
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

  const mappedTargets = useMemo(() => new Set(Object.values(mapping).filter(Boolean)), [mapping]);
  const contactable = mappedTargets.has('email') || mappedTargets.has('phone');
  const named = mappedTargets.has('first_name') || mappedTargets.has('company');

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

    const response = await mutate('/api/imports/leads/preview', { method: 'POST', body: form });
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

    const response = await mutate('/api/imports/leads/preview', { method: 'POST', body: form });
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

    const response = await mutate('/api/imports/leads', { method: 'POST', body: body(true) });
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
        title="Import a prospect list"
        description="Nothing is written until you review what the file contains and confirm."
      />

      <Steps current={step} />

      {error ? (
        <p
          role="alert"
          className="max-w-reading rounded border border-critical/40 bg-critical-soft px-3 py-2 text-[13px] text-critical"
        >
          {error}
        </p>
      ) : null}

      {step === 'upload' ? (
        <div className="max-w-reading space-y-6">
          <div>
            <label htmlFor="csv" className="block text-[13px] font-medium text-foreground">
              CSV file
            </label>
            <p id="csv-help" className="mt-1 text-[13px] text-muted-foreground">
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
              className={`${controlClass(false)} mt-2 py-1.5`}
            />
            {busy ? (
              <p role="status" className="mt-2 text-[13px] text-muted-foreground">
                Reading the file…
              </p>
            ) : null}
          </div>

          {/* Offered before the upload, not buried in documentation. The columns
              are the words a founder would use, and the file maps itself. */}
          <div className="space-y-3 border-t border-border pt-5">
            <SectionHeader
              title="Not sure what the file should look like?"
              description="Download the template, replace the three example businesses with your own, and upload it. Columns you do not have can be left empty or deleted."
            />
            <a
              href="/api/imports/leads/template"
              download="sangam-prospect-template.csv"
              data-testid="download-template"
              className="btn btn-ghost inline-flex"
            >
              Download the template
            </a>
          </div>
        </div>
      ) : null}

      {step === 'mapping' && preview ? (
        <div className="space-y-8">
          <section className="space-y-3">
            <SectionHeader
              title="Columns"
              description="We matched these from your headers. Change anything we got wrong. Columns left unmapped are kept on the lead as captured data rather than discarded."
            />

            <div className="max-w-2xl overflow-hidden rounded-lg border border-border bg-surface">
              <table className="w-full border-collapse text-left">
                <caption className="sr-only">Column mapping</caption>
                <thead>
                  <tr className="border-b border-border-strong bg-surface-sunken">
                    <th
                      scope="col"
                      className="px-4 py-2 text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground"
                    >
                      Your column
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-2 text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground"
                    >
                      Imports as
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {preview.headers.map((header) => (
                    <tr key={header} className="border-b border-border last:border-b-0">
                      <td className="px-4 py-1.5 font-mono text-[13px] text-secondary-foreground">
                        {header}
                      </td>
                      <td className="px-4 py-1.5">
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
                          className={`${controlClass(false)} w-auto`}
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
            </div>

            {!named || !contactable ? (
              <p role="alert" className="max-w-reading text-[13px] text-critical">
                {!named ? 'Map a column to the business name or the contact person. ' : ''}
                {!contactable
                  ? 'Map a column to email or phone, or the leads created cannot be contacted.'
                  : ''}
              </p>
            ) : null}
          </section>

          <ReviewPanel preview={preview} />

          {/*
            The confirmation. It states exactly what it will do, because this is
            the only click in the whole flow that writes anything - and until it
            is pressed, the screen has been promising that nothing has.
          */}
          <section className="space-y-3 border-t border-border pt-6">
            <Checkbox
              id="assign-rules"
              checked={assign}
              onChange={(event) => setAssign(event.target.checked)}
              label="Share the new businesses out using the assignment rules"
            />

            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                data-testid="commit-import"
                onClick={() => void commit()}
                disabled={busy || preview.will_create === 0 || !named || !contactable}
              >
                {busy
                  ? 'Importing…'
                  : `Import ${preview.will_create} ${preview.will_create === 1 ? 'business' : 'businesses'}`}
              </Button>
              <Button variant="ghost" onClick={restart}>
                Choose a different file
              </Button>
              <p className="text-[13px] text-muted-foreground">Nothing has been written yet.</p>
            </div>
          </section>
        </div>
      ) : null}

      {step === 'result' && committed ? (
        <div className="space-y-8">
          <section className="space-y-3">
            <SectionHeader title="Import complete" />
            <Counts
              testId="import-summary"
              items={[
                { key: 'added', value: committed.created, label: 'added' },
                ...(committed.duplicates.length > 0
                  ? [{ key: 'had', value: committed.duplicates.length, label: 'already had' }]
                  : []),
                ...(committed.rejected > 0
                  ? [{ key: 'unusable', value: committed.rejected, label: 'unusable' }]
                  : []),
              ]}
            />
            <p className="text-[13px] text-muted-foreground">Batch {committed.batch_id}</p>
            <div className="flex flex-wrap gap-3">
              <a href="/leads" className="btn btn-primary inline-flex">
                See the prospects
              </a>
              <Button variant="ghost" onClick={restart}>
                Import another file
              </Button>
            </div>
          </section>

          {committed.duplicates.length > 0 ? (
            <DuplicateTable duplicates={committed.duplicates} />
          ) : null}

          {committed.rejections.length > 0 ? (
            <RejectionTable rejections={committed.rejections} total={committed.rejected} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The counts, as figures with words beside them rather than as coloured pills.
 *
 * The wording is load-bearing. "24 added / 3 already had / 1 unusable" is what a
 * founder reads after an import, and the browser suite asserts on those exact
 * phrases - so this renders them as one string per figure rather than as a
 * number and a label that a screen reader would have to reassemble.
 */
function Counts({
  items,
  testId,
}: {
  items: Array<{ key: string; value: number; label: string }>;
  testId: string;
}): JSX.Element {
  return (
    <p className="flex flex-wrap items-baseline gap-x-8 gap-y-2" data-testid={testId}>
      {items.map((item) => (
        <span key={item.key} className="text-lg font-semibold tabular text-foreground">
          {item.value}{' '}
          <span className="text-sm font-normal text-muted-foreground">{item.label}</span>
        </span>
      ))}
    </p>
  );
}

function Steps({ current }: { current: Step }): JSX.Element {
  // Upload → Review → Confirm: the three words the safety model is built on.
  const steps: { key: Step; label: string }[] = [
    { key: 'upload', label: 'Upload' },
    { key: 'mapping', label: 'Review' },
    { key: 'result', label: 'Confirm' },
  ];
  const index = steps.findIndex((s) => s.key === current);

  return (
    <ol className="flex flex-wrap items-center gap-2 border-b border-border pb-4 text-sm">
      {steps.map((step, position) => (
        <li key={step.key} className="flex items-center gap-2">
          <span
            className="step-dot"
            data-state={position === index ? 'current' : position < index ? 'done' : 'todo'}
            aria-hidden="true"
          >
            {position < index ? '✓' : position + 1}
          </span>
          <span
            aria-current={position === index ? 'step' : undefined}
            className={position === index ? 'font-medium text-foreground' : 'text-muted-foreground'}
          >
            {step.label}
            {position < index ? <span className="sr-only"> (completed)</span> : null}
          </span>
          {position < steps.length - 1 ? (
            <span aria-hidden="true" className="mx-2 h-px w-8 bg-border" />
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function ReviewPanel({ preview }: { preview: Preview }): JSX.Element {
  return (
    <>
      <section className="space-y-3 border-t border-border pt-6">
        <SectionHeader
          title="What will happen"
          description={`${preview.total_rows} rows read.${
            preview.duplicates.length > 0
              ? ' Rows matching a business you already have are left alone — the existing record keeps its owner and its history.'
              : ''
          }`}
        />
        <Counts
          testId="preview-summary"
          items={[
            { key: 'create', value: preview.will_create, label: 'new businesses' },
            ...(preview.duplicates.length > 0
              ? [{ key: 'had', value: preview.duplicates.length, label: 'already in Sangam' }]
              : []),
            ...(preview.rejected > 0
              ? [{ key: 'unusable', value: preview.rejected, label: 'unusable' }]
              : []),
          ]}
        />
      </section>

      {preview.sample.length > 0 ? <NormalisedSample sample={preview.sample} /> : null}

      {preview.duplicates.length > 0 ? <DuplicateTable duplicates={preview.duplicates} /> : null}

      {preview.rejected > 0 ? (
        <RejectionTable rejections={preview.rejections} total={preview.rejected} />
      ) : null}
    </>
  );
}

/**
 * What will actually be stored, not what the sheet said.
 *
 * A founder trusts an import once they have seen `98450 12201` become
 * `+91 98450 12201` and a stray `  Sri Lakshmi Sweets ` lose its spaces. Showing
 * the first few rows post-normalisation is the cheapest way to earn that, and it
 * catches a wrong column mapping before eight hundred rows land.
 */
function NormalisedSample({ sample }: { sample: SampleRow[] }): JSX.Element {
  const columns: Array<Column<SampleRow>> = [
    {
      key: 'row',
      header: 'Row',
      align: 'right',
      width: '7%',
      cell: (row) => <span className="text-muted-foreground">{row.row}</span>,
    },
    {
      key: 'company',
      header: 'Business',
      width: '25%',
      cell: (row) => (
        <span className="block truncate font-medium text-foreground">
          {row.normalized.company ?? '—'}
        </span>
      ),
    },
    {
      key: 'name',
      header: 'Contact',
      width: '20%',
      // The importer stores the company in the name field when a row has no
      // named human, exactly as quick add does. Printing it in both columns here
      // would tell a founder their spreadsheet has a contact person called
      // "Evidence Tailors" - which is the confusion this preview exists to
      // prevent, not to create.
      cell: (row) =>
        row.normalized.name && row.normalized.name !== row.normalized.company ? (
          <span className="block truncate text-secondary-foreground">{row.normalized.name}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: 'phone',
      header: 'Phone',
      width: '18%',
      cell: (row) => <span className="tabular text-secondary-foreground">{row.normalized.phone ?? '—'}</span>,
    },
    {
      key: 'email',
      header: 'Email',
      width: '20%',
      dropAt: 900,
      cell: (row) => (
        <span className="block truncate text-secondary-foreground">
          {row.normalized.email ?? '—'}
        </span>
      ),
    },
    {
      key: 'city',
      header: 'Area',
      width: '10%',
      dropAt: 1100,
      cell: (row) => (
        <span className="block truncate text-muted-foreground">{row.normalized.city ?? '—'}</span>
      ),
    },
  ];

  return (
    <section className="space-y-3 border-t border-border pt-6">
      <SectionHeader
        title="How the first rows will be saved"
        description="Cleaned values, exactly as they will be stored."
      />
      <DataTable
        caption="Normalised preview of the first rows"
        columns={columns}
        rows={sample}
        rowKey={(row) => String(row.row)}
        bodyTestId="normalised-sample"
        stickyHeader={false}
      />
    </section>
  );
}

/**
 * Businesses this file already has in Sangam, with the evidence for the match.
 *
 * Never merged automatically. Two shops sharing a landline is ordinary, and an
 * accidental merge of two real customers is far harder to unpick than a duplicate
 * row. The incoming row is kept as an import record pointing at what it matched,
 * so nothing is thrown away either.
 */
function DuplicateTable({ duplicates }: { duplicates: DuplicateMatch[] }): JSX.Element {
  const columns: Array<Column<DuplicateMatch>> = [
    {
      key: 'row',
      header: 'Row',
      align: 'right',
      width: '7%',
      cell: (match) => <span className="text-muted-foreground">{match.row}</span>,
    },
    {
      key: 'incoming',
      header: 'In your file',
      width: '28%',
      cell: (match) => (
        <span className="block truncate text-foreground" title={match.incoming}>
          {match.incoming}
        </span>
      ),
    },
    {
      key: 'existing',
      header: 'Already in Sangam',
      width: '30%',
      cell: (match) => (
        <span className="flex items-baseline gap-2">
          <a
            href={`/leads/${match.lead_id}`}
            className="truncate text-accent underline-offset-2 hover:underline"
          >
            {match.name || 'Existing prospect'}
          </a>
          <span className="shrink-0 text-[13px] text-muted-foreground">{match.status}</span>
        </span>
      ),
    },
    {
      key: 'matched',
      header: 'Matched on',
      width: '35%',
      cell: (match) => (
        <span className="text-muted-foreground">
          {match.matched_on === 'phone' ? 'Same phone number' : 'Same email address'}
          <span className="ml-2 text-[13px]">{match.evidence}</span>
        </span>
      ),
    },
  ];

  return (
    <section className="space-y-3 border-t border-border pt-6">
      <SectionHeader
        title="Already in Sangam"
        description="These rows match a business you already have. They will not be imported again and the existing record will not be changed."
      />
      <DataTable
        caption="Rows matching existing prospects"
        columns={columns}
        rows={duplicates}
        rowKey={(match) => `${match.row}-${match.lead_id}`}
        bodyTestId="duplicate-rows"
        stickyHeader={false}
      />
    </section>
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
  return (
    <section className="space-y-3 border-t border-border pt-6">
      <SectionHeader
        title="Rows that will not be imported"
        description="Fix these in the file and import again, or import without them."
      />

      <div className="max-w-3xl rounded-lg border border-border bg-surface">
        <table className="w-full border-collapse text-left">
          <caption className="sr-only">Rejected rows and the reason for each</caption>
          <thead>
            <tr className="border-b border-border-strong bg-surface-sunken">
              <th
                scope="col"
                className="w-20 px-4 py-2 text-right text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground"
              >
                Row
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-xs font-medium uppercase tracking-[0.04em] text-muted-foreground"
              >
                Why
              </th>
            </tr>
          </thead>
          <tbody data-testid="rejection-rows">
            {rejections.map((rejection) => (
              <tr key={rejection.row} className="border-b border-border align-top last:border-b-0">
                <th
                  scope="row"
                  className="px-4 py-2 text-right text-sm font-normal tabular text-muted-foreground"
                >
                  {rejection.row}
                </th>
                <td className="px-4 py-2 text-sm text-secondary-foreground">
                  {rejection.reasons.join('; ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {total > rejections.length ? (
        <p className="text-[13px] text-muted-foreground">
          Showing the first {rejections.length} of {total}.
        </p>
      ) : null}
    </section>
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
