/**
 * Client-side permission helpers. These drive presentation only - the server
 * re-checks every action, and hiding a control is never the security boundary.
 */
export type Permission = `${string}:${string}`;

export interface Principal {
  readonly userId: string;
  readonly tenantId: string;
  readonly roles: readonly string[];
  readonly permissions: ReadonlySet<Permission>;
  readonly scope: 'global' | 'branch' | 'team' | 'self';
  readonly mfaVerified: boolean;
}

export const can = (principal: Principal, resource: string, action: string): boolean =>
  principal.permissions.has(`${resource}:${action}` as Permission);

export const canAny = (
  principal: Principal,
  pairs: readonly (readonly [string, string])[],
): boolean => pairs.some(([resource, action]) => can(principal, resource, action));

/** Operations that require re-authentication before the UI should even offer them. */
export const STEP_UP_OPERATIONS = new Set([
  'billing.update',
  'subscription.checkout',
  'export.create',
  'tenant.delete',
  'tenant.transfer_ownership',
  'api_key.create',
  'security.settings',
  'payment.refund_high_value',
]);

export const needsStepUp = (principal: Principal, operation: string): boolean =>
  STEP_UP_OPERATIONS.has(operation) && !principal.mfaVerified;
