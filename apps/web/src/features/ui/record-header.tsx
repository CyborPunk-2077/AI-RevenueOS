import type { ReactNode } from 'react';
import { Avatar } from './avatar';
import { cn } from './cn';

/**
 * The header of a record page.
 *
 * The one thing it exists to get right is that **a business, the person at it,
 * and the colleague who owns it are three different facts.** `new-lead-form`
 * stores the company name in the contact-name field when no human was supplied
 * and marks it with `capture.name_is_business`; a header that ignores that
 * marker prints the same string twice and quietly teaches somebody that the
 * business is a person. So the subject is the business, the metadata line beneath
 * carries the contact and the ways to reach them, and where there is no contact
 * it says so rather than repeating the name.
 */

export interface MetaFact {
  key: string;
  label: string;
  value: ReactNode;
  testId?: string;
}

export function RecordHeader({
  subject,
  subjectTestId,
  marker,
  facts,
  actions,
  className = '',
}: {
  /** The business. Always the `h1`. */
  subject: string;
  subjectTestId?: string;
  /** A sample marker or workspace note, where one applies. */
  marker?: ReactNode;
  facts: MetaFact[];
  actions?: ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <header className={cn('border-b border-border pb-5', className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 items-start gap-3">
          <Avatar name={subject} size="lg" className="mt-0.5" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1
                data-testid={subjectTestId}
                className="text-2xl font-semibold leading-[30px] tracking-[-0.01em] text-foreground"
              >
                {subject}
              </h1>
              {marker}
            </div>

            {/*
              A definition list, because these are labelled facts and a screen
              reader should hear "Primary contact: Amit Patel" rather than four
              strings separated by dots.
            */}
            <dl className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1.5">
              {facts.map((fact) => (
                <div key={fact.key} className="flex items-baseline gap-1.5">
                  <dt className="text-[13px] text-muted-foreground">{fact.label}</dt>
                  <dd data-testid={fact.testId} className="text-[13px] text-foreground">
                    {fact.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>

        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
