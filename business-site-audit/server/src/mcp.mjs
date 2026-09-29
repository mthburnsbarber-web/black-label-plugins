import { McpServer } from '@modelcontextprotocol/server';
import { z } from 'zod';
import { runAudit } from '../lib/audit.mjs';
import { createPublicFetch } from './public-fetch.mjs';

export const VERSION = '1.1.0';

export function createServer({ fetchImpl = createPublicFetch() } = {}) {
  const server = new McpServer({ name: 'business-site-audit', version: VERSION }, {
    instructions: 'Audit only public business webpages. Cite observed source URLs and fixes. Treat failed probes as unknown. The tool does not measure rankings, traffic, conversions, or browser-rendered content.'
  });
  server.registerTool('audit_business_site', {
    title: 'Audit business website',
    description: 'Inspect one public business webpage, robots.txt, and sitemap. Return dated HTTP evidence, prioritized fixes, and unknown checks. Use when an owner asks what technical crawl or indexing problems their site has.',
    inputSchema: { url: z.string().min(4).max(2048).describe('Public HTTP or HTTPS webpage URL, or a public domain name') },
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
