# Verification — 2026-09-18

Release 1.0.1 was tested on macOS 27.0 arm64, including Apple's Python 3.9.6.

| Evidence | Observed result |
| --- | --- |
| Presence regression suite | 14 passed |
| Browser regression suite | 11 passed |
| Existing local operations/hook regressions (not shipped) | 24 passed |
| Claude strict manifest validation | Both plugins passed |
| Registry comparison | All 57 requested site IDs present, no account identities shipped |
| Safari native localhost acceptance | Unicode text entry, actual form submission/readback, screenshot, file chooser/readback passed |
| Chrome native localhost acceptance | Same four checks passed |

Raw, sanitized evidence is in `evidence/`. Tests cover retained scope, restart, corrections, leases, independent progress, filler/media checks, identity mismatch, duplicates, unknown results, changed media, credential-pattern guards, draft/audit boundaries, strict input schemas, code matching, busy inboxes and cross-browser keyboard serialization.

The first fresh Safari run did not expose its input within the fixture's short readiness wait. The acceptance runner now waits up to 12 seconds for the observed field, then passed. No success was inferred from opening a page.

## What this proves and does not prove

The suite proves the tested coordinator behavior and native browser interactions. Fixtures for Messages use synthetic codes; no real text-code or email-code sign-in was completed by those tests. Localhost UI evidence does not prove every site's authentication, publishing, uploaded-media processing or public visibility. The registry is a set of workflow destinations, not 57 independently tested integrations. Saved authentication observations are dated and require live rechecking.

The agent performs factual/visual review and browser execution. The coordinator does not automatically post or independently attest provider results. Human challenges, permissions, device approval and provider review remain external dependencies. Marketplace review and public installation are recorded separately from tests.
