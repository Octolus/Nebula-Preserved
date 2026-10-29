import { defineMiddleware } from 'astro:middleware';
import { cookieName, verify, csrf } from './lib/security';
import { management, ManagementError } from './lib/management';
export const onRequest = defineMiddleware(async (context, next) => {
  const path = context.url.pathname;
  const publicPath = path === '/login' || path === '/api/login' || path === '/health';
  if (!publicPath) {
    const session = verify(context.cookies.get(cookieName)?.value);
    if (!session)
      return path.startsWith('/api/')
        ? Response.json({ error: { message: 'Sign in required' } }, { status: 401 })
        : context.redirect('/login', 303);
    try {
      const actor = await management('/me', session.id);
      context.locals.session = session;
      context.locals.actor = actor;
      context.locals.csrf = csrf(session);
    } catch (error) {
      const revoked = error instanceof ManagementError && [401, 403].includes(error.status);
      if (revoked) context.cookies.delete(cookieName, { path: '/' });
      if (path.startsWith('/api/'))
        return Response.json(
          {
            error: {
              message: revoked ? 'Operator access revoked' : 'Management service unavailable',
            },
          },
          { status: revoked ? 401 : 503, headers: { 'Cache-Control': 'no-store' } },
        );
      if (revoked) return context.redirect('/login', 303);
      return new Response('Management service unavailable.', {
        status: 503,
        headers: { 'Cache-Control': 'no-store' },
      });
    }
  }
  const response = await next();
  response.headers.set('Cache-Control', 'no-store');
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Referrer-Policy', 'same-origin');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  );
  return response;
});
