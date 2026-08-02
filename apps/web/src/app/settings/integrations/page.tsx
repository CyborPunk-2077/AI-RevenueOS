import { apiFetch } from '@/lib/session';

export const dynamic = 'force-dynamic';

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

export default async function IntegrationSettingsPage(): Promise<JSX.Element> {
  const result = await apiFetch<ConfigurationResponse>('/integrations');
  if (!result.ok || !result.data) {
    return (
      <p role="alert" className="rounded border border-destructive p-4 text-sm text-destructive">
        {result.error ?? 'Integration settings are unavailable.'}
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold">Integrations</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Credentials are encrypted and never displayed. A saved configuration is not proof of
          provider, DNS, commercial, legal, or production activation.
        </p>
      </section>

      <p className="rounded border border-dashed p-3 text-sm text-muted-foreground" data-testid="activation-disclaimer">
        Live activation claimed: <strong>No</strong>. Complete the provider activation runbook and
        enable the deployment feature flag only after external approval evidence exists.
      </p>

      <div className="grid gap-4 md:grid-cols-2" data-testid="integration-readiness">
        {result.data.configurations.map((item) => (
          <article key={`${item.kind}:${item.provider}:${item.identifier}`} className="rounded border p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-medium">{label(item.provider)}</h2>
                <p className="text-xs text-muted-foreground">{item.kind} · {item.identifier}</p>
              </div>
              <span className={item.ready ? 'text-sm text-green-700' : 'text-sm text-amber-700'}>
                {label(item.status)}
              </span>
            </div>
            <p className="mt-3 text-sm">
              Credentials: {item.credentials_present ? 'stored securely' : 'not recorded'}
            </p>
            {item.credential_fields.length > 0 ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Stored fields: {item.credential_fields.map(label).join(', ')}. Values are never returned.
              </p>
            ) : null}
            {item.activation_issues.length > 0 ? (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {item.activation_issues.map((issue) => <li key={issue}>{issue}</li>)}
              </ul>
            ) : null}
            <button
              type="button"
              disabled
              aria-describedby={`${item.provider}-activation-note`}
              className="mt-4 rounded border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
            >
              Activate provider
            </button>
            <p id={`${item.provider}-activation-note`} className="mt-1 text-xs text-muted-foreground">
              Activation stays disabled until deployment and external gates are verified.
            </p>
          </article>
        ))}
      </div>
    </div>
  );
}
