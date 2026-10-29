import type { APIRoute } from 'astro';
import {
  authenticate,
  allowLogin,
  cookieName,
  issue,
  lifetime,
  origin,
  sameOrigin,
  readJson,
} from '../../lib/security';
import { management } from '../../lib/management';
export const POST: APIRoute = async ({ request, cookies, clientAddress }) => {
  try {
    if (!sameOrigin(request))
      return Response.json({ error: { message: 'Origin rejected' } }, { status: 403 });
    if (!allowLogin(clientAddress))
      return Response.json(
        { error: { message: 'Too many attempts. Try again in 15 minutes.' } },
        { status: 429 },
      );
    const { id, password } = await readJson(request, 4096);
    if (
      typeof id !== 'string' ||
      id.length > 128 ||
      typeof password !== 'string' ||
      password.length > 1024 ||
      !(await authenticate(id, password))
    )
      return Response.json(
        { error: { message: 'Invalid operator ID or password' } },
        { status: 401 },
      );
    await management('/me', id);
    cookies.set(cookieName, issue(id), {
      httpOnly: true,
      secure: origin().startsWith('https:'),
      sameSite: 'strict',
      path: '/',
      maxAge: lifetime,
    });
    return Response.json({ ok: true });
  } catch {
    return Response.json(
      { error: { message: 'Sign-in service unavailable. Check server configuration.' } },
      { status: 503 },
    );
  }
};
