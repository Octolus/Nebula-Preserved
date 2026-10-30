import type { APIRoute } from 'astro';
import { management, ManagementError } from '../../../lib/management';
import { validCsrf, readJson } from '../../../lib/security';
import { allowedManagementPath, managementQuery } from '../../../lib/manage-policy';
export const ALL: APIRoute = async ({ request, params, locals, url }) => {
  try {
    const path = params.path || '';
    if (!allowedManagementPath(request.method, path)) return new Response(null, { status: 404 });
    const query = managementQuery(path, url.searchParams);
    let body: unknown;
    if (request.method === 'POST') {
      if (!validCsrf(request, locals.session))
        return Response.json(
          { error: { message: 'Request verification failed. Reload the page.' } },
          { status: 403 },
        );
      body = await readJson(request, 16384);
      if (!/^[a-zA-Z0-9-]{16,128}$/.test(request.headers.get('Idempotency-Key') || ''))
        return Response.json({ error: { message: 'Request ID required' } }, { status: 400 });
    }
    const data = await management(`/${path}${query.size ? '?' + query : ''}`, locals.session.id, {
      method: request.method,
      body,
      key: request.headers.get('Idempotency-Key') || undefined,
    });
    return Response.json({ data });
  } catch (error) {
    if (error instanceof ManagementError)
      return Response.json(
        { error: { code: error.code, message: error.message } },
        { status: error.status },
      );
    if (error instanceof SyntaxError)
      return Response.json({ error: { message: 'Invalid request data' } }, { status: 400 });
    return Response.json(
      { error: { message: 'Management service unavailable. Retry with the same request ID.' } },
      { status: 502 },
    );
  }
};
