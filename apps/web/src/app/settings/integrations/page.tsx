import { apiFetch } from '@/lib/session';
import { Button } from '@/features/ui/controls';
import { DataTable, type Column } from '@/features/ui/data-table';
import { PageHeader, SectionHeader } from '@/features/ui/primitives';
import { StatusText, type Severity } from '@/features/ui/status';

export const dynamic = 'force-dynamic';

/**
 * What each capability can actually do, and what it is waiting for.
 *
 * The whole value of this screen is that it never flatters the product. A saved
 * credential is not an activated provider; a configured channel is not a channel
 * with a verified sending domain or an approved template. Every row states the
 * real external prerequisite in a sentence, because that honesty is a product
 * feature - the founders sell against tools that show a green tick for a channel
 * that has never delivered anything.
 */

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
}

interface ConfigurationResponse {
  readonly configurations: readonly ProviderConfiguration[];
  readonly live_activation_claimed: false;
}

const label = (value: string): string =>
  value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

/** Three words, and each one means something different. */
const STATUS_WORD: Record<ProviderConfiguration['status'], string> = {
  ready: 'Connected',
  pending_activation: 'Needs activation',
  not_configured: 'Not configured',
};

const STATUS_TONE: Record<ProviderConfiguration['status'], Severity> = {
  ready: 'positive',
  // Not critical: an unconfigured channel is not broken, it is simply switched
  // off. Painting every gated capability red would make the one that genuinely
  // errored impossible to find.
  pending_activation: 'warning',
  not_configured: 'neutral',
};

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

  const rows = [...result.data.configurations];

  const columns: Array<Column<ProviderConfiguration>> = [
    {
      key: 'capability',
      header: 'Capability',
      width: '26%',
      cell: (item) => (
        <span className="block">
          <span className="block truncate font-medium text-foreground">
            {label(item.provider)}
          </span>
          <span className="block truncate text-[13px] text-muted-foreground">
            {item.kind} · {item.identifier}
          </span>
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      width: '18%',
      cell: (item) => (
        <StatusText tone={STATUS_TONE[item.status]}>{STATUS_WORD[item.status]}</StatusText>
      ),
    },
    {
      key: 'needs',
      header: 'What it needs',
      width: '38%',
      cell: (item) =>
        item.activation_issues.length > 0 ? (
          <span className="block text-secondary-foreground">
            {item.activation_issues.join('; ')}
          </span>
        ) : item.ready ? (
          <span className="text-muted-foreground">Nothing — this one works.</span>
        ) : (
          <span className="text-muted-foreground">
            A provider account and credentials for this channel.
          </span>
        ),
    },
    {
      key: 'credentials',
      header: 'Credentials',
      width: '18%',
      dropAt: 1100,
      cell: (item) => (
        <span className="block text-[13px] text-muted-foreground">
          {item.credentials_present ? 'Stored securely' : 'Not recorded'}
          {item.credential_fields.length > 0 ? (
            <span className="mt-0.5 block truncate" title={item.credential_fields.map(label).join(', ')}>
              {item.credential_fields.map(label).join(', ')}
            </span>
          ) : null}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Integrations"
        description="Credentials are encrypted and never displayed. A saved configuration is not proof of provider, DNS, commercial, legal or production activation."
      />

      {/*
        The most important sentence on the screen, and the one it would be
        easiest to quietly drop. Nothing below has been activated for real
        traffic, and the page says so before it says anything else.
      */}
      <div
        role="note"
        data-testid="activation-disclaimer"
        className="max-w-reading rounded border border-border-strong bg-surface-sunken px-3.5 py-2.5"
      >
        <p className="text-[13px] font-medium text-foreground">Live activation claimed: No.</p>
        <p className="mt-1 text-[13px] text-secondary-foreground">
          Complete the provider activation runbook and enable the deployment feature flag only after
          external approval evidence exists.
        </p>
      </div>

      <section className="space-y-3" data-testid="integration-readiness">
        <SectionHeader
          title="Capabilities"
          description="What each one can do today, and the external thing it is waiting for."
        />
        <DataTable
          caption="Integration capabilities, their status and what each one needs"
          columns={columns}
          rows={rows}
          rowKey={(item) => `${item.kind}:${item.provider}:${item.identifier}`}
          stickyHeader={false}
        />
      </section>

      <section className="space-y-2 border-t border-border pt-6">
        <SectionHeader
          title="Activation"
          description="Activation stays disabled until deployment and the external gates above are verified. There is no button here that would make a channel work sooner."
        />
        <Button variant="secondary" disabled>
          Activate a provider
        </Button>
      </section>
    </div>
  );
}
