import { createHmac, randomBytes, scrypt, timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { promisify } from 'node:util';

const derive = promisify(scrypt);
export type Session = { id: string; exp: number; nonce: string };
export const cookieName = 'nebula_panel';
export const lifetime = 8 * 60 * 60;
export function secret(name: string) {
  const path = process.env[name];
  if (!path) throw new Error('Panel secrets are not configured');
  const value = readFileSync(path, 'utf8').trim();
  if (value.length < 32) throw new Error('Panel secret is too short');
  return value;
}
export function origin() {
  const configured = process.env.NEBULA_PANEL_ORIGIN;
  if (!configured) throw new Error('NEBULA_PANEL_ORIGIN is required');
  const url = new URL(configured);
  if (
    !['https:', 'http:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  )
    throw new Error('Invalid panel origin');
  return url.origin;
}
export function equal(a: string, b: string) {
  const x = Buffer.from(a),
    y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}
function sign(value: string) {
  return createHmac('sha256', secret('NEBULA_PANEL_SESSION_KEY_FILE'))
    .update(value)
    .digest('base64url');
}
export function issue(id: string) {
  const session: Session = {
    id,
    exp: Math.floor(Date.now() / 1000) + lifetime,
    nonce: randomBytes(24).toString('base64url'),
  };
  const body = Buffer.from(JSON.stringify(session)).toString('base64url');
  return `${body}.${sign(body)}`;
}
export function verify(value: string | undefined): Session | null {
  if (!value || value.length > 2048) return null;
  try {
    const [body, signature, ...extra] = value.split('.');
    if (extra.length || !signature || !equal(sign(body), signature)) return null;
    const s = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    if (
      typeof s.id !== 'string' ||
      !s.id ||
      typeof s.nonce !== 'string' ||
      !Number.isSafeInteger(s.exp) ||
      s.exp <= Date.now() / 1000 ||
      s.exp > Date.now() / 1000 + lifetime + 30
    )
      return null;
    return s;
  } catch {
    return null;
  }
}
export function csrf(session: Session) {
  return sign(`csrf:${session.id}:${session.nonce}`);
}
export function sameOrigin(request: Request) {
  return request.headers.get('origin') === origin();
}
export function validCsrf(request: Request, session: Session) {
  return sameOrigin(request) && equal(request.headers.get('x-csrf-token') || '', csrf(session));
}
export async function readJson(request: Request, maximum: number) {
  if (request.headers.get('content-type')?.split(';')[0].trim() !== 'application/json')
    throw new SyntaxError('JSON required');
  const reader = request.body?.getReader();
  if (!reader) throw new SyntaxError('Body required');
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) {
        await reader.cancel();
        throw new SyntaxError('Request too large');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
export async function passwordMatches(password: string, encoded: string) {
  const parts = encoded.split('$');
  if (
    parts.length !== 6 ||
    parts[0] !== 'scrypt' ||
    parts[1] !== '16384' ||
    parts[2] !== '8' ||
    parts[3] !== '1' ||
    !/^[a-f0-9]{32}$/.test(parts[4]) ||
    !/^[a-f0-9]{64}$/.test(parts[5])
  )
    return false;
  const key = (await derive(password, parts[4], 32)) as Buffer;
  return equal(key.toString('hex'), parts[5]);
}
const attempts = new Map<string, { count: number; until: number }>();
export function allowLogin(ip: string) {
  const now = Date.now();
  for (const [key, v] of attempts) if (v.until < now) attempts.delete(key);
  const previous = attempts.get(ip);
  if (previous) {
    previous.count++;
    return previous.count <= 10;
  }
  if (attempts.size >= 5000) return false;
  attempts.set(ip, { count: 1, until: now + 15 * 60 * 1000 });
  return true;
}
export async function authenticate(id: string, password: string) {
  const path = process.env.NEBULA_ADMIN_OPERATORS_FILE;
  if (!path) throw new Error('Operator file is not configured');
  const parsed = JSON.parse(readFileSync(path, 'utf8'));
  const operator = parsed.operators?.find(
    (o: { id: string; enabled: boolean }) => o.id === id && o.enabled === true,
  );
  const dummy = 'scrypt$16384$8$1$00000000000000000000000000000000$' + '0'.repeat(64);
  const matches = await passwordMatches(password, operator?.password_scrypt || dummy);
  return matches && !!operator;
}
