// A private, read-only YAML endpoint. Never log request URLs or config contents.
const encoder = new TextEncoder();
const headers = {
  'Cache-Control': 'private, no-store',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
};
function failure(status = 404) {
  return new Response(status === 404 ? 'Not found' : 'Unavailable', { status, headers });
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!['GET', 'HEAD'].includes(request.method)) return failure();
    const match = /^\/mihomo\/([A-Za-z0-9][A-Za-z0-9_-]{0,63})\.yaml$/.exec(url.pathname);
    const token = url.searchParams.get('token');
    if (!match || !token || !/^[A-Za-z0-9_-]{43}$/.test(token) ||
        url.searchParams.getAll('token').length !== 1 || !/^[a-f0-9]{64}$/.test(env.TOKEN_SHA256 || '')) return failure();
    const provided = await crypto.subtle.digest('SHA-256', encoder.encode(token));
    const expected = Uint8Array.from(env.TOKEN_SHA256.match(/../g), b => parseInt(b, 16));
    if (!crypto.subtle.timingSafeEqual(provided, expected)) return failure();
    try {
      // Bindings keep objects private; there is no public bucket or list route.
      const config = await env.CONFIGS.get(`mihomo/${match[1]}.yaml`, 'arrayBuffer');
      if (config === null) return failure();
      const digest = await crypto.subtle.digest('SHA-256', config);
      const etag = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
      return new Response(request.method === 'HEAD' ? null : config, {
        headers: { ...headers, 'Content-Type': 'application/yaml; charset=utf-8',
          'Content-Disposition': `attachment; filename="${match[1]}.yaml"`,
          'ETag': `"${etag}"`, 'profile-update-interval': '24' },
      });
    } catch {
      // No exception text: storage errors must not disclose state or credentials.
      return failure(503);
    }
  },
};
