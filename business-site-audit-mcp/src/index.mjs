import { createMcpHandler } from 'agents/mcp/server';
import { createServer, VERSION } from './mcp.mjs';

const handler = createMcpHandler(() => createServer(), {
  route: '/mcp',
  allowedHostnames: ['audit-mcp.blacklabelbots.com'],
});

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET') {
      return Response.json({ name: 'business-site-audit', version: VERSION, status: 'ok' }, { headers: { 'cache-control': 'no-store' } });
    }
    if (url.pathname !== '/mcp') return new Response('Not found', { status: 404 });
    if (!env?.AUDIT_RATE_LIMITER) return new Response('Rate limiter unavailable', { status: 503 });
    const actor = request.headers.get('CF-Connecting-IP') ?? 'local-unknown';
    const { success } = await env.AUDIT_RATE_LIMITER.limit({ key: actor });
    if (!success) return new Response('Rate limit exceeded', { status: 429, headers: { 'retry-after': '60' } });
    return handler(request, env, ctx);
  },
};
