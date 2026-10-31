# Black Label Plugins

Three business-use plugins for Codex and Claude Code. Browser 1.2.0; Presence 1.0.1; Business Site Audit 1.1.2.

- **Black Label Browser:** run browser tasks in a separate headless Chromium or WebKit profile with its own virtual mouse and keyboard. It never touches your screen, pointer, keyboard or personal browser. No extension, Accessibility, Screen Recording or Apple Events.
- **Black Label Presence:** coordinate an owner-authorized presence campaign, inspect real content and media, prevent duplicate submissions, and record observed receipts. The executing agent performs browser actions.
- **Business Site Audit:** audit your own public website for crawl, indexing, metadata and structured-data issues, with observed source URLs and focused fixes. Its declared, hosted MCP tool needs no account or local runtime.

## Install

Browser and Presence require macOS 13 or later, Python 3.9+, Apple's Command Line Tools (`xcrun swiftc`), Node.js, Playwright, Chrome, and a host supporting local stdio MCP plugins. Business Site Audit uses its public HTTPS MCP server and works wherever the plugin host supports remote MCP. Build the browser helper on the target Mac. The helper is locally ad-hoc signed; this release is source, not a notarized binary.

```sh
git clone https://github.com/mthburnsbarber-web/black-label-plugins.git
cd black-label-plugins
npm install --prefix ~/.blacklabel/browser-runtime playwright
BL_BROWSER_PLAYWRIGHT=~/.blacklabel/browser-runtime/node_modules/playwright python3 black-label-browser/install.py --with-webkit
```

The browser needs no Accessibility or Screen Recording permission. Installation does not change permissions. Text-code lookup also needs the Python host's existing permission to read Messages; the helper's Accessibility grant alone does not provide that access.

For Codex:

```sh
codex plugin marketplace add https://github.com/mthburnsbarber-web/black-label-plugins.git
codex plugin add black-label-browser@black-label-public
codex plugin add black-label-presence@black-label-public
codex plugin add business-site-audit@black-label-public
```

For Claude Code:

```sh
claude plugin marketplace add https://github.com/mthburnsbarber-web/black-label-plugins.git
claude plugin install black-label-browser@black-label-public --scope user
claude plugin install black-label-presence@black-label-public --scope user
claude plugin install business-site-audit@black-label-public --scope user
```

Reload plugins or refresh the host's tool context. These are independently hosted public plugins; installation does not imply OpenAI or Anthropic directory approval.

## Use

“Audit my business website and show the evidence behind the first fixes.”

Or, with Browser and Presence installed: “Publish one distinct product update with matching real screenshots on our existing LinkedIn and X accounts, finish the requested profile corrections, and give me the verified links.”

The agent discovers the exact authorized identities from the live browser. It retains corrections, inspects content, executes actions and checks results without repeatedly asking for the same instruction. Draft and audit requests remain non-publishing tasks.

The public registry contains **57 destinations, no personal accounts or credentials**: 44 active templates, eight held, three excluded and two conditional. Use an explicit site list for a narrow job. To customize destinations, make a private copy of `black-label-presence/platforms.json`, change requirements/account candidates/dispositions, and configure `BL_PRESENCE_REGISTRY` in the Presence MCP environment. Never commit that private copy. Registry coverage is not proof of real authentication or site-specific API support.

The browser keeps sign-ins in its own private profile and never imports your personal browser's cookies or passwords. Email verification is a search route executed by the agent, not an inbox reader. Text-code matching uses recent incoming Messages with service/time/sender filtering. Human checks and device approvals require the real user's action; work resumes afterward. Providers may change their UI or restrict accounts.

## Verification

```sh
python3 -m unittest discover -s black-label-presence/tests -v
python3 -m unittest discover -s black-label-browser/tests -v
python3 black-label-browser/tests/live_isolated.py
npm --prefix business-site-audit-mcp test
node business-site-audit-mcp/bin/audit-site.mjs https://example.com/
```

The live browser command runs both hidden engines against a localhost fixture without touching your screen, and tests text entry, form batches, stale IDs, the virtual mouse, file attachment, screenshots and profile persistence. It creates no social posts. The site audit CLI is a maintainer check; buyers use the declared MCP tool. See [VERIFICATION.md](VERIFICATION.md) for exact observed evidence and limits, and [PRIVACY.md](PRIVACY.md) for data handling.

## Support and license

Report reproducible issues at https://github.com/mthburnsbarber-web/black-label-plugins/issues. Include versions and redacted errors, never passwords, codes or inbox contents. MIT license. Maintained by Black Label.
