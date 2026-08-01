/**
 * Browser-facing API client. It talks only to the Next.js BFF proxy; the browser
 * never holds an access or refresh token and never calls a provider directly.
 */
export interface ApiMeta {
  readonly request_id: string;
  readonly timestamp: string;
  readonly version: string;
  readonly pagination?: {
    readonly next_cursor: string | null;
    readonly has_more: boolean;
    readonly page_size: number;
    readonly total: number | null;
  };
}

export interface ApiSuccess<T> {
  readonly success: true;
  readonly data: T;
  readonly meta: ApiMeta;
}

export interface ApiFailure {
  readonly success: false;
  readonly error: {
    readonly code: ApiErrorCode;
    readonly message: string;
    readonly details: Record<string, unknown>;
  };
  readonly meta: ApiMeta;
}

export type ApiErrorCode =
  | 'VALIDATION_ERROR'
  | 'UNAUTHENTICATED'
  | 'TOKEN_EXPIRED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'RATE_LIMITED'
  | 'FEATURE_NOT_AVAILABLE'
  | 'QUOTA_EXCEEDED'
  | 'PROVIDER_UNAVAILABLE'
  | 'IDEMPOTENCY_CONFLICT'
  | 'PRECONDITION_FAILED'
  | 'INTERNAL_ERROR';

export class ApiError extends Error {
  constructor(
    readonly code: ApiErrorCode,
    message: string,
    readonly details: Record<string, unknown>,
    readonly status: number,
    readonly requestId: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** Errors the user can act on directly, rather than a generic failure toast. */
  get isActionable(): boolean {
    return (
      this.code === 'FEATURE_NOT_AVAILABLE' ||
      this.code === 'QUOTA_EXCEEDED' ||
      this.code === 'PRECONDITION_FAILED' ||
      this.code === 'RATE_LIMITED'
    );
  }

  /** A provider outage degrades; it must never look like data loss. */
  get isDegraded(): boolean {
    return this.code === 'PROVIDER_UNAVAILABLE';
  }
}

interface RequestOptions {
  readonly method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  readonly body?: unknown;
  readonly idempotencyKey?: string;
  readonly ifMatch?: number;
  readonly signal?: AbortSignal;
  readonly csrfToken?: string;
}

const UNSAFE = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<ApiSuccess<T>> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };

  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
  if (options.ifMatch !== undefined) headers['If-Match'] = `W/"${options.ifMatch}"`;
  // CSRF double-submit for every unsafe request through the BFF.
  if (UNSAFE.has(method) && options.csrfToken) headers['X-CSRF-Token'] = options.csrfToken;

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    // The refresh-session cookie is host-only, Secure, HttpOnly and SameSite=Lax.
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    ...(options.signal ? { signal: options.signal } : {}),
  });

  const payload = (await response.json()) as ApiSuccess<T> | ApiFailure;

  if (!payload.success) {
    throw new ApiError(
      payload.error.code,
      payload.error.message,
      payload.error.details,
      response.status,
      payload.meta.request_id,
    );
  }
  return payload;
}

export const money = (amountMinor: number, currency = 'INR'): string =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency }).format(amountMinor / 100);

export const dateInTenantZone = (iso: string, timeZone: string): string =>
  new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(
    new Date(iso),
  );
