# Black Label Plugins

Two local MCP plugins for Codex and Claude Code. Browser 1.0.2; Presence 1.0.1.

- **Black Label Browser:** control real Safari and Chrome on macOS through Accessibility and native input. No browser extension, CDP, Apple Events or Automator.
- **Black Label Presence:** retain a campaign's full request and corrections, coordinate 57 named destinations, inspect content and media, reserve submissions, and record observed receipts. The executing agent performs browser actions; this is not an unattended publisher.

## Install

Requirements: macOS 13 or later, Python 3.9+, Apple's Command Line Tools (`xcrun swiftc`), Safari or Chrome, and a host supporting local stdio MCP plugins. Build on the target Mac. The helper is locally ad-hoc signed; this release is source, not a notarized binary.

```sh
git clone https://github.com/mthburnsbarber-web/black-label-plugins.git
cd black-label-plugins
python3 black-label-browser/install.py
```

Grant **Black Label Browser Bridge** Accessibility and Screen Recording through macOS System Settings when needed. Installation does not change permissions. Text-code lookup also needs the Python host's existing permission to read Messages; the helper's Accessibility grant alone does not provide that access.

For Codex:

```sh
codex plugin marketplace add https://github.com/mthburnsbarber-web/black-label-plugins.git
codex plugin add black-label-browser@black-label-public
codex plugin add black-label-presence@black-label-public
```

For Claude Code:

```sh
claude plugin marketplace add https://github.com/mthburnsbarber-web/black-label-plugins.git
claude plugin install black-label-browser@black-label-public --scope user
claude plugin install black-label-presence@black-label-public --scope user
```

Reload plugins or refresh the host's tool context. These are independently hosted public plugins; installation does not imply OpenAI or Anthropic directory approval.

## Use

“Publish one distinct product update with matching real screenshots on our existing LinkedIn and X accounts, finish the requested profile corrections, and give me the verified links.”

The agent discovers the exact authorized identities from the live browser. It retains corrections, inspects content, executes actions and checks results without repeatedly asking for the same instruction. Draft and audit requests remain non-publishing tasks.

The public registry contains **57 destinations, no personal accounts or credentials**: 44 active templates, eight held, three excluded and two conditional. Use an explicit site list for a narrow job. To customize destinations, make a private copy of `black-label-presence/platforms.json`, change requirements/account candidates/dispositions, and configure `BL_PRESENCE_REGISTRY` in the Presence MCP environment. Never commit that private copy. Registry coverage is not proof of real authentication or site-specific API support.

The browser supports saved sessions and ordinary password autofill. Email verification is a search route executed by the agent, not an inbox reader. Text-code matching uses recent incoming Messages with service/time/sender filtering. Human checks and device approvals require the real user's action; work resumes afterward. Providers may change their UI or restrict accounts.

## Verification

```sh
python3 -m unittest discover -s black-label-presence/tests -v
python3 -m unittest discover -s black-label-browser/tests -v
python3 black-label-browser/tests/live_native.py
```

The last command opens localhost fixture tabs in Safari and Chrome, changes foreground focus, and tests text entry, submission/readback, screenshots and native file selection. It creates no social posts. See [VERIFICATION.md](VERIFICATION.md) for exact observed evidence and limits, and [PRIVACY.md](PRIVACY.md) for data handling.

## Support and license

Report reproducible issues at https://github.com/mthburnsbarber-web/black-label-plugins/issues. Include versions and redacted errors, never passwords, codes or inbox contents. MIT license. Maintained by Black Label.
