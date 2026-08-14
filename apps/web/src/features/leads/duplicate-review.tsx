'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { mutate } from '@/lib/csrf';
import { Button } from '@/features/ui/controls';
import { SectionHeader } from '@/features/ui/primitives';

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
    readonly company?: string | null;
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

/**
 * What to call the other record.
 *
 * A prospecting list is full of businesses with a phone number and no named
 * contact, so the business name is tried first and the person second. Falling
 * straight through to "Unknown record" - which is what this did - asked somebody
 * to decide on a merge without telling them what they were merging.
 */
function name(lead: {
  first_name: string;
  last_name: string | null;
  company?: string | null;
}): string {
  const person = [lead.first_name, lead.last_name].filter(Boolean).join(' ');
  if (lead.company && lead.company !== person) {
    return person ? `${lead.company} (${person})` : lead.company;
  }
  return person || 'Unnamed prospect';
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
    <section aria-labelledby="duplicates-heading" className="space-y-3">
      <SectionHeader
        id="duplicates-heading"
        title="Possible duplicates"
        actions={
          <Button variant="ghost" size="sm" onClick={() => void scan()} disabled={busy}>
            {busy ? 'Scanning…' : 'Scan again'}
          </Button>
        }
      />

      {error ? (
        <p role="alert" className="text-[13px] text-critical">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-[13px] text-muted-foreground">
          {notice}
        </p>
      ) : null}

      {rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          Nothing flagged. Scanning compares email, phone and name against your other open leads.
        </p>
      ) : (
        <ul className="divide-y divide-border border-t border-border" data-testid="duplicate-rows">
          {rows.map((row) => (
            <li key={row.candidate_lead_id} className="space-y-1.5 py-3">
              <p className="text-sm font-medium text-foreground">
                {row.candidate ? name(row.candidate) : 'Record no longer available'}
              </p>
              <p className="text-[13px] text-muted-foreground">
                {row.candidate
                  ? (row.candidate.phone ?? row.candidate.email ?? 'no contact details')
                  : 'It may have been merged or archived since this match was recorded.'}
              </p>
              {/*
                The evidence, in words. A percentage on its own asks somebody to
                trust a number; "same phone number" lets them check.
              */}
              <p className="text-[13px] text-muted-foreground">
                {REASON_LABEL[row.match_reason] ?? row.match_reason} &middot;{' '}
                {Math.round(row.confidence * 100)}% match
              </p>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(row)}>
                Merge into this lead
                <span className="sr-only">{row.candidate ? `, ${name(row.candidate)}` : ''}</span>
              </Button>
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
    </section>
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
      className="rounded border border-warning/50 bg-warning-soft p-4"
    >
      <h3 id="merge-title" className="text-[13px] font-semibold text-foreground">
        Merge {other ? name(other) : 'that record'} into {name(lead)}?
      </h3>

      <ul className="mt-3 list-inside list-disc space-y-1 text-[13px] text-foreground">
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
        <Button variant="primary" onClick={onConfirm} disabled={busy}>
          {busy ? 'Merging…' : 'Merge'}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
