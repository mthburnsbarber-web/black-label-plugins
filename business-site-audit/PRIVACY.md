# Business Site Audit data handling

The plugin sends the public URL you supply to the declared Business Site Audit MCP server at `https://audit-mcp.blacklabelbots.com/mcp`. Black Label operates that server on Cloudflare Workers. The server requests the supplied public page, its robots.txt, and its sitemap or redirects, then returns the dated report to your AI host. The audited site and network providers can see those ordinary public HTTP requests and the disclosed `BusinessSiteAudit/1.1` user agent. Your AI host handles the result under its own data policy.

The server code does not store reports, use analytics cookies, ask for an account, read your local files, or read credentials. Cloudflare processes the request URL, client IP, and operational request metadata to deliver and protect the service. A per-IP rate limiter uses the client IP for a 60-second window. Cloudflare observability is enabled for operational failures; no tool arguments or report bodies are deliberately logged by the server code.

The tool rejects URL credentials, IP-literal targets, non-default ports, private hostnames, and private or reserved DNS answers. Redirects are rechecked. Public HTTP GET/HEAD is the only site action. Do not submit private links or tokens in query strings; the submitted URL is sent to the server.
