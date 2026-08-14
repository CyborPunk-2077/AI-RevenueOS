/**
 * Who a prospect record is about.
 *
 * **The trap this exists to close.** `new-lead-form` sets `first_name = person ||
 * company`. When a business is added with no named contact - the common case for
 * a prospecting list - the company name is stored in the contact-name field, and
 * `capture.name_is_business = true` is written to say so.
 *
 * Three consequences, and all three are presentation rules rather than data
 * migrations. The storage stays exactly as it is:
 *
 * - A row leads with the **business**: `capture.company` when present, otherwise
 *   `first_name`.
 * - The **contact is empty, not duplicated**. Printing the same string in the
 *   business and contact columns is the precise confusion this module exists to
 *   prevent, and it quietly teaches somebody that the business is a person.
 * - Business, primary contact and internal owner are **three different facts**.
 *   A row where all three are the same person is a bug.
 *
 * One copy, because three screens had three copies of this reasoning and only
 * two of them had it right.
 */

export interface IdentifiableLead {
  readonly first_name: string;
  readonly last_name: string | null;
  readonly capture: Record<string, unknown> | null;
}

/** A captured field, or null when it is absent or blank. */
export function captureText(
  capture: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  const value = capture?.[key];
  return value === undefined || value === null || value === '' ? null : String(value);
}

export function identifyLead(lead: IdentifiableLead): {
  business: string;
  contact: string | null;
} {
  const company = captureText(lead.capture, 'company');
  const person = [lead.first_name, lead.last_name].filter(Boolean).join(' ').trim();
  const nameIsBusiness = lead.capture?.name_is_business === true;

  if (company) {
    // The contact is returned only when it is genuinely a different fact from
    // the business - never as a duplicate, and never invented to fill a column.
    return { business: company, contact: nameIsBusiness || !person ? null : person };
  }
  return { business: person || 'Unnamed record', contact: null };
}
