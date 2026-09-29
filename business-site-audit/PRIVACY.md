# Business Site Audit data handling

The script sends public GET or HEAD requests to the URL you supply, the final site after redirects, and any public sitemap URL declared by its robots.txt. DNS resolution and redirects are checked before each connection. It does not transmit the report to Black Label, use a telemetry endpoint, ask for an account, or persist a report. The audited site and normal network infrastructure can see the HTTP requests and the disclosed `BusinessSiteAudit/1.0` user agent. The invoking AI host receives the JSON result under that host's data policy.

The script refuses credentials in URLs, non-default ports, IP-literal targets, private hostnames, and resolved private or reserved addresses. It pins the selected public DNS address for each connection. No API key or cookie is read from the machine.
