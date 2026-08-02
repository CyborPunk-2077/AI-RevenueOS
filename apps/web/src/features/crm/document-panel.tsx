'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

export interface DocumentEntry {
  readonly id: string;
  readonly title: string;
  readonly status: string;
  readonly file_id: string | null;
  readonly file_name: string | null;
  readonly sent_at: string | null;
  readonly signed_at: string | null;
  readonly version: number;
}

export interface FileEntry {
  readonly id: string;
  readonly name: string;
  readonly size_bytes: number;
  readonly mime_type: string;
  readonly scan_status: string;
  readonly downloadable: boolean;
  readonly owner_name: string | null;
  readonly created_at: string | null;
}

export interface StorageStatus {
  readonly configured: boolean;
  readonly missing: readonly string[];
  readonly blocker: string | null;
}

const NEXT_STATUS: Record<string, string> = {
  draft: 'sent',
  generated: 'sent',
  sent: 'signed',
};

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Documents and files on one record.
 *
 * The file half is deliberately honest about a capability we do not have. Object
 * storage needs an AWS account that does not exist yet, so the attach control is
 * disabled and says exactly what is missing. A control that accepted a file and
 * silently stored nothing would be worse than no control at all -- the user would
 * believe the document was filed.
 *
 * The document half is fully real: it is metadata, and metadata needs no bucket.
 */
export function DocumentPanel({
  parent,
  parentId,
  documents,
  files,
  storage,
}: {
  parent: 'contacts' | 'deals';
  parentId: string;
  documents: DocumentEntry[];
  files: FileEntry[];
  storage: StorageStatus;
}): JSX.Element {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const parentField = parent === 'contacts' ? 'contact_id' : 'deal_id';

  async function onCreate(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true);
    setError(null);
    const data = new FormData(form);
    const response = await mutate('/api/documents', {
      method: 'POST',
      body: { title: String(data.get('title') ?? ''), [parentField]: parentId },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not create the document.');
      setBusy(false);
      return;
    }
    setBusy(false);
    form.reset();
    router.refresh();
  }

  async function advance(doc: DocumentEntry): Promise<void> {
    const next = NEXT_STATUS[doc.status];
    if (!next) return;
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/documents/${doc.id}`, {
      method: 'PATCH',
      ifMatch: doc.version,
      body: { status: next },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not update the document.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  async function removeDocument(doc: DocumentEntry): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/documents/${doc.id}`, { method: 'DELETE' });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
      setError(payload.error?.message ?? 'Could not delete the document.');
      setBusy(false);
      return;
    }
    setBusy(false);
    router.refresh();
  }

  return (
    <section aria-labelledby="documents-heading" className="space-y-4">
      <h2 id="documents-heading" className="font-medium">
        Documents
      </h2>

      <form
        onSubmit={onCreate}
        className="flex flex-wrap items-end gap-3 rounded border p-4"
        noValidate
      >
        <div className="grow">
          <label htmlFor="document_title" className="block text-sm">
            Document title
          </label>
          <input
            id="document_title"
            name="title"
            required
            maxLength={300}
            className="mt-1 w-full rounded border px-3 py-2"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          data-testid="add-document"
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
        >
          Add document
        </button>
      </form>

      {error ? (
        <p role="alert" data-testid="document-error" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {documents.length === 0 ? (
        <p
          data-testid="documents-empty"
          className="rounded border border-dashed p-6 text-sm text-muted-foreground"
        >
          No documents yet.
        </p>
      ) : (
        <ul className="divide-y" data-testid="document-rows">
          {documents.map((doc) => (
            <li key={doc.id} className="flex items-center justify-between gap-4 py-2 text-sm">
              <div>
                <span>{doc.title}</span>
                <span
                  data-testid={`document-status-${doc.id}`}
                  className="ml-2 rounded bg-muted px-2 py-0.5 text-xs"
                >
                  {doc.status}
                </span>
                {doc.file_name ? (
                  <span className="ml-2 text-xs text-muted-foreground">{doc.file_name}</span>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                {NEXT_STATUS[doc.status] ? (
                  <button
                    type="button"
                    disabled={busy}
                    data-testid={`advance-document-${doc.id}`}
                    onClick={() => void advance(doc)}
                    className="rounded border px-3 py-1 text-xs disabled:opacity-50"
                  >
                    Mark {NEXT_STATUS[doc.status]}
                  </button>
                ) : null}
                <button
                  type="button"
                  disabled={busy}
                  data-testid={`delete-document-${doc.id}`}
                  onClick={() => void removeDocument(doc)}
                  className="rounded border px-3 py-1 text-xs disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <h3 className="pt-2 font-medium">Files</h3>

      {storage.configured ? null : (
        <div
          role="status"
          data-testid="storage-unavailable"
          className="rounded border border-dashed p-4 text-sm"
        >
          <p className="font-medium">File uploads are unavailable.</p>
          <p className="mt-1 text-muted-foreground">{storage.blocker}</p>
          {storage.missing.length > 0 ? (
            <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
              {storage.missing.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      )}

      {files.length === 0 ? (
        <p
          data-testid="files-empty"
          className="rounded border border-dashed p-6 text-sm text-muted-foreground"
        >
          No files attached.
        </p>
      ) : (
        <ul className="divide-y" data-testid="file-rows">
          {files.map((file) => (
            <li key={file.id} className="flex items-center justify-between gap-4 py-2 text-sm">
              <div>
                <span>{file.name}</span>
                <span className="ml-2 text-xs text-muted-foreground">
                  {humanSize(file.size_bytes)}
                </span>
                <span
                  data-testid={`file-scan-${file.id}`}
                  className="ml-2 rounded bg-muted px-2 py-0.5 text-xs"
                >
                  {file.scan_status}
                </span>
              </div>
              {file.downloadable ? (
                <a
                  href={`/api/files/${file.id}/download`}
                  className="rounded border px-3 py-1 text-xs"
                >
                  Download
                </a>
              ) : (
                <span className="text-xs text-muted-foreground">not yet available</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
