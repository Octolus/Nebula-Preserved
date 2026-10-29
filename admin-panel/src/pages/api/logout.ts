import type { APIRoute } from 'astro';
import { cookieName, validCsrf } from '../../lib/security';
export const POST: APIRoute = async ({ request, cookies, locals }) => {
  if (!validCsrf(request, locals.session)) return new Response(null, { status: 403 });
  cookies.delete(cookieName, { path: '/' });
  return Response.json({ ok: true });
};
