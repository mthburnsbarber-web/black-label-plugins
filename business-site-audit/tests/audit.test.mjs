import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { auditWebsite } from '../server/report.mjs';
import { isPublicAddress } from '../server/lib/network.mjs';

function fixture(routes) {
  const calls = [];
  return {
    calls,
    fetchImpl: async (url, init = {}) => {
      calls.push({ url, method: init.method ?? 'GET' });
      const row = routes[url];
      if (row instanceof Error) throw row;
      if (!row) return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain' } });
      if (row.status === 302) return new Response(null, { status: 302, headers: { location: row.location } });
      return new Response(init.method === 'HEAD' ? null : row.body, {
        status: row.status ?? 200, headers: { 'content-type': row.type ?? 'text/html', ...row.headers },
      });
    },
  };
}
const root = 'https://harborbakery.com/';
const goodHome = '<!doctype html><html lang="en"><head><title>Harbor Bakery | Fresh bread daily</title><meta name="description" content="Fresh bread, cakes and coffee made daily at Harbor Bakery for neighbors and visitors in Portland, Maine."><link rel="canonical" href="https://harborbakery.com/"><script type="application/ld+json">{"@context":"https://schema.org","@type":"Bakery","name":"Harbor Bakery"}</script></head><body><h1>Fresh bread in Portland</h1></body></html>';
const fixedClock = () => new Date('2026-09-29T00:00:00Z');

test('both marketplace entries resolve to the installable plugin directory', () => {
  const repo = fileURLToPath(new URL('../../', import.meta.url));
  const codex = JSON.parse(readFileSync(join(repo, '.agents/plugins/marketplace.json'), 'utf8'));
  const claude = JSON.parse(readFileSync(join(repo, '.claude-plugin/marketplace.json'), 'utf8'));
  const codexSource = codex.plugins.find((row) => row.name === 'business-site-audit')?.source.path;
  const claudeSource = claude.plugins.find((row) => row.name === 'business-site-audit')?.source;
  assert.equal(resolve(repo, codexSource), resolve(repo, claudeSource));
  const pluginRoot = resolve(repo, codexSource);
  assert.ok(existsSync(join(pluginRoot, 'skills/site-audit/SKILL.md')));
  const manifest = JSON.parse(readFileSync(join(pluginRoot, '.codex-plugin/plugin.json'), 'utf8'));
  const mcp = JSON.parse(readFileSync(join(pluginRoot, '.mcp.json'), 'utf8'));
  assert.equal(manifest.version, '1.1.0');
  assert.equal(manifest.mcpServers, './.mcp.json');
  assert.equal(mcp.mcpServers['business-site-audit'].type, 'http');
  assert.equal(mcp.mcpServers['business-site-audit'].url, 'https://audit-mcp.blacklabelbots.com/mcp');
  assert.equal(claude.plugins.find((row) => row.name === 'business-site-audit')?.version, '1.1.0');
  assert.ok(!existsSync(join(pluginRoot, 'skills/site-audit/scripts')));
});

test('first use audits an unrelated business and gives source-linked actions without a made-up grade', async () => {
  const site = fixture({
    [root]: { body: goodHome },
    'http://harborbakery.com/': { status: 302, location: root },
    [`${root}robots.txt`]: { body: `User-agent: *\nAllow: /\nSitemap: ${root}sitemap.xml\n`, type: 'text/plain' },
    [`${root}sitemap.xml`]: { body: `<urlset><url><loc>${root}</loc></url></urlset>`, type: 'application/xml' },
  });
  const report = await auditWebsite(root, { fetchImpl: site.fetchImpl, clock: fixedClock });
  assert.equal(report.status, 'observed');
  assert.equal(report.checked_at, '2026-09-29T00:00:00.000Z');
  assert.equal(report.observed_page.title, 'Harbor Bakery | Fresh bread daily');
  assert.equal(report.observed_discovery.sitemap_entries_seen, 1);
  assert.deepEqual(report.observed_discovery.blocked_crawlers, {});
  assert.ok(report.findings.every((f) => f.source_url.startsWith('https://harborbakery.com/') && f.fix));
  assert.ok(!('score' in report) && !('grade' in report));
  assert.ok(!report.findings.some((f) => f.id === 'llms.missing' || f.id === 'agents.no-doors'));
  assert.ok(site.calls.length <= report.method.max_fetches);
});

test('blocking noindex and crawler rules outrank optional page polish', async () => {
  const site = fixture({
    [root]: { body: '<html><head><title>Bakery</title><meta name="robots" content="noindex"></head><body><h1>Bread</h1></body></html>', headers: { 'x-robots-tag': 'noindex' } },
    [`${root}robots.txt`]: { body: 'User-agent: *\nDisallow: /\n', type: 'text/plain' },
  });
  const report = await auditWebsite(root, { fetchImpl: site.fetchImpl, clock: fixedClock });
  assert.equal(report.top_actions[0].priority, 'blocking');
  const ids = report.top_actions.map((f) => f.id);
  assert.ok(ids.includes('robots.search-blocked'));
  assert.equal(report.observed_discovery.blocked_crawlers.Googlebot.verdict, 'blocked');
  assert.ok(ids.includes('page.x-robots-noindex'));
  assert.ok(ids.includes('page.meta-noindex'));
  assert.equal(report.findings.find((f) => f.id === 'robots.search-blocked').source_url, `${root}robots.txt`);
});

test('a failed sitemap probe remains unknown instead of a verified missing sitemap', async () => {
  const site = fixture({ [root]: { body: goodHome }, [`${root}sitemap.xml`]: new Error('network down') });
  const report = await auditWebsite(root, { fetchImpl: site.fetchImpl, clock: fixedClock });
  assert.equal(report.status, 'partial');
  assert.ok(report.unknown_checks.some((x) => x.check === 'sitemap'));
  assert.ok(!report.findings.some((x) => x.id === 'sitemap.missing'));
});

test('unsafe URL and private redirect are refused before a private fetch', async () => {
  const site = fixture({ [root]: { status: 302, location: 'http://127.0.0.1/admin' } });
  await assert.rejects(auditWebsite('http://127.0.0.1', { fetchImpl: site.fetchImpl }), /private or reserved address/);
  assert.equal(site.calls.length, 0);
  const report = await auditWebsite(root, { fetchImpl: site.fetchImpl, clock: fixedClock });
  assert.equal(report.status, 'inconclusive');
  assert.ok(report.unknown_checks.some((x) => x.check === 'homepage'));
  assert.ok(!report.top_actions.some((x) => x.id === 'page.unreachable'));
  assert.ok(site.calls.every((x) => !x.url.includes('127.0.0.1')));
});

test('resolved private and reserved addresses cannot be selected for a connection', () => {
  for (const ip of ['127.0.0.1', '10.2.3.4', '169.254.169.254', '192.168.1.3', '203.0.113.1'])
    assert.equal(isPublicAddress(ip, 4), false, ip);
  assert.equal(isPublicAddress('1.1.1.1', 4), true);
  assert.equal(isPublicAddress('::1', 6), false);
  assert.equal(isPublicAddress('2606:4700:4700::1111', 6), true);
});

test('a redirect audits discovery files on the final business host', async () => {
  const finalRoot = 'https://www.harborbakery.com/';
  const site = fixture({
    [root]: { status: 302, location: finalRoot },
    [finalRoot]: { body: goodHome },
    [`${finalRoot}robots.txt`]: { body: `User-agent: *\nDisallow: /\nSitemap: ${finalRoot}sitemap.xml\n`, type: 'text/plain' },
    [`${finalRoot}sitemap.xml`]: { body: `<urlset><url><loc>${finalRoot}</loc></url></urlset>`, type: 'application/xml' },
  });
  const report = await auditWebsite(root, { fetchImpl: site.fetchImpl, clock: fixedClock });
  assert.equal(report.observed_page.url, finalRoot);
  assert.equal(report.observed_discovery.sitemap_url, `${finalRoot}sitemap.xml`);
  assert.ok(report.findings.some((f) => f.id === 'robots.search-blocked' && f.source_url === `${finalRoot}robots.txt`));
  assert.ok(!site.calls.some((x) => x.url === `${root}robots.txt`));
});

test('unreadable robots rules are unknown rather than an allow verdict', async () => {
  const site = fixture({
    [root]: { body: goodHome },
    [`${root}robots.txt`]: { status: 403, body: 'Forbidden', type: 'text/plain' },
  });
  const report = await auditWebsite(root, { fetchImpl: site.fetchImpl, clock: fixedClock });
  assert.equal(report.status, 'partial');
  assert.equal(report.observed_discovery.robots_status, 403);
  assert.equal(report.observed_discovery.blocked_crawlers, null);
  assert.ok(report.unknown_checks.some((x) => x.check === 'robots.txt'));
});
