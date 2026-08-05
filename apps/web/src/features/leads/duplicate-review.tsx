'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { mutate } from '@/lib/csrf';
import { Card, StatusPill } from '@/features/ui/primitives';

/**
 * Duplicate review and merge.
 *
 * Merge is reversible - the loser is kept, stamped with `merged_into_id`, never
 * deleted - but it does not *feel* reversible, and a confirmation that
 * understates it teaches people to fear the button. So the dialog names both
 * records explicitly, says which survives, and lists exactly which fields will
 * be filled from the other one.
 *
 * The survivor is the lead whose page you are on. Making that implicit is how
 * someone merges the wrong way round and loses the record they were curating.
 */

export interface Candidate {
  readonly candidate_lead_id: string;
  readonly match_reason: string;
  readonly confidence: number;
  readonly candidate: {
    readonly first_name: string;
    readonly last_name: string | null;
    readonly email: string | null;
    readonly phone: string | null;
    readonly status: string;
  } | null;
}

export interface LeadSummary {
  readonly id: string;
  readonly first_name: string;
  readonly last_name: string | null;
  readonly email: string | null;
  readonly phone: string | null;
}

const REASON_LABEL: Record<string, string> = {
  exact_email: 'Same email address',
  exact_phone: 'Same phone number',
  name_company: 'Same name and company',
  fuzzy_name: 'Similar name',
};

function name(lead: { first_name: string; last_name: string | null }): string {
  return [lead.first_name, lead.last_name].filter(Boolean).join(' ');
}

export function DuplicateReview({
  lead,
  candidates,
}: {
  lead: LeadSummary;
  candidates: Candidate[];
}): JSX.Element {
  const router = useRouter();
  const [rows, setRows] = useState(candidates);
  const [confirming, setConfirming] = useState<Candidate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function scan(): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/leads/${lead.id}/deduplicate`, { method: 'POST' });
    if (!response.ok) {
      setError('That scan could not be run.');
      setBusy(false);
      return;
    }
    const payload = (await response.json()) as { data: { candidates: Candidate[] } };
    setRows(payload.data.candidates);
    setNotice(
      payload.data.candidates.length === 0
        ? 'No likely duplicates found.'
        : `${payload.data.candidates.length} possible duplicates found.`,
    );
    setBusy(false);
  }

  async function merge(candidate: Candidate): Promise<void> {
    setBusy(true);
    setError(null);
    const response = await mutate(`/api/leads/${lead.id}/merge`, {
      method: 'POST',
      body: { merge_id: candidate.candidate_lead_id },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      setError(payload.error?.message ?? 'That merge could not be completed.');
      setBusy(false);
      setConfirming(null);
      return;
    }
    setRows(rows.filter((row) => row.candidate_lead_id !== candidate.candidate_lead_id));
    setConfirming(null);
    setNotice('Merged. The other record is archived and now points here.');
    setBusy(false);
    router.refresh();
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="heading text-base">Possible duplicates</h2>
        <button
          type="button"
          onClick={() => void scan()}
          disabled={busy}
          className="btn btn-ghost px-3 py-1.5"
        >
          {busy ? 'Scanning…' : 'Scan again'}
        </button>
      </div>

      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="mt-3 text-sm text-muted-foreground">
          {notice}
        </p>
      ) : null}

      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Nothing flagged. Scanning compares email, phone and name against your other open leads.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {rows.map((row) => (
            <li key={row.candidate_lead_id} className="rounded border border-border p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">
                    {row.candidate ? name(row.candidate) : 'Unknown record'}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {row.candidate?.email ?? row.candidate?.phone ?? 'no contact details'}
                  </p>
                  <p className="mt-1">
                    <StatusPill tone={row.confidence >= 0.9 ? 'warning' : 'neutral'}>
                      {REASON_LABEL[row.match_reason] ?? row.match_reason} ·{' '}
                      {Math.round(row.confidence * 100)}% match
                    </StatusPill>
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setConfirming(row)}
                  className="btn btn-ghost px-3 py-1.5"
                >
                  Merge into this lead
                  <span className="sr-only">
                    {row.candidate ? `, ${name(row.candidate)}` : ''}
                  </span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {confirming ? (
        <MergeConfirmation
          lead={lead}
          candidate={confirming}
          busy={busy}
          onCancel={() => setConfirming(null)}
          onConfirm={() => void merge(confirming)}
        />
      ) : null}
    </Card>
  );
}

/**
 * The confirmation names both records and states the direction. "Are you sure?"
 * would technically be accurate and completely useless.
 */
function MergeConfirmation({
  lead,
  candidate,
  busy,
  onCancel,
  onConfirm,
}: {
  lead: LeadSummary;
  candidate: Candidate;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}): JSX.Element {
  const other = candidate.candidate;
  const fillable: string[] = [];
  if (!lead.email && other?.email) fillable.push('email');
  if (!lead.phone && other?.phone) fillable.push('phone');
  if (!lead.last_name && other?.last_name) fillable.push('last name');

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="merge-title"
      className="mt-4 rounded border border-warning/50 bg-warning-soft p-4"
    >
      <h3 id="merge-title" className="heading text-sm">
        Merge {other ? name(other) : 'that record'} into {name(lead)}?
      </h3>

      <ul className="mt-3 list-inside list-disc space-y-1 text-sm">
        <li>
          <strong>{name(lead)}</strong> stays, and keeps every value it already has.
        </li>
        <li>
          <strong>{other ? name(other) : 'The other lead'}</strong> is archived. It is not deleted -
          links to it will point here.
        </li>
        <li>
          {fillable.length > 0
            ? `Empty fields on this lead will be filled from it: ${fillable.join(', ')}.`
            : 'Nothing will be overwritten; this lead already has every field the other one has.'}
        </li>
        <li>Both records keep their source history, so attribution is not lost.</li>
      </ul>

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="btn btn-primary"
        >
          {busy ? 'Merging…' : 'Merge'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="btn btn-ghost"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
