import { secret } from './security';
export class ManagementError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export async function management(
  path: string,
  actor: string,
  options: { method?: string; body?: unknown; key?: string } = {},
) {
  const configured = process.env.NEBULA_MANAGEMENT_URL;
  if (!configured) throw new Error('Management API is not configured');
  const base = new URL(configured);
  if (
    !['http:', 'https:'].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.search ||
    base.hash
  )
    throw new Error('Invalid management URL');
  const headers: Record<string, string> = {
    Authorization: `Bearer ${secret('NEBULA_ADMIN_TOKEN_FILE')}`,
    'X-Management-Actor': actor,
  };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.key) headers['Idempotency-Key'] = options.key;
  const response = await fetch(new URL(`/management/v1${path}`, base), {
    method: options.method || 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    redirect: 'error',
    signal: AbortSignal.timeout(15000),
  });
  const payload = await response.json();
  if (!response.ok)
    throw new ManagementError(
      response.status,
      payload.error?.code || 'upstream_error',
      payload.error?.message || 'Management request failed',
    );
  return payload.data;
}
