---
name: business-site-audit
description: Audit a business's own public website for observed crawl, indexing, metadata, and discovery issues; give source-linked fixes or verify a repair. Use for a public URL, not private dashboards or ranking forecasts.
---

# Business site audit

Run the bundled `scripts/audit-site.mjs` with the owner's public page URL. Resolve the script relative to this `SKILL.md` so it works from any current directory. It requires Node.js 20 or newer and prints a dated JSON report. The script reads public HTTP responses only; it does not sign in or change the site.

Start with the `status` field. `inconclusive` means the page returned no HTTP response to this run. `partial` means a supporting probe failed. Do not turn an unknown probe into a claim that the owner's site is missing a file or broken. `homepage_unavailable` carries an observed response that needs inspection.

For an observed audit, give the owner the first few `top_actions` in priority order. Each action has the exact observed detail, source URL, and a fix. Explain only fixes supported by those observations. When there are no priority issues, say the checks found none; avoid a generic SEO checklist or invented score. The audit covers one page plus public discovery files and cannot establish rankings, traffic, conversions, or how a JavaScript-rendered page looks to a browser.

If the owner asks you to repair a site whose source is available, make the focused change, deploy only within the authority already granted, rerun this script against the live URL, and compare the specific observed finding. Do not treat a local build as live verification.
