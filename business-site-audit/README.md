# Business Site Audit

Give the plugin one public page on your business website. Its declared `audit_business_site` MCP tool checks that page, robots.txt, and the sitemap, then returns a dated, short list of observed problems with source URLs and focused fixes. No Black Label account, API key, local Node installation, or subscription is needed.

Example: “Audit https://mybusiness.com/services and show the first crawl and indexing fixes with evidence.”

The tool reports observed HTTP status, title, description, canonical URL, indexing directives, crawler rules inferred from robots.txt, and malformed structured data. It labels failed probes as unknown. It does not claim a ranking, traffic gain, conversion outcome, or JavaScript-rendered appearance.

## Install and use

Install `business-site-audit@black-label-public` from the [repository marketplace](../README.md), then ask the example request above. The plugin connects to the public, read-only MCP server at https://audit-mcp.blacklabelbots.com/mcp. The only declared tool is `audit_business_site`; it accepts a public URL or domain name. The service rate limit is 30 MCP requests per minute per client IP, per Cloudflare location.

The audit makes at most 12 public GET/HEAD requests, with per-request timeouts, redirect validation, and a 1.5 MB response-body limit. Private hostnames, IP-literal targets, credentials in URLs, non-default ports, and private or reserved DNS answers are refused. The server never edits the audited site.

## Verification and support

The [MCP server source and tests](../business-site-audit-mcp/) are public but separate from the installable plugin. From a source checkout, run `npm --prefix business-site-audit-mcp test`. The maintainer's optional CLI is `node business-site-audit-mcp/bin/audit-site.mjs https://example.com/`; the installed plugin uses its declared MCP tool. See [VERIFICATION.md](VERIFICATION.md), [PRIVACY.md](PRIVACY.md), and [TERMS.md](TERMS.md). Report redacted issues at https://github.com/mthburnsbarber-web/black-label-plugins/issues.
