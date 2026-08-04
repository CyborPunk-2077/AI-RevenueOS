import { apiFetch } from '@/lib/session';
import { WidgetSettingsForm, type WidgetSettings } from '@/features/webchat/widget-settings-form';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Web chat' };

export default async function WebchatSettingsPage(): Promise<JSX.Element> {
  const result = await apiFetch<{ widget: WidgetSettings | null }>('/webchat/widget');
  const widget = result.data?.widget ?? null;

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold">Web chat</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The one channel you can switch on yourself. WhatsApp, email, SMS, voice and payments each
          need credentials and approval from an outside provider; web chat needs only the list of
          sites allowed to show it.
        </p>
      </section>

      <WidgetSettingsForm widget={widget} />
    </div>
  );
}
