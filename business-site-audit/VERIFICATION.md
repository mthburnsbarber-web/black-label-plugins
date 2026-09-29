# Verification

The release gate is `node --test business-site-audit/tests/audit.test.mjs` plus a fresh live run through the packaged script. The seven tests cover an unrelated business fixture, noindex and crawler-blocking precedence, unknown-versus-missing probes, private redirect refusal, private/reserved resolved-address rejection, final-host discovery after a redirect, and unreadable robots rules.

An earlier live run against `https://www.cloudflare.com/` on 2026-09-29 returned HTTP 200, the observed title “Cloudflare: Build for the agent era”, and no prioritized findings. After narrowing the probe set, a live run against `https://example.com/` returned HTTP 200 and three source-linked improvement findings: a 404 sitemap, plain HTTP returning 200, and an absent meta description. The final audit used four of twelve permitted fetches and assigned no numerical grade. This is public HTTP behavior for one page; it is not customer ranking or browser-rendering evidence.

A fresh installation from the published Git revision and provider directory approval require separate readback before claiming those states.
