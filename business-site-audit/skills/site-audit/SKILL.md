---
name: business-site-audit
description: Audit a business owner's public website for observed crawl, indexing, metadata, and discovery issues through the declared audit_business_site MCP tool. Return source-linked fixes or verify a repair.
---

# Business site audit

Call this plugin's declared MCP tool `audit_business_site` with the owner's public page URL. The tool runs on the published Business Site Audit MCP server. No local command, bundled script, sign-in, or API key is needed.

Read the returned `status` before summarizing it. `inconclusive` means the page returned no HTTP response. `partial` means a supporting probe failed. `homepage_unavailable` means an HTTP response was observed but the page was not usable HTML. Do not turn an unknown probe into a claim that the site is missing a resource or is healthy.

For an observed audit, give the owner the first few `top_actions` in priority order. Each action has an observed detail, a source URL, and a fix. When there are no priority issues, say the checks found none. Do not invent an SEO score or generic fixes.

The audit covers one public page plus robots.txt and a sitemap. It does not establish rankings, traffic, conversions, or the appearance of a JavaScript-rendered page. `blocked_crawlers` evaluates robots.txt rules; it is not a live crawler test or proof that a search engine indexed the page.

If the owner asks you to repair a site whose source is available, make the focused change within the authority already granted, deploy if authorized, then call `audit_business_site` again against the live URL and compare the observed finding. If the MCP tool is unavailable, report the connection problem and resume after the plugin's declared server is reachable; do not substitute a local script.
