# Business Site Audit

Audit **your own business website** and get a short list of observed technical problems with the exact page or discovery-file URL and a concrete fix. The first audit requires a public URL, Node.js 20+, and no account or API key.

Example request: “Audit https://mybusiness.com/services for crawl and indexing problems. Show the evidence and the first fixes to make.”

The packaged skill runs a deterministic public HTTP audit. It checks the requested page, robots.txt, sitemap, indexing directives, title, description, canonical URL, and malformed structured data. It distinguishes a failed probe from an observed missing resource. It does not give an arbitrary SEO grade or claim a search ranking, traffic gain, or conversion outcome.

## Run without an AI host

```sh
node business-site-audit/skills/site-audit/scripts/audit-site.mjs https://example.com/
```

The command prints JSON to standard output and writes no report file. `top_actions` is the ranked summary; `findings` includes observed detail and source URLs. `status: inconclusive` means the homepage had no HTTP response during this run. The audit reads one public page, robots.txt, and the declared or default sitemap, and checks the HTTP redirect, with a 12-request ceiling, per-request timeouts, redirect checks, and bounded response bytes. It does not render JavaScript, sign in, edit a site, or submit forms.

## Install

The root [README](../README.md) gives the Codex and Claude Code marketplace commands. This is a skill-only plugin: no MCP server, subscription, or Black Label customer data is involved. The code runs locally with built-in Node modules. The invoking host can use the result to propose changes in the owner's own site repository; deployment is a separate, explicit workflow.

## Verification and support

Run `node --test business-site-audit/tests/audit.test.mjs` from the repository root. See [VERIFICATION.md](VERIFICATION.md) for the observed live probe and test boundary, [PRIVACY.md](PRIVACY.md) for data handling, and [TERMS.md](TERMS.md) for software terms. File issues at https://github.com/mthburnsbarber-web/black-label-plugins/issues with the audited URL and redacted error output. Do not include private URLs or credentials.
