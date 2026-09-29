---
name: business-site-audit
description: Audit a business's own public website for observed crawl, indexing, metadata, and discovery issues; give source-linked fixes or verify a repair. Use for a public URL, not private dashboards or ranking forecasts.
---

# Business site audit

Run the bundled `scripts/audit-site.mjs` with the owner's public page URL. Use the **actual installed plugin file path**, independent of the current directory. Claude Chat may display a logical skill address such as `/mnt/skills/plugins/business-site-audit:business-site-audit`; that address is not a filesystem path. In that environment, locate `business-site-audit/skills/site-audit/scripts/audit-site.mjs` under `$HOME/.claude/plugins/synced/` and run the found file with Node. In Claude Code or Codex, resolve `scripts/audit-site.mjs` from the real `SKILL.md` path. Do not run `ls` or `node` against the logical skill address.

The script requires Node.js 20 or newer and prints a dated JSON report. It reads public HTTP responses only; it does not sign in or change the site.

Start with the `status` field. `inconclusive` means the page returned no HTTP response to this run. `partial` means a supporting probe failed. Do not turn an unknown probe into a claim that the owner's site is missing a file or broken. `homepage_unavailable` carries an observed response that needs inspection.

For an observed audit, give the owner the first few `top_actions` in priority order. Each action has the exact observed detail, source URL, and a fix. Explain only fixes supported by those observations. When there are no priority issues, say the checks found none; avoid a generic SEO checklist or invented score. The audit covers one page plus public discovery files and cannot establish rankings, traffic, conversions, or how a JavaScript-rendered page looks to a browser.

The `blocked_crawlers` field is an evaluation of robots.txt rules, not a live crawler test. Do not say those crawlers were probed or that a search engine actually indexed the page.

If the owner asks you to repair a site whose source is available, make the focused change, deploy only within the authority already granted, rerun this script against the live URL, and compare the specific observed finding. Do not treat a local build as live verification.
