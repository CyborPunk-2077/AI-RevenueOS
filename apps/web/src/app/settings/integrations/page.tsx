import { apiFetch } from '@/lib/session';
import { DataTable, type Column } from '@/features/ui/data-table';
import { PageHeader, SectionHeader } from '@/features/ui/primitives';
import { StatusText, type Severity } from '@/features/ui/status';
import { formatDateTime } from '@/lib/dates';

export const dynamic = 'force-dynamic';

/**
 * What each capability can actually do, and what it is waiting for.
 *
 * The value of this screen is that it never flatters the product. The founders
 * sell against tools that show a green tick for a channel which has never
 * delivered anything, so the honesty is a feature.
 *
 * **It was, however, being honest about the wrong question.** One boolean -
 * `ready` - was answering five, and the result was a page that said "credentials
 * not recorded", "Needs activation" and "Live activation claimed: No" about
 * WhatsApp while a real customer conversation was open in the next tab. Every one
 * of those sentences was true. None of them was the thing the reader wanted to
 * know, which is simply: can this channel send and receive right now, and what
 * happened last time it tried?
 *
 * So the five are kept apart, each derived from its own evidence:
 *
 * - **Runtime connection** - the deployed adapter reports itself configured. This
 *   is what decides whether a send is even attempted.
 * - **Stored configuration** - whether this workspace holds its own encrypted
 *   copy. Usually not, on a single-tenant deployment, and that is not a fault.
 * - **Webhook** - an inbound message is proof the provider reached us. Nothing
 *   else on this page is proof of that.
 * - **Outbound** - the status and error of the last real send attempt, in the
 *   provider's own words.
 * - **Production activation** - the commercial and legal gate. Always false until
 *   external approval evidence exists, and never inferred from the four above.
 *
 * The other change is that seven unconfigured providers no longer render as seven
 * rows of failure. What Sangam can genuinely do today sits at the top; the rest is
 * a quiet catalogue underneath, so the product reads as focused rather than
 * broken.
 */

interface Activity {
  readonly last_inbound_at: string | null;
  readonly last_outbound_at: string | null;
  readonly last_outbound_status: string | null;
  readonly last_outbound_error: string | null;
}

interface ProviderConfiguration {
  readonly id: string | null;
  readonly kind: 'channel' | 'integration';
  readonly provider: string;
  readonly identifier: string;
  readonly display_name: string;
  readonly settings: Readonly<Record<string, string | boolean | number>>;
  readonly credentials_present: boolean;
  readonly credential_fields: readonly string[];
  readonly ready: boolean;
  readonly status: 'ready' | 'pending_activation' | 'not_configured';
  readonly activation_issues: readonly string[];
  readonly version: number;
  readonly runtime_credentials_present: boolean;
  readonly stored_credentials_present: boolean;
  readonly configuration_source: 'deployment' | 'workspace' | 'none';
  readonly activity: Activity;
  readonly production_activation: boolean;
}

interface ConfigurationResponse {
  readonly configurations: readonly ProviderConfiguration[];
  readonly live_activation_claimed: false;
}

/**
 * Provider names as their owners spell them.
 *
 * Title-casing the database key produced "Whatsapp" and "Sms" on the one screen
 * whose whole job is to look trustworthy about providers.
 */
const DISPLAY_NAMES: Record<string, string> = {
  whatsapp: 'WhatsApp',
  sms: 'SMS',
  web_chat: 'Web chat',
  google_calendar: 'Google Calendar',
};

const label = (value: string): string =>
  DISPLAY_NAMES[value] ??
  value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

/** One named fact, its tone, and the evidence it came from. */
interface Fact {
  readonly name: string;
  readonly value: string;
  readonly tone: Severity;
  readonly detail?: string;
}

/**
 * The four questions, answered from evidence rather than from one another.
 *
 * Deliberately not a lookup of hardcoded sentences. Every string below is chosen
 * by a value the server measured, and the neutral tone is the default: a channel
 * that has simply never been used is not a channel that is failing.
 */
function factsFor(item: ProviderConfiguration): Fact[] {
  const { activity } = item;
  const facts: Fact[] = [
    {
      name: 'Runtime connection',
      value: item.runtime_credentials_present ? 'Configured' : 'Not configured',
      tone: item.runtime_credentials_present ? 'positive' : 'neutral',
      detail:
        item.configuration_source === 'deployment'
          ? 'Credentials come from the deployment, not from this workspace.'
          : item.configuration_source === 'workspace'
            ? 'Credentials are stored encrypted in this workspace.'
            : undefined,
    },
  ];

  if (item.kind === 'channel') {
    facts.push({
      name: 'Webhook',
      value: activity.last_inbound_at ? 'Inbound received' : 'No inbound received yet',
      tone: activity.last_inbound_at ? 'positive' : 'neutral',
      detail: activity.last_inbound_at
        ? `Last message from a customer ${formatDateTime(activity.last_inbound_at)}.`
        : 'Nothing has arrived on this channel, so the provider has not been observed reaching Sangam.',
    });

    const failed = activity.last_outbound_status === 'failed';
    const queued = activity.last_outbound_status === 'queued';
    facts.push({
      name: 'Outbound',
      value: !activity.last_outbound_at
        ? 'Nothing sent yet'
        : failed
          ? 'Last send failed'
          : queued
            ? 'Held — not sent'
            : `Last send ${activity.last_outbound_status}`,
      // Only a genuine provider rejection is critical. "Nothing sent yet" is not
      // a problem, and painting it red is how the one real failure gets lost.
      tone: failed
        ? 'critical'
        : queued
          ? 'warning'
          : activity.last_outbound_at
            ? 'positive'
            : 'neutral',
      detail: activity.last_outbound_at
        ? [
            formatDateTime(activity.last_outbound_at),
            activity.last_outbound_error ? `Provider said: ${activity.last_outbound_error}` : null,
          ]
            .filter(Boolean)
            .join(' · ')
        : undefined,
    });
  }

  facts.push({
    name: 'Production activation',
    value: item.production_activation ? 'Enabled' : 'Not enabled',
    tone: 'neutral',
    detail:
      'Commercial, legal and provider approval. Recorded separately and never inferred from the state above.',
  });

  return facts;
}

function CapabilityPanel({ item }: { item: ProviderConfiguration }): JSX.Element {
  const facts = factsFor(item);
  return (
    <section
      data-testid={`capability-${item.provider}`}
      className="rounded-lg border border-border bg-surface"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-4 py-3">
        <h3 className="text-[15px] font-semibold text-foreground">{label(item.provider)}</h3>
        <p className="text-[13px] text-muted-foreground">
          {item.kind} · {item.identifier}
        </p>
      </header>

      <dl className="divide-y divide-border">
        {facts.map((fact) => (
          <div
            key={fact.name}
            className="grid gap-x-4 gap-y-0.5 px-4 py-2.5 min-[720px]:grid-cols-[11rem_minmax(0,1fr)]"
          >
            <dt className="text-[13px] text-muted-foreground">{fact.name}</dt>
            <dd>
              <StatusText tone={fact.tone}>{fact.value}</StatusText>
              {fact.detail ? (
                <span className="mt-0.5 block text-[13px] text-muted-foreground">
                  {fact.detail}
                </span>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default async function IntegrationSettingsPage(): Promise<JSX.Element> {
  const result = await apiFetch<ConfigurationResponse>('/integrations');
  if (!result.ok || !result.data) {
    return (
      <p
        role="alert"
        className="max-w-reading rounded border border-critical/40 bg-critical-soft px-3 py-2 text-sm text-critical"
      >
        {result.error ?? 'Integration settings are unavailable.'}
      </p>
    );
  }

  const all = [...result.data.configurations];

  /*
   * "In use" means observed, not merely declared.
   *
   * A capability earns the top of the page by having a runtime credential, a
   * stored configuration, or traffic that actually happened. Everything else is
   * a catalogue entry - which is what it is, and it should not look like a
   * failing system.
   */
  const inUse = all.filter(
    (item) =>
      item.runtime_credentials_present ||
      item.stored_credentials_present ||
      item.activity.last_inbound_at !== null ||
      item.activity.last_outbound_at !== null,
  );
  const notConfigured = all.filter((item) => !inUse.includes(item));

  const catalogue: Array<Column<ProviderConfiguration>> = [
    {
      key: 'capability',
      header: 'Capability',
      width: '30%',
      cell: (item) => <span className="font-medium text-foreground">{label(item.provider)}</span>,
    },
    {
      key: 'kind',
      header: 'Kind',
      width: '20%',
      cell: (item) => <span className="text-muted-foreground">{item.kind}</span>,
    },
    {
      key: 'needs',
      header: 'Before it can be switched on',
      width: '50%',
      cell: (item) => (
        <span className="block text-secondary-foreground">
          {item.activation_issues.length > 0
            ? item.activation_issues.join('; ')
            : 'A provider account and credentials.'}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Integrations"
        description="Credentials are encrypted and never displayed. Each capability is reported on four separate axes, because a saved credential is not a working channel and a working channel is not a production activation."
      />

      <section className="space-y-3" data-testid="integration-readiness">
        <SectionHeader
          title="In use"
          description="Connection, webhook and outbound state, each derived from its own evidence."
        />
        {inUse.length === 0 ? (
          <p className="max-w-reading text-[13px] text-muted-foreground">
            No capability has a runtime credential, a stored configuration or any recorded traffic.
          </p>
        ) : (
          <div className="grid gap-4 min-[1200px]:grid-cols-2">
            {inUse.map((item) => (
              <CapabilityPanel
                key={`${item.kind}:${item.provider}:${item.identifier}`}
                item={item}
              />
            ))}
          </div>
        )}
      </section>

      {/*
        The most important sentence on the screen, and the one it would be
        easiest to quietly drop. It sits *after* the state above rather than
        before it, because as a banner it was read as a verdict on the whole page
        - including on the channel that was demonstrably working.
      */}
      <div
        role="note"
        data-testid="activation-disclaimer"
        className="max-w-reading rounded border border-border-strong bg-surface-sunken px-3.5 py-2.5"
      >
        <p className="text-[13px] font-medium text-foreground">Live activation claimed: No.</p>
        <p className="mt-1 text-[13px] text-secondary-foreground">
          A channel above may be sending and receiving on a development or test provider. That is
          not the same as production activation, which needs the provider runbook completed and
          external approval evidence on file.
        </p>
      </div>

      {notConfigured.length > 0 ? (
        <section
          className="space-y-3 border-t border-border pt-6"
          data-testid="integration-catalogue"
        >
          <SectionHeader
            title="Not configured"
            description="Sangam can carry these once a provider account exists. Nothing here is broken; none of it is switched on."
          />
          <DataTable
            caption="Capabilities that are not configured, and what each one needs first"
            columns={catalogue}
            rows={notConfigured}
            rowKey={(item) => `${item.kind}:${item.provider}:${item.identifier}`}
            stickyHeader={false}
          />
        </section>
      ) : null}
    </div>
  );
}
