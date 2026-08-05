'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { mutate } from '@/lib/csrf';
import { Card, EmptyState, StatusPill } from '@/features/ui/primitives';

/**
 * The capture form builder.
 *
 * The distinction this screen exists to make visible: `schema` is the draft you
 * are editing, `published_schema` is the snapshot the internet is being served.
 * They diverge the moment you change a field, and they stay diverged until you
 * press Publish. A builder that hides that is how a half-renamed field ends up
 * live on someone's website.
 *
 * So: the pending-changes banner is not decoration, the Publish button states
 * what it will do, and the published panel shows the snapshot rather than the
 * draft.
 */

export interface FormField {
  readonly name: string;
  readonly type: string;
  readonly label: string;
  readonly required: boolean;
  readonly options: string[];
}

export interface FormSchema {
  readonly fields: FormField[];
  readonly submit_label?: string;
  readonly consent_text?: string | null;
}

export interface CaptureForm {
  readonly id: string;
  readonly name: string;
  readonly type: string;
  readonly schema: FormSchema;
  readonly published_schema: FormSchema | Record<string, never>;
  readonly allowed_origins: string[];
  readonly is_published: boolean;
  readonly published_at: string | null;
  readonly has_unpublished_changes: boolean;
  readonly version: number;
}

const FIELD_TYPES = [
  'text',
  'textarea',
  'email',
  'phone',
  'number',
  'select',
  'multiselect',
  'checkbox',
  'date',
  'hidden',
] as const;

const BLANK: FormField = {
  name: '',
  type: 'text',
  label: '',
  required: false,
  options: [],
};

export function FormBuilder({ form }: { form: CaptureForm }): JSX.Element {
  const router = useRouter();
  const [name, setName] = useState(form.name);
  const [fields, setFields] = useState<FormField[]>(form.schema.fields ?? []);
  const [origins, setOrigins] = useState((form.allowed_origins ?? []).join('\n'));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const contactable = useMemo(
    () => fields.some((field) => field.name === 'email' || field.name === 'phone'),
    [fields],
  );

  async function call(path: string, method: string, body?: unknown): Promise<boolean> {
    setBusy(true);
    setError(null);
    setNotice(null);
    const response = await mutate(path, body === undefined ? { method } : { method, body });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string; details?: { problems?: string[] } };
      };
      setError(
        payload.error?.details?.problems?.join(' ') ??
          payload.error?.message ??
          'That did not work.',
      );
      setBusy(false);
      return false;
    }
    setBusy(false);
    router.refresh();
    return true;
  }

  async function saveDraft(): Promise<void> {
    const ok = await call(`/api/forms/${form.id}`, 'PATCH', {
      name,
      schema: { ...form.schema, fields },
      allowed_origins: origins.split('\n').map((line) => line.trim()).filter(Boolean),
    });
    if (ok) setNotice('Draft saved. It is not live until you publish.');
  }

  async function publish(): Promise<void> {
    const ok = await call(`/api/forms/${form.id}/publish`, 'POST');
    if (ok) setNotice('Published. The live form now matches this draft.');
  }

  async function unpublish(): Promise<void> {
    const ok = await call(`/api/forms/${form.id}/unpublish`, 'POST');
    if (ok) setNotice('Taken offline. The snapshot is kept, so you can republish.');
  }

  return (
    <div className="space-y-6">
      {form.has_unpublished_changes ? (
        <div
          role="status"
          className="rounded border border-warning/40 bg-warning-soft p-4 text-sm text-warning"
        >
          <strong className="font-medium">This draft differs from the live form.</strong> Visitors
          still see the version published{' '}
          {form.published_at ? new Date(form.published_at).toLocaleString('en-IN') : 'earlier'}.
          Publish to make these changes live.
        </div>
      ) : null}

      <Card>
        <label htmlFor="form_name" className="block text-sm font-medium">
          Form name
        </label>
        <input
          id="form_name"
          value={name}
          maxLength={150}
          onChange={(event) => setName(event.target.value)}
          className="mt-1 w-full rounded border border-border px-3 py-2 text-sm"
        />
      </Card>

      <Card>
        <div className="flex items-center justify-between">
          <h2 className="heading text-base">Fields</h2>
          <button
            type="button"
            onClick={() => setFields([...fields, { ...BLANK }])}
            className="rounded border border-border px-3 py-1.5 text-sm"
          >
            Add field
          </button>
        </div>

        {fields.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">No fields yet.</p>
        ) : (
          <ul className="mt-4 space-y-4">
            {fields.map((field, index) => (
              <li key={index} className="rounded border border-border p-3">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <label htmlFor={`name-${index}`} className="block text-xs font-medium">
                      Name
                    </label>
                    <input
                      id={`name-${index}`}
                      value={field.name}
                      onChange={(event) => replace(index, { ...field, name: event.target.value })}
                      className="mt-1 w-full rounded border border-border px-2 py-1 font-mono text-xs"
                    />
                  </div>
                  <div>
                    <label htmlFor={`label-${index}`} className="block text-xs font-medium">
                      Label
                    </label>
                    <input
                      id={`label-${index}`}
                      value={field.label}
                      onChange={(event) => replace(index, { ...field, label: event.target.value })}
                      className="mt-1 w-full rounded border border-border px-2 py-1 text-xs"
                    />
                  </div>
                  <div>
                    <label htmlFor={`type-${index}`} className="block text-xs font-medium">
                      Type
                    </label>
                    <select
                      id={`type-${index}`}
                      value={field.type}
                      onChange={(event) => replace(index, { ...field, type: event.target.value })}
                      className="mt-1 w-full rounded border border-border px-2 py-1 text-xs"
                    >
                      {FIELD_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="mt-3 flex items-center justify-between">
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={field.required}
                      onChange={(event) =>
                        replace(index, { ...field, required: event.target.checked })
                      }
                    />
                    Required
                  </label>
                  <button
                    type="button"
                    onClick={() => setFields(fields.filter((_, i) => i !== index))}
                    className="text-xs text-destructive underline"
                  >
                    Remove
                    <span className="sr-only"> the field {field.name || index + 1}</span>
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {!contactable ? (
          <p role="alert" className="mt-3 text-sm text-destructive">
            Add a field named <code>email</code> or <code>phone</code>. Without one, the leads this
            form creates cannot be contacted.
          </p>
        ) : null}
      </Card>

      <Card>
        <label htmlFor="form_origins" className="block text-sm font-medium">
          Sites allowed to submit this form
        </label>
        <p id="origins-help" className="mt-1 text-xs text-muted-foreground">
          One per line, scheme and domain only. Leave empty for a hosted form that is not embedded.
        </p>
        <textarea
          id="form_origins"
          rows={3}
          value={origins}
          aria-describedby="origins-help"
          onChange={(event) => setOrigins(event.target.value)}
          className="mt-2 w-full rounded border border-border px-3 py-2 font-mono text-sm"
        />
      </Card>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-sm text-muted-foreground">
          {notice}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void saveDraft()}
          disabled={busy}
          className="rounded border border-border px-4 py-2 text-sm disabled:opacity-60"
        >
          Save draft
        </button>
        <button
          type="button"
          onClick={() => void publish()}
          disabled={busy || !contactable}
          className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
        >
          {form.is_published ? 'Publish changes' : 'Publish form'}
        </button>
        {form.is_published ? (
          <button
            type="button"
            onClick={() => void unpublish()}
            disabled={busy}
            className="rounded border border-border px-4 py-2 text-sm disabled:opacity-60"
          >
            Take offline
          </button>
        ) : null}
      </div>

      {form.is_published ? <PublishedPanel form={form} /> : null}
    </div>
  );

  function replace(index: number, next: FormField): void {
    setFields(fields.map((field, i) => (i === index ? next : field)));
  }
}

/** What is actually being served: the snapshot, not the draft. */
function PublishedPanel({ form }: { form: CaptureForm }): JSX.Element {
  const snapshot = form.published_schema as FormSchema;
  const live = snapshot.fields ?? [];

  return (
    <Card>
      <div className="flex items-center gap-2">
        <h2 className="heading text-base">Live now</h2>
        <StatusPill tone="success">Published</StatusPill>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        This is the snapshot visitors see, taken when you last published.
      </p>

      <ul className="mt-3 flex flex-wrap gap-2">
        {live.map((field) => (
          <li key={field.name} className="rounded bg-surface-sunken px-2 py-1 font-mono text-xs">
            {field.name}
            {field.required ? '*' : ''}
          </li>
        ))}
      </ul>

      <h3 className="mt-5 text-sm font-medium">Embed</h3>
      <pre className="mt-2 overflow-x-auto rounded bg-surface-sunken p-3 text-xs">
        <code>{`<script src="/forms.js" data-form="${form.id}" async></script>`}</code>
      </pre>

      <h3 className="mt-5 text-sm font-medium">Allowed origins</h3>
      {form.allowed_origins.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          None listed, so the form accepts submissions from anywhere it is hosted.
        </p>
      ) : (
        <ul className="mt-1 list-inside list-disc text-xs text-muted-foreground">
          {form.allowed_origins.map((origin) => (
            <li key={origin}>{origin}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function FormList({
  forms,
  tenantSlug,
}: {
  forms: CaptureForm[];
  tenantSlug: string;
}): JSX.Element {
  if (forms.length === 0) {
    return (
      <EmptyState
        title="No capture forms yet"
        description="Build one to collect leads from your website. Nothing goes live until you publish it."
      />
    );
  }

  return (
    <ul className="space-y-3">
      {forms.map((form) => (
        <li key={form.id}>
          <a href={`/${tenantSlug}/forms/${form.id}`} className="block">
            <Card interactive>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="heading text-sm">{form.name}</span>
                <span className="flex gap-2">
                  {form.is_published ? (
                    <StatusPill tone="success">Published</StatusPill>
                  ) : (
                    <StatusPill tone="neutral">Draft</StatusPill>
                  )}
                  {form.has_unpublished_changes ? (
                    <StatusPill tone="warning">Unpublished changes</StatusPill>
                  ) : null}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {(form.schema.fields ?? []).length} fields
              </p>
            </Card>
          </a>
        </li>
      ))}
    </ul>
  );
}
