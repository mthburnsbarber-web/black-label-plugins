# Business Site Audit MCP server

Stateless, read-only MCP endpoint for the Business Site Audit plugin. It uses Cloudflare Workers, the MCP SDK v2 handler, and the deterministic audit engine in `lib/`. `src/public-fetch.mjs` checks public DNS answers before each outbound request; the audit fetcher validates each redirect and bounds requests, time, and bytes. Cloudflare's Worker egress policy is the final private-network boundary. The Worker applies a 30-request-per-minute, per-IP rate limit.

Development: `npm ci`, `npm test`, `npm run check`, then `npx wrangler dev --local`. Production deployment: `npm run deploy`; verify `https://audit-mcp.blacklabelbots.com/health`, MCP initialization, `tools/list`, and one representative `tools/call`. The optional `bin/audit-site.mjs` CLI is for source-level maintenance, not the plugin runtime.

The public custom domain and rate-limit binding are defined in `wrangler.jsonc`. Changing the MCP tool name, schema, or data-handling behavior requires plugin version and directory disclosure updates.
