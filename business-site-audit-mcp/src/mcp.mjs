import { McpServer } from '@modelcontextprotocol/server';
import { z } from 'zod';
import { runAudit } from '../lib/audit.mjs';
import { createPublicFetch } from './public-fetch.mjs';

export const VERSION = '1.1.2';

const findingSchema = z.object({
  id: z.string(),
  priority: z.enum(['blocking', 'important', 'improvement']),
  title: z.string(),
  observed: z.string(),
  source_url: z.string().url(),
  fix: z.string(),
});

const outputSchema = {
  kind: z.literal('business-site-audit'),
  version: z.literal(VERSION),
  target: z.string().url(),
  checked_at: z.string().datetime(),
  status: z.enum(['inconclusive', 'homepage_unavailable', 'partial', 'observed']),
  summary: z.string(),
  top_actions: z.array(findingSchema),
  findings: z.array(findingSchema),
  unknown_checks: z.array(z.object({ check: z.string(), reason: z.string() })),
  observed_page: z.object({
    url: z.string().url(), http_status: z.number().int().nullable(),
    title: z.string().nullable(), description: z.string().nullable(),
    canonical: z.string().nullable(), json_ld_types: z.array(z.string()),
    error: z.string().nullable(),
  }),
  observed_discovery: z.object({
    robots_status: z.number().int().nullable(), sitemap_url: z.string().url(),
    sitemap_status: z.number().int().nullable(), sitemap_entries_seen: z.number().int(),
    blocked_crawlers: z.record(z.string(), z.object({
      kind: z.string(), verdict: z.literal('blocked'), matchedBy: z.string(),
      rule: z.string().optional(),
    })).nullable(),
  }),
  method: z.object({ scope: z.string(), fetches: z.number().int(), max_fetches: z.number().int() }),
};

export function createServer({ fetchImpl = createPublicFetch() } = {}) {
  const server = new McpServer({ name: 'business-site-audit', version: VERSION }, {
    instructions: 'Audit only public business webpages. Cite observed source URLs and fixes. Treat failed probes as unknown. The tool does not measure rankings, traffic, conversions, or browser-rendered content.'
  });
  server.registerTool('audit_business_site', {
    title: 'Audit business website',
    description: 'Inspect one public business webpage, robots.txt, and sitemap. Return dated HTTP evidence, prioritized fixes, and unknown checks. Use when an owner asks what technical crawl or indexing problems their site has.',
    inputSchema: { url: z.string().min(4).max(2048).describe('Public HTTP or HTTPS webpage URL, or a public domain name') },
    outputSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: true },
  }, async ({ url }) => {
    try {
      const report = await runAudit(url, { fetchImpl });
      return { structuredContent: report, content: [{ type: 'text', text: JSON.stringify(report) }] };
    } catch (error) {
      return { isError: true, content: [{ type: 'text', text: JSON.stringify({ error: error?.code ?? 'audit_failed', message: String(error?.message ?? error).slice(0, 180) }) }] };
    }
  });
  return server;
}
