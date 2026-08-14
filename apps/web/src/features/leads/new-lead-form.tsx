'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { mutate } from '@/lib/csrf';
import { Button, controlClass } from '@/features/ui/controls';
import { Drawer } from '@/features/ui/drawer';

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
 * Shaped around how a prospect actually arrives: somebody walks past a shop, gets
 * a name from a friend, or spots a business online, and has about twenty seconds
 * to record it before the moment passes. So the first section is the whole
 * required form - who they are and one way to reach them - and everything else
 * lives behind "More details", filled in later when it is known.
 *
 * The contact person is optional on purpose. A prospecting list is a list of
 * businesses, and demanding a named human on day one is how a real list stays in
 * a spreadsheet. If only the business is known, the business name becomes the
 * record's name and `capture.name_is_business` records that it is not a person -
 * which is what lets every list in the product show an em dash in the contact
 * column instead of printing the shop's name twice.
 *
 * **It is a drawer now, not a panel at the top of the list.** People come to
 * Prospects to look at prospects; adding one is something they do occasionally
 * and deliberately. The validation behaviour is unchanged and deliberately so -
 * every `error-*` marker, the typed values surviving a rejection, and the
 * `aria-invalid`/`aria-describedby` wiring were hard-won in session 4 and are
 * pinned by browser tests.
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
    const value = (key: string): string => String(form.get(key) ?? '').trim();

    const company = value('company');
    const person = value('first_name');

    // Checked here for immediacy only. Every one of these is enforced again by
    // the API, and the mapping below shows whatever the server says - the browser
    // is never the authority on what is acceptable.
    const local: Record<string, string> = {};
    if (!company && !person) {
      local.company = 'Enter the business name, or a contact person under More details.';
    }
    if (!value('phone') && !value('email')) {
      local.phone = 'Add a phone number or an email, otherwise nobody can contact them.';
    }
    const amountText = value('estimated_value');
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
      if (local.estimated_value) setDetailed(true);
      return;
    }

    // Descriptive detail rides in `capture`, which is free-form by design; only
    // identity and ownership are lead columns.
    const capture: Record<string, string | boolean> = {};
    for (const key of ['company', 'city', 'industry', 'website', 'requirement', 'notes']) {
      const entered = value(key);
      if (entered) capture[key] = entered;
    }
    if (!person && company) capture.name_is_business = true;

    const amount = value('estimated_value');
    if (amount) capture.estimated_value_inr = amount;

    const assignee = value('assignee_id');

    const response = await mutate('/api/leads', {
      method: 'POST',
      body: {
        first_name: person || company,
        last_name: value('last_name') || null,
        email: value('email') || null,
        phone: value('phone') || null,
        source: value('source') || 'manual',
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
        // A rejected field behind the disclosure would otherwise be a message
        // nobody can see.
        if (faults.first_name || faults.last_name || faults.source || faults.assignee_id) {
          setDetailed(true);
        }
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

  /**
   * Wires a control to its message. `aria-invalid` and `aria-describedby` are
   * what make the error reach a screen reader; the message is a sentence rather
   * than a red outline, so nobody has to see colour to know what went wrong.
   */
  const attrs = (
    name: string,
  ): { className: string; 'aria-invalid'?: true; 'aria-describedby'?: string } =>
    fieldErrors[name]
      ? {
          className: controlClass(true),
          'aria-invalid': true,
          'aria-describedby': `${name}-error`,
        }
      : { className: controlClass(false) };

  const Fault = ({ name }: { name: string }): JSX.Element | null =>
    fieldErrors[name] ? (
      <p id={`${name}-error`} data-testid={`error-${name}`} className="mt-1 text-[13px] text-critical">
        {fieldErrors[name]}
      </p>
    ) : null;

  const label = 'block text-[13px] font-medium text-foreground';

  return (
    <>
      <Button
        variant="primary"
        data-testid="new-lead"
        onClick={() => setOpen(true)}
        aria-expanded={open}
      >
        Add a business
      </Button>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Add a business you want to approach"
        description="A business name or a contact person, plus one way to reach them. Everything else can wait."
        data-testid="new-lead-drawer"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="primary" type="submit" form="new-lead-form" disabled={busy} data-testid="create-lead">
              {busy ? 'Adding…' : 'Add prospect'}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        }
      >
        <form id="new-lead-form" onSubmit={onSubmit} className="space-y-4" noValidate>
          <div className="space-y-3">
            <div>
              <label htmlFor="company" className={label}>
                Business name
              </label>
              <div className="mt-1">
                <input id="company" name="company" data-testid="lead-company" {...attrs('company')} />
              </div>
              <Fault name="company" />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="phone" className={label}>
                  Phone
                </label>
                <div className="mt-1">
                  <input id="phone" name="phone" data-testid="lead-phone-input" {...attrs('phone')} />
                </div>
                <Fault name="phone" />
              </div>
              <div>
                <label htmlFor="email" className={label}>
                  Email
                </label>
                <div className="mt-1">
                  <input id="email" name="email" type="email" {...attrs('email')} />
                </div>
                <Fault name="email" />
              </div>
            </div>
          </div>

          {detailed ? (
            <div className="space-y-4 border-t border-border pt-4">
              <h3 className="text-[13px] font-semibold text-foreground">More details</h3>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="first_name" className={label}>
                    Contact person
                  </label>
                  <div className="mt-1">
                    <input id="first_name" name="first_name" {...attrs('first_name')} />
                  </div>
                  <Fault name="first_name" />
                </div>
                <div>
                  <label htmlFor="last_name" className={label}>
                    Surname
                  </label>
                  <div className="mt-1">
                    <input id="last_name" name="last_name" {...attrs('last_name')} />
                  </div>
                  <Fault name="last_name" />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="city" className={label}>
                    Area or city
                  </label>
                  <div className="mt-1">
                    <input id="city" name="city" className={controlClass(false)} />
                  </div>
                </div>
                <div>
                  <label htmlFor="industry" className={label}>
                    What they do
                  </label>
                  <div className="mt-1">
                    <input
                      id="industry"
                      name="industry"
                      placeholder="Dental clinic"
                      className={controlClass(false)}
                    />
                  </div>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="website" className={label}>
                    Website
                  </label>
                  <div className="mt-1">
                    <input id="website" name="website" className={controlClass(false)} />
                  </div>
                </div>
                <div>
                  <label htmlFor="source" className={label}>
                    How we found them
                  </label>
                  <div className="mt-1">
                    <input id="source" name="source" placeholder="Referral" {...attrs('source')} />
                  </div>
                  <Fault name="source" />
                </div>
              </div>

              <div>
                <label htmlFor="requirement" className={label}>
                  Why we think they need us
                </label>
                <div className="mt-1">
                  <textarea
                    id="requirement"
                    name="requirement"
                    rows={2}
                    className={controlClass(false)}
                  />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="notes" className={label}>
                    Notes
                  </label>
                  <div className="mt-1">
                    <input id="notes" name="notes" className={controlClass(false)} />
                  </div>
                </div>
                <div>
                  <label htmlFor="estimated_value" className={label}>
                    Rough value (₹)
                  </label>
                  <div className="mt-1">
                    <input
                      id="estimated_value"
                      name="estimated_value"
                      inputMode="numeric"
                      {...attrs('estimated_value')}
                    />
                  </div>
                  <Fault name="estimated_value" />
                </div>
              </div>

              {members.length > 0 ? (
                <div>
                  <label htmlFor="assignee_id" className={label}>
                    Who will handle it
                  </label>
                  <div className="mt-1">
                    <select
                      id="assignee_id"
                      name="assignee_id"
                      data-testid="lead-owner-new"
                      className={controlClass(false)}
                    >
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
                </div>
              ) : null}
            </div>
          ) : (
            <button
              type="button"
              data-testid="more-details"
              onClick={() => setDetailed(true)}
              className="text-[13px] text-accent underline-offset-2 hover:underline"
            >
              More details
            </button>
          )}

          {/* Form-level fallback for anything that is not about one box - a
              network failure, or a rejection the server did not attribute to a
              field. */}
          {error ? (
            <p role="alert" data-testid="new-lead-error" className="text-[13px] text-critical">
              {error}
            </p>
          ) : null}

          {/* Announced once for the whole form, so a screen-reader user is told
              there is something to fix without every field shouting separately. */}
          {Object.keys(fieldErrors).length > 0 ? (
            <p role="alert" data-testid="new-lead-field-errors" className="text-[13px] text-critical">
              Please correct the highlighted{' '}
              {Object.keys(fieldErrors).length === 1 ? 'field' : 'fields'} above.
            </p>
          ) : null}
        </form>
      </Drawer>
    </>
  );
}
