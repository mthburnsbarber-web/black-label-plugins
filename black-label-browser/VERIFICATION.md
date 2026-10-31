# Verification

## Browser 1.2.0 — 2026-10-31

Tested on macOS 27.2 arm64 from a fresh install under an empty temporary home, following the install steps in this repository: Python 3.9.6, Node v26.12.0, Playwright 1.64.1, Google Chrome 156.0.8078.74  and Playwright's WebKit.

| Evidence | Observed result |
| --- | --- |
| Python unit tests | 42 passed |
| Node unit tests | 10 passed |
| `live_isolated` | Chromium and WebKit passed, including stale IDs, Unicode input, virtual mouse, file attachment, screenshots and profile persistence |
| `live_workflow` | Chromium and WebKit passed, including sign-in cookies across connections, logout, tab limits, form batches and chat isolation |
| `live_session_refs` | Exact reopen, typed refusals, separate account stores and credential binding passed |
| `live_e2e`, `live_navigation`, `live_execution`, `live_capabilities`, `live_styled_controls` | Passed |
| Native compatibility helper | Compiled |

Every live test ran against a local fixture with synthetic accounts. They do not prove sign-in, posting or access on any real provider. Google has refused a real sign-in in the `server/handoff.py` window with "Couldn't sign you in". `live_workflow` and `live_capabilities` also need Pillow in the Python that runs them.

## Earlier releases

The native desktop driver described below was removed in the headless design. These results are history and don't describe Browser 1.2.0.

### 2026-09-18

Browser 1.0.2 and Presence 1.0.1 were tested on macOS 27.0 arm64, including Apple's Python 3.9.6.

| Evidence | Observed result |
| --- | --- |
| Presence regression suite | 14 passed |
| Browser regression suite | 11 passed |
| Existing local operations/hook regressions (not shipped) | 24 passed |
| Claude strict manifest validation | Both plugins passed |
| Registry comparison | All 57 requested site IDs present, no account identities shipped |
| Safari native localhost acceptance | Unicode text entry, empty-field clearing, actual form submission/readback, screenshot, file chooser/readback passed |
| Chrome native localhost acceptance | Same five checks passed |

Raw, sanitized evidence is in `evidence/`. Tests cover retained scope, restart, corrections, leases, independent progress, filler/media checks, identity mismatch, duplicates, unknown results, changed media, credential-pattern guards, draft/audit boundaries, strict input schemas, code matching, busy inboxes and cross-browser keyboard serialization.

The first fresh Safari run did not expose its input within the fixture's short readiness wait. The acceptance runner now waits up to 12 seconds for the observed field, then passed. No success was inferred from opening a page.

## What this proves and does not prove

The suite proves the tested coordinator behavior and native browser interactions. Fixtures for Messages use synthetic codes; no real text-code or email-code sign-in was completed by those tests. Localhost UI evidence does not prove every site's authentication, publishing, uploaded-media processing or public visibility. The registry is a set of workflow destinations, not 57 independently tested integrations. Saved authentication observations are dated and require live rechecking.

The agent performs factual/visual review and browser execution. The coordinator does not automatically post or independently attest provider results. Human challenges, permissions, device approval and provider review remain external dependencies. Marketplace review and public installation are recorded separately from tests.

## Live submission workflow

The native browser completed an existing Google-account sign-in and both Claude plugin submission forms. Both appeared as "Submitted and pending review" in the Console. The form run exposed an empty-string fill defect; Browser 1.0.2 fixes it, and the native fixture now proves clearing via submitted-page readback in both Safari and Chrome. Checkbox numeric state is also exposed in accessibility text. OpenAI public-directory approval has not been obtained; the standard hosted MCP portal requires a separate review route for local desktop access.
