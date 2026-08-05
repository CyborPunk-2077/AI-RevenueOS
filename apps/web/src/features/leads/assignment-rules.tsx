'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { mutate } from '@/lib/csrf';
import { Card, EmptyState, StatusPill } from '@/features/ui/primitives';

/**
 * Assignment rules.
 *
 * Order is the entire semantics: the first matching rule wins, so the list is
 * the algorithm. That is why reordering is a first-class action with its own
 * endpoint rather than a per-rule "priority" number a user has to keep
 * consistent by hand.
 *
 * Reordering uses buttons, not drag and drop. Drag is faster with a mouse and
 * impossible with a keyboard; a Move up / Move down pair works for everyone and
 * announces the change. If drag is added later it must be in addition to these,
 * never instead.
 */

export interface Condition {
  readonly field: string;
  readonly operator: string;
  readonly value?: unknown;
}

export interface AssignmentRule {
  readonly id: string;
  readonly name: string;
  readonly strategy: string;
  readonly conditions: { all?: Condition[] };
  readonly targets: string[];
  readonly position: number;
  readonly is_active: boolean;
  readonly version: number;
}

/** Mirrors CONDITION_FIELDS in domain/leads/assignment.py. */
const FIELDS = [
  'source',
  'source_channel',
  'city',
  'company',
  'category',
  'qualification_score',
  'status',
] as const;

const OPERATORS = [
  'equals',
  'not_equals',
  'contains',
  'starts_with',
  'in',
  'is_set',
  'is_not_set',
] as const;

const STRATEGIES = [
  { value: 'round_robin', label: 'Round robin - take turns' },
  { value: 'load_balanced', label: 'Load balanced - lightest queue first' },
  { value: 'first_available', label: 'First available - always the first name' },
] as const;

export function AssignmentRules({ rules }: { rules: AssignmentRule[] }): JSX.Element {
  const router = useRouter();
  const [order, setOrder] = useState(rules);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dryRunLead, setDryRunLead] = useState('');
  const [dryRun, setDryRun] = useState<string | null>(null);

  async function move(index: number, direction: -1 | 1): Promise<void> {
    const target = index + direction;
    if (target < 0 || target >= order.length) return;

    const next = [...order];
    const [moved] = next.splice(index, 1);
    next.splice(target, 0, moved);
    setOrder(next);

    setBusy(true);
    setError(null);
    const response = await mutate('/api/assignment-rules/reorder', {
      method: 'POST',
      body: { rule_ids: next.map((rule) => rule.id) },
    });
    if (!response.ok) {
      setOrder(order); // put it back rather than leave the UI lying
      setError('That order could not be saved.');
    }
    setBusy(false);
    router.refresh();
  }

  async function toggle(rule: AssignmentRule): Promise<void> {
    setBusy(true);
    const response = await mutate(`/api/assignment-rules/${rule.id}?version=${rule.version}`, {
      method: 'PATCH',
      body: { is_active: !rule.is_active },
    });
    if (!response.ok) setError('That rule could not be updated.');
    setBusy(false);
    router.refresh();
  }

  async function preview(): Promise<void> {
    if (!dryRunLead.trim()) return;
    setBusy(true);
    setDryRun(null);
    const response = await mutate(`/api/leads/${dryRunLead.trim()}/assign?dry_run=true`, {
      method: 'POST',
    });
    if (!response.ok) {
      setDryRun('That lead could not be found, or no rule matched it.');
      setBusy(false);
      return;
    }
    const payload = (await response.json()) as {
      data: { assigned: boolean; would_assign?: { rule_name?: string; assignee_id: string } };
    };
    setDryRun(
      payload.data.would_assign
        ? `Would assign to ${payload.data.would_assign.assignee_id} by rule "${payload.data.would_assign.rule_name ?? 'unnamed'}".`
        : 'No rule matches that lead, so it would stay unassigned.',
    );
    setBusy(false);
  }

  return (
    <div className="space-y-6">
      <Card>
        <h2 className="heading text-base">How assignment works</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Rules are checked from the top. The first one that matches wins and the rest are
          ignored. A lead that matches nothing stays unassigned rather than being given to
          someone arbitrarily.
        </p>
      </Card>

      {order.length === 0 ? (
        <EmptyState
          title="No assignment rules"
          description="Without rules, new leads arrive unassigned and someone has to pick them up manually."
        />
      ) : (
        <ol className="space-y-3">
          {order.map((rule, index) => (
            <li key={rule.id}>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="heading text-sm">
                      <span className="text-muted-foreground">{index + 1}.</span> {rule.name}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {describe(rule)} &middot; {rule.targets.length}{' '}
                      {rule.targets.length === 1 ? 'assignee' : 'assignees'}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {rule.is_active ? (
                      <StatusPill tone="success">Active</StatusPill>
                    ) : (
                      <StatusPill tone="neutral">Paused</StatusPill>
                    )}
                    <button
                      type="button"
                      onClick={() => void move(index, -1)}
                      disabled={busy || index === 0}
                      className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                    >
                      ↑<span className="sr-only"> Move {rule.name} up</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void move(index, 1)}
                      disabled={busy || index === order.length - 1}
                      className="rounded border border-border px-2 py-1 text-xs disabled:opacity-40"
                    >
                      ↓<span className="sr-only"> Move {rule.name} down</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggle(rule)}
                      disabled={busy}
                      className="rounded border border-border px-3 py-1 text-xs"
                    >
                      {rule.is_active ? 'Pause' : 'Activate'}
                      <span className="sr-only"> {rule.name}</span>
                    </button>
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ol>
      )}

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <Card>
        <h2 className="heading text-base">Test against a lead</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          A dry run reports what would happen without assigning anything.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <label htmlFor="dry_lead" className="sr-only">
            Lead id
          </label>
          <input
            id="dry_lead"
            value={dryRunLead}
            placeholder="Lead id"
            onChange={(event) => setDryRunLead(event.target.value)}
            className="field flex-1 font-mono"
          />
          <button
            type="button"
            onClick={() => void preview()}
            disabled={busy || !dryRunLead.trim()}
            className="btn btn-ghost"
          >
            Dry run
          </button>
        </div>
        {dryRun ? (
          <p role="status" className="mt-3 text-sm">
            {dryRun}
          </p>
        ) : null}
      </Card>
    </div>
  );
}

function describe(rule: AssignmentRule): string {
  const clauses = rule.conditions?.all ?? [];
  const strategy = STRATEGIES.find((s) => s.value === rule.strategy)?.label ?? rule.strategy;
  if (clauses.length === 0) return `Every lead · ${strategy}`;
  return `${clauses
    .map((clause) => `${clause.field} ${clause.operator.replace(/_/g, ' ')} ${clause.value ?? ''}`.trim())
    .join(' and ')} · ${strategy}`;
}

export { FIELDS as CONDITION_FIELDS, OPERATORS, STRATEGIES };
