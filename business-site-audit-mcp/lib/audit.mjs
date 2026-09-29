import { createFetcher, checkPublicUrl, siteRoot } from './safe-fetch.mjs';
import { CRAWLERS, parseRobots, evaluate } from './robots.mjs';
import { extractPage } from './html.mjs';

const PRIORITY = { blocking: 0, important: 1, improvement: 2 };
const searchCrawlers = CRAWLERS.filter((crawler) => crawler.kind === 'search');
const answerCrawlers = CRAWLERS.filter((crawler) => crawler.kind === 'ai-answer');

function normalizeTarget(input) {
  const raw = String(input ?? '').trim();
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`;
  return checkPublicUrl(withScheme);
}

function isHtml(response) {
  return response?.ok && response.status === 200 &&
    (response.contentType.includes('text/html') || /^\s*<(!doctype|html)/i.test(response.text));
}

export async function runAudit(input, { fetchImpl, clock = () => new Date() } = {}) {
  const target = normalizeTarget(input);
  if (!target.ok) throw Object.assign(new Error(target.reason), { code: 'invalid_url' });
  const fetcher = createFetcher({ fetchImpl, maxFetches: 12 });
  const requestedUrl = target.url.toString();
  const page = await fetcher.get(requestedUrl, { accept: 'text/html,application/xhtml+xml' });
  const finalUrl = page.ok ? page.url : requestedUrl;
  const siteRootUrl = siteRoot(new URL(finalUrl));
  const hostname = new URL(finalUrl).hostname;
  const findings = [];
  const unknown = [];
  const finding = (id, priority, title, observed, source_url, fix) =>
    findings.push({ id, priority, title, observed, source_url, fix });

  const homepageInconclusive = !page.ok;
  const homepageUnavailable = !homepageInconclusive && !isHtml(page);
  if (homepageInconclusive) {
    unknown.push({ check: 'homepage', reason: page.error ?? 'No HTTP response was observed' });
  } else if (homepageUnavailable) {
    finding('page.unreachable', 'blocking', 'Page did not load as HTML',
      `GET ${finalUrl} returned HTTP ${page.status} (${page.contentType || 'no content type'}).`,
      finalUrl, 'Serve this page as HTML with HTTP 200 over HTTPS.');
  }

  const [plainHttp, robotsResponse] = await Promise.all([
    fetcher.get(`http://${hostname}/`, { followRedirects: false, accept: 'text/html' }),
    fetcher.get(new URL('/robots.txt', siteRootUrl).toString(), { accept: 'text/plain' }),
  ]);
  if (plainHttp.ok && !(plainHttp.status >= 300 && plainHttp.status < 400 &&
      /^https:\/\//i.test(plainHttp.headers?.location ?? ''))) {
    finding('transport.http-not-redirected', 'improvement', 'HTTP does not redirect to HTTPS',
      `GET http://${hostname}/ returned HTTP ${plainHttp.status}${plainHttp.headers?.location ? ` with Location: ${plainHttp.headers.location}` : ''}.`,
      `http://${hostname}/`, 'Redirect HTTP requests to HTTPS.');
  } else if (!plainHttp.ok) {
    unknown.push({ check: 'HTTP redirect', reason: plainHttp.error ?? 'No HTTP response was observed' });
  }

  const robotsUrl = new URL('/robots.txt', siteRootUrl).toString();
  const robotsReadable = robotsResponse.ok && robotsResponse.status === 200 &&
    !robotsResponse.contentType.includes('text/html') && !robotsResponse.truncated;
  const robotsAbsent = robotsResponse.ok && [404, 410].includes(robotsResponse.status);
  const robotsUnknown = !robotsReadable && !robotsAbsent;
  const robots = robotsReadable ? parseRobots(robotsResponse.text) : null;
  const crawlerRules = robotsUnknown ? null : Object.fromEntries(
    CRAWLERS.map((crawler) => [crawler.token, {
      kind: crawler.kind,
      ...evaluate(robots ?? { groups: [] }, crawler.token, new URL(finalUrl).pathname || '/'),
    }]),
  );
  const blockedCrawlerRules = crawlerRules === null ? null : Object.fromEntries(
    Object.entries(crawlerRules).filter(([, rule]) => rule.verdict === 'blocked'),
  );
  if (robotsUnknown) {
    unknown.push({ check: 'robots.txt', reason: robotsResponse.ok
      ? `HTTP ${robotsResponse.status} did not provide complete readable rules`
      : robotsResponse.error ?? 'No HTTP response was observed' });
  } else if (robots) {
    for (const [kind, id, priority, title] of [
      ['search', 'robots.search-blocked', 'blocking', 'Search crawler access is blocked'],
      ['ai-answer', 'robots.ai-answer-blocked', 'important', 'AI answer crawler access is blocked'],
    ]) {
      const relevant = kind === 'search' ? searchCrawlers : answerCrawlers;
      const blocked = relevant.filter((crawler) => crawlerRules[crawler.token].verdict === 'blocked');
      if (blocked.length) finding(id, priority, title,
        blocked.map((crawler) => `${crawler.token}: ${crawlerRules[crawler.token].rule}`).join('; '),
        robotsUrl, 'Review the matching Disallow rules for this page; allow the crawlers you want to reach it.');
    }
  }

  const sitemapUrl = robots?.sitemaps?.[0] ?? new URL('/sitemap.xml', siteRootUrl).toString();
  const sitemapResponse = await fetcher.get(sitemapUrl, { accept: 'application/xml,text/xml' });
  const sitemapEntries = sitemapResponse.ok && sitemapResponse.status === 200 && !sitemapResponse.truncated
    ? (sitemapResponse.text.match(/<loc\s*>/gi) ?? []).length : 0;
  const sitemapReadable = sitemapResponse.ok && sitemapResponse.status === 200 &&
    !sitemapResponse.truncated && sitemapEntries > 0 && /<(urlset|sitemapindex)\b/i.test(sitemapResponse.text);
  if (!sitemapResponse.ok || sitemapResponse.truncated) {
    unknown.push({ check: 'sitemap', reason: sitemapResponse.truncated
      ? 'Response exceeded the size limit' : sitemapResponse.error ?? 'No HTTP response was observed' });
  } else if (!sitemapReadable) {
    finding('sitemap.missing', 'improvement', 'No readable XML sitemap',
      `GET ${sitemapUrl} returned HTTP ${sitemapResponse.status} with ${sitemapEntries} <loc> entries.`,
      sitemapUrl, 'Publish a sitemap with your canonical pages and reference it from robots.txt.');
  }

  const facts = isHtml(page) && !page.truncated ? extractPage(page.text) : null;
  if (page.truncated) unknown.push({ check: 'page metadata', reason: 'HTML response exceeded the size limit' });
  if (facts) {
    if (/\bnoindex\b/i.test(page.headers?.['x-robots-tag'] ?? ''))
      finding('page.x-robots-noindex', 'blocking', 'Response header says noindex',
        `X-Robots-Tag: ${page.headers['x-robots-tag']}`, finalUrl,
        'Remove noindex from the header if this page should appear in search.');
    if (/\bnoindex\b/i.test(facts.robots ?? ''))
      finding('page.meta-noindex', 'blocking', 'Page metadata says noindex',
        `<meta name="robots" content="${facts.robots}">`, finalUrl,
        'Remove noindex from the page metadata if this page should appear in search.');
    if (!facts.title)
      finding('page.no-title', 'important', 'Missing page title', 'No <title> element was found.',
        finalUrl, 'Add a specific title naming the business and what this page offers.');
    if (!facts.description)
      finding('page.no-description', 'improvement', 'Missing meta description',
        'No <meta name="description"> was found.', finalUrl,
        'Add a concise description of this page for search previews.');
    if (facts.canonical) {
      try {
        if (new URL(facts.canonical, finalUrl).hostname !== hostname)
          finding('page.canonical-offsite', 'improvement', 'Canonical URL points to another host',
            facts.canonical, finalUrl, 'Confirm that the canonical URL names the intended source page.');
      } catch {
        unknown.push({ check: 'canonical URL', reason: 'The canonical URL could not be parsed' });
      }
    }
    if (facts.jsonLd.invalid.length)
      finding('schema.invalid', 'important', 'JSON-LD could not be parsed',
        `${facts.jsonLd.invalid.length} block(s): ${facts.jsonLd.invalid.map((row) => row.error).join('; ')}`,
        finalUrl, 'Fix the JSON syntax in the affected structured data blocks.');
  }

  findings.sort((a, b) => PRIORITY[a.priority] - PRIORITY[b.priority]);
  return {
    kind: 'business-site-audit', version: '1.1.2', target: requestedUrl,
    checked_at: clock().toISOString(),
    status: homepageInconclusive ? 'inconclusive' : homepageUnavailable ? 'homepage_unavailable'
      : unknown.length ? 'partial' : 'observed',
    summary: homepageInconclusive ? 'The page returned no HTTP response. Recheck before drawing conclusions.'
      : homepageUnavailable ? 'The page response was not usable HTML. Inspect its status and content type.'
        : findings.length ? `${findings.length} actionable finding${findings.length === 1 ? '' : 's'} on this page and its discovery files.`
          : 'No priority issues observed in the completed checks; this is a one-page technical audit.',
    top_actions: findings.slice(0, 5), findings, unknown_checks: unknown,
    observed_page: { url: finalUrl, http_status: page.ok ? page.status : null,
      title: facts?.title ?? null, description: facts?.description ?? null,
      canonical: facts?.canonical ?? null, json_ld_types: facts?.jsonLd.types ?? [],
      error: page.error ?? null },
    observed_discovery: { robots_status: robotsResponse.ok ? robotsResponse.status : null,
      sitemap_url: sitemapUrl, sitemap_status: sitemapResponse.ok ? sitemapResponse.status : null,
      sitemap_entries_seen: sitemapEntries, blocked_crawlers: blockedCrawlerRules },
    method: { scope: 'Public HTTP only: one requested page plus discovery files. Robots rules are evaluated locally; no crawler traffic is tested. No JavaScript rendering, sign-in, form submission or search ranking claim.',
      fetches: fetcher.stats().fetches, max_fetches: fetcher.stats().maxFetches },
  };
}
