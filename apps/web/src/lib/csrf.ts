/**
 * Double-submit CSRF. The BFF sets a readable token cookie at sign-in and rejects
 * any unsafe request whose header does not match it.
 */
export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)(?:__Host-)?airev-csrf=([^;]+)/);
  return match?.[1] ?? '';
}

/** fetch() for mutations, with the CSRF header attached. */
export async function mutate(
  path: string,
  init: { method: string; body?: unknown; ifMatch?: number },
): Promise<Response> {
  const headers: Record<string, string> = {
    'content-type': 'application/json',
    'x-csrf-token': csrfToken(),
  };
  if (init.ifMatch !== undefined) headers['if-match'] = `W/"${init.ifMatch}"`;

  return fetch(path, {
    method: init.method,
    headers,
    credentials: 'same-origin',
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
}
