import { Globe, Mail, MessageCircle, MessageSquare, Phone, Users } from 'lucide-react';
import { cn } from './cn';

/**
 * Which way a customer reached us, or we reached them.
 *
 * One of the few places an icon earns its space: in a conversation list the
 * channel is scanned rather than read, and "WhatsApp" spelled out in every row
 * is four times the width for the same fact. It always ships with a text label
 * for anyone who cannot see it - the icon is recognition, not the information.
 *
 * No brand colours. A green WhatsApp glyph beside a blue email glyph turns a
 * calm list into a set of logos, and the channel is not the most important thing
 * in the row - the business is.
 */

const CHANNELS = {
  whatsapp: { Icon: MessageCircle, label: 'WhatsApp' },
  sms: { Icon: MessageSquare, label: 'SMS' },
  email: { Icon: Mail, label: 'Email' },
  call: { Icon: Phone, label: 'Call' },
  phone: { Icon: Phone, label: 'Call' },
  voice: { Icon: Phone, label: 'Call' },
  meeting: { Icon: Users, label: 'Meeting' },
  web_chat: { Icon: Globe, label: 'Web chat' },
  webchat: { Icon: Globe, label: 'Web chat' },
  web_form: { Icon: Globe, label: 'Web form' },
} as const;

export function channelLabel(channel: string): string {
  return CHANNELS[channel as keyof typeof CHANNELS]?.label ?? channel.replace(/_/g, ' ');
}

export function ChannelIcon({
  channel,
  size = 15,
  className = '',
  /** Off where the row already names the channel in words. */
  withLabel = false,
}: {
  channel: string;
  size?: number;
  className?: string;
  withLabel?: boolean;
}): JSX.Element {
  const entry = CHANNELS[channel as keyof typeof CHANNELS];
  const label = channelLabel(channel);

  if (!entry) {
    // An unrecognised channel is named rather than given a guessed glyph.
    return <span className={cn('text-muted-foreground', className)}>{label}</span>;
  }

  const { Icon } = entry;
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-muted-foreground', className)}>
      <Icon size={size} strokeWidth={1.75} aria-hidden="true" />
      {withLabel ? <span>{label}</span> : <span className="sr-only">{label}</span>}
    </span>
  );
}
