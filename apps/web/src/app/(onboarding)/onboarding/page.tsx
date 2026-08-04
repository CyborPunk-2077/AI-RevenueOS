import { redirect } from 'next/navigation';
import { apiFetch } from '@/lib/session';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Set up your workspace' };

interface OnboardingState {
  readonly completed: boolean;
  readonly steps: { readonly key: string; readonly label?: string; readonly done: boolean }[];
  readonly tenant_slug?: string;
}

/**
 * The onboarding checklist.
 *
 * State comes from the server, which owns the dependency order between steps; a
 * client-side stepper would let someone skip to "invite your team" before the
 * tenant has roles to invite them into.
 */
export default async function OnboardingPage(): Promise<JSX.Element> {
  const result = await apiFetch<OnboardingState>('/onboarding/state');
  if (!result.ok || !result.data) redirect('/login');
  if (result.data.completed) redirect('/leads');

  const steps = result.data.steps ?? [];
  const remaining = steps.filter((step) => !step.done).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Set up your workspace</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {remaining === 0
            ? 'Everything is done. One moment.'
            : `${remaining} ${remaining === 1 ? 'step' : 'steps'} left before your team can start.`}
        </p>
      </div>

      <ol className="space-y-3">
        {steps.map((step) => (
          <li
            key={step.key}
            className="flex items-center justify-between rounded-lg border border-border px-4 py-3"
          >
            <span className="text-sm">{step.label ?? step.key.replace(/_/g, ' ')}</span>
            {/* Text, not a coloured tick: a checkmark alone is invisible to a
                screen reader user and ambiguous to everyone else. */}
            <span className="text-xs font-medium uppercase text-muted-foreground">
              {step.done ? 'Done' : 'To do'}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
