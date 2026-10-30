import type { APIRoute } from 'astro';
import { catalogPreview } from '../../../lib/catalog-preview';

// Middleware verifies the signed session and the live operator before this
// endpoint runs. The private, read-only pack is deliberately outside public/.
export const GET: APIRoute = async ({ params, locals, request }) => {
  if (!locals.session || !locals.actor?.id) return new Response(null, { status: 401 });
  const preview = await catalogPreview(params.key || '', process.env.NEBULA_CATALOG_PREVIEW_DIR);
  if (!preview) return new Response(null, { status: 404 });
  const headers = {
    'Content-Type': 'image/webp',
    'X-Content-Type-Options': 'nosniff',
    'Cache-Control': 'private, no-store',
    ETag: preview.etag,
  };
  if (request.headers.get('If-None-Match') === preview.etag)
    return new Response(null, { status: 304, headers });
  return new Response(new Uint8Array(preview.bytes), { headers });
};
