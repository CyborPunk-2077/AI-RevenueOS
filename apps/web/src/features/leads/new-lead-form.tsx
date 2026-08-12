'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';

interface Member {
  readonly id: string;
  readonly full_name: string;
  readonly is_active: boolean;
}

interface FieldFault {
  readonly field: string;
  readonly reason: string;
}

/**
 * What to say about each field when the server rejects it.
 *
 * The API answers with a structured list of faults, but the `reason` in it is
 * Pydantic's own wording ("Value error, ..."), which is written for whoever is
 * reading a stack trace. A founder should never see that, so the field name -
 * which is stable and part of the API contract - selects the sentence instead.
 */
const FIELD_MESSAGE: Record<string, string> = {
  phone: 'Enter a valid phone number, for example +91 98450 12201.',
  email: 'Enter a valid email address, for example name@business.in.',
  first_name: 'Enter the business name or the contact person.',
  last_name: 'That surname is too long.',
  source: 'Keep "How we found them" shorter.',
  assignee_id: 'Choose one of the people listed.',
};

/** The form control a server field name belongs to. */
const FIELD_INPUT: Record<string, string> = {
  phone: 'phone',
  email: 'email',
  first_name: 'company',
  last_name: 'last_name',
  source: 'source',
  assignee_id: 'assignee_id',
};

function readFaults(payload: unknown): Record<string, string> {
  const faults = (payload as { error?: { details?: { fields?: FieldFault[] } } })?.error?.details
    ?.fields;
  if (!Array.isArray(faults)) return {};
  const mapped: Record<string, string> = {};
  for (const fault of faults) {
    const input = FIELD_INPUT[fault.field] ?? fault.field;
    // First fault per field wins; a second sentence about the same box helps
    // nobody.
    if (!mapped[input]) {
      mapped[input] = FIELD_MESSAGE[fault.field] ?? 'Check this value and try again.';
    }
  }
  return mapped;
}

/**
 * Adding a business you have just decided to approach.
 *
 * Shaped around how a prospect actually arrives: somebody walks past a shop,
 * gets a name from a friend, or spots a business online, and has about twenty
 * seconds to record it before the moment passes. So the first row is the whole
 * required form - who they are and one way to reach them - and everything else
 * lives behind "More details", filled in later when it is known.
 *
 * The contact person is optional on purpose. A prospecting list is a list of
 * businesses, and demanding a named human on day one is how a real list becomes
 * a spreadsheet nobody transfers into the CRM. If only the business is known, the
 * business name becomes the record's name, exactly as the import does.
 */
export function NewLeadForm({ members = [] }: { members?: Member[] }): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [detailed, setDetailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  function clearErrors(): void {
    setError(null);
    setFieldErrors({});
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const element = event.currentTarget;
    setBusy(true);
    clearErrors();

    const form = new FormData(element);
    const text = (key: string): string => String(form.get(key) ?? '').trim();

    const company = text('company');
    const person = text('first_name');

    // Checked here for immediacy only. Every one of these is enforced again by
    // the API, and the mapping below shows whatever the server says - the browser
    // is never the authority on what is acceptable.
    const local: Record<string, string> = {};
    if (!company && !person) {
      local.company = 'Enter the business name, or a contact person under More details.';
    }
    if (!text('phone') && !text('email')) {
      local.phone = 'Add a phone number or an email, otherwise nobody can contact them.';
    }
    const amountText = text('estimated_value');
    if (amountText && !/^[\d,. ]+$/.test(amountText)) {
      // The server stores this as free-form captured text and has no opinion on
      // it, so this check is the only one there is. Said plainly rather than
      // pretending a rule exists further down.
      local.estimated_value = 'Enter an amount using numbers only, for example 25000.';
    }
    if (Object.keys(local).length > 0) {
      setFieldErrors(local);
      setError(null);
      setBusy(false);
      return;
    }

    // Descriptive detail rides in `capture`, which is free-form by design; only
    // identity and ownership are lead columns.
    const capture: Record<string, string | boolean> = {};
    for (const key of ['company', 'city', 'industry', 'website', 'requirement', 'notes']) {
      const value = text(key);
      if (value) capture[key] = value;
    }
    if (!person && company) capture.name_is_business = true;

    const amount = text('estimated_value');
    if (amount) capture.estimated_value_inr = amount;

    const assignee = text('assignee_id');

    const response = await mutate('/api/leads', {
      method: 'POST',
      body: {
        first_name: person || company,
        last_name: text('last_name') || null,
        email: text('email') || null,
        phone: text('phone') || null,
        source: text('source') || 'manual',
        capture,
        assignee_id: assignee || null,
      },
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as {
        error?: { message?: string; code?: string };
      };
      const faults = readFaults(body);
      if (Object.keys(faults).length > 0) {
        // Nothing is reset: the founder keeps everything they typed and fixes
        // the one box that is wrong.
        setFieldErrors(faults);
        setError(null);
      } else {
        setFieldErrors({});
        setError(body.error?.message ?? 'Could not add the prospect. Please try again.');
      }
      setBusy(false);
      return;
    }
    setBusy(false);
    setOpen(false);
    setDetailed(false);
    clearErrors();
    element.reset();
    router.refresh();
  }

  if (!open) {
    return (
      <button
        type="button"
        data-testid="new-lead"
        onClick={() => setOpen(true)}
        className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
      >
        Add a business
      </button>
    );
  }

  const field = 'mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm';
  const bad = 'mt-1 w-full rounded-md border-2 border-destructive bg-background px-3 py-2 text-sm';

  /**
   * Wires a control to its message. `aria-invalid` and `aria-describedby` are what
   * make the error reach a screen reader, and the message is a sentence rather
   * than a red outline, so nobody has to see colour to know what went wrong.
   */
  const attrs = (
    name: string,
  ): { className: string; 'aria-invalid'?: true; 'aria-describedby'?: string } =>
    fieldErrors[name]
      ? { className: bad, 'aria-invalid': true, 'aria-describedby': `${name}-error` }
      : { className: field };

  const Fault = ({ name }: { name: string }): JSX.Element | null =>
    fieldErrors[name] ? (
      <p id={`${name}-error`} data-testid={`error-${name}`} className="mt-1 text-sm text-destructive">
        {fieldErrors[name]}
      </p>
    ) : null;

  return (
    <form onSubmit={onSubmit} className="surface space-y-4 p-5" noValidate>
      <h2 className="font-medium">Add a business you want to approach</h2>

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="company" className="block text-sm font-medium">
            Business name
          </label>
          <input id="company" name="company" data-testid="lead-company" {...attrs('company')} />
          <Fault name="company" />
        </div>
        <div>
          <label htmlFor="phone" className="block text-sm font-medium">
            Phone
          </label>
          <input id="phone" name="phone" data-testid="lead-phone-input" {...attrs('phone')} />
          <Fault name="phone" />
        </div>
        <div>
          <label htmlFor="email" className="block text-sm font-medium">
            Email
          </label>
          <input id="email" name="email" type="email" {...attrs('email')} />
          <Fault name="email" />
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        A business name or a contact person, plus one way to reach them. Everything else can wait.
      </p>

      {detailed ? (
        <div className="space-y-4 border-t border-border pt-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="first_name" className="block text-sm font-medium">
                Contact person
              </label>
              <input id="first_name" name="first_name" {...attrs('first_name')} />
              <Fault name="first_name" />
            </div>
            <div>
              <label htmlFor="last_name" className="block text-sm font-medium">
                Surname
              </label>
              <input id="last_name" name="last_name" {...attrs('last_name')} />
              <Fault name="last_name" />
            </div>
            <div>
              <label htmlFor="city" className="block text-sm font-medium">
                Area or city
              </label>
              <input id="city" name="city" className={field} />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="industry" className="block text-sm font-medium">
                What they do
              </label>
              <input id="industry" name="industry" placeholder="Dental clinic" className={field} />
            </div>
            <div>
              <label htmlFor="website" className="block text-sm font-medium">
                Website
              </label>
              <input id="website" name="website" className={field} />
            </div>
            <div>
              <label htmlFor="source" className="block text-sm font-medium">
                How we found them
              </label>
              <input id="source" name="source" placeholder="Referral" {...attrs('source')} />
              <Fault name="source" />
            </div>
          </div>

          <div>
            <label htmlFor="requirement" className="block text-sm font-medium">
              Why we think they need us
            </label>
            <textarea id="requirement" name="requirement" rows={2} className={field} />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <label htmlFor="notes" className="block text-sm font-medium">
                Notes
              </label>
              <input id="notes" name="notes" className={field} />
            </div>
            <div>
              <label htmlFor="estimated_value" className="block text-sm font-medium">
                Rough value (₹)
              </label>
              <input
                id="estimated_value"
                name="estimated_value"
                inputMode="numeric"
                {...attrs('estimated_value')}
              />
              <Fault name="estimated_value" />
            </div>
          </div>

          {members.length > 0 ? (
            <div className="sm:w-1/3">
              <label htmlFor="assignee_id" className="block text-sm font-medium">
                Who will handle it
              </label>
              <select id="assignee_id" name="assignee_id" data-testid="lead-owner-new" className={field}>
                <option value="">Decide later</option>
                {members
                  .filter((m) => m.is_active)
                  .map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.full_name}
                    </option>
                  ))}
              </select>
            </div>
          ) : null}
        </div>
      ) : (
        <button
          type="button"
          data-testid="more-details"
          onClick={() => setDetailed(true)}
          className="text-sm text-primary underline-offset-2 hover:underline"
        >
          More details
        </button>
      )}

      {/* Form-level fallback for anything that is not about one box - a network
          failure, or a rejection the server did not attribute to a field. */}
      {error ? (
        <p role="alert" data-testid="new-lead-error" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {/* Announced once for the whole form, so a screen-reader user is told there
          is something to fix without every field shouting separately. */}
      {Object.keys(fieldErrors).length > 0 ? (
        <p role="alert" data-testid="new-lead-field-errors" className="text-sm text-destructive">
          Please correct the highlighted {Object.keys(fieldErrors).length === 1 ? 'field' : 'fields'}{' '}
          above.
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          data-testid="create-lead"
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
        >
          {busy ? 'Adding…' : 'Add prospect'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-md border border-border px-4 py-2 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
