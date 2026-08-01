/**
 * Tenant context. Every query key carries the tenant id, so switching tenants
 * cannot serve another organisation's cached data.
 */
export type TenantId = string & { readonly __brand: 'TenantId' };

export interface TenantContext {
  readonly id: TenantId;
  readonly slug: string;
  readonly name: string;
  readonly timezone: string;
  readonly currency: 'INR' | 'USD' | 'AED';
  readonly locale: string;
  readonly branding: Readonly<{ logoUrl?: string; primaryColor?: string }>;
}

export const asTenantId = (value: string): TenantId => value as TenantId;

/** React Query stale times, in milliseconds, exactly as specified. */
export const STALE_TIME = {
  profile: 5 * 60_000,
  tenant: 5 * 60_000,
  lead: 30_000,
  deal: 30_000,
  contact: 60_000,
  conversation: 15_000,
  message: 30_000,
  appointment: 60_000,
  document: 2 * 60_000,
  analytics: 5 * 60_000,
  settings: 10 * 60_000,
  audit: 2 * 60_000,
  workflow: 5 * 60_000,
} as const;

export type Resource = keyof typeof STALE_TIME;

/**
 * Query keys are always `[tenantId, resource, ...rest]`. A key without a tenant
 * id is a defect and is rejected at development time.
 */
export const queryKey = (
  tenantId: TenantId,
  resource: Resource,
  ...rest: readonly (string | number | Record<string, unknown>)[]
): readonly unknown[] => {
  if (!tenantId) {
    throw new Error('every query key must be scoped to a tenant');
  }
  return [tenantId, resource, ...rest];
};

export const staleTimeFor = (resource: Resource): number => STALE_TIME[resource];
