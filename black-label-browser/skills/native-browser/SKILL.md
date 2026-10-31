---
name: native-browser
description: Use Black Label Browser for invisible browser automation with a separate headless profile and virtual input, without changing the owner screen or pointer.
---

# Hidden browser execution

Use the `black-label-browser` MCP tools. The default driver is a separate headless
engine controlled over private pipes. It never raises, types into, scrolls or
captures the owner desktop. No extension, owner debugging toggle, Accessibility
or Screen Recording is required. Chrome uses isolated Chromium; safari uses
isolated WebKit. Personal browser sessions are not imported.

1. Call `browser_status` to prove the engine can launch. Expect
   `mode=isolated-headless`, `desktop_keyboard_input=false`,
   `desktop_activation=false` and `owner_cursor_protected=true`. If a stale host
   connection still reports native desktop mode, use a fresh stdio connection to
   this installed plugin. Do not perform actions through the stale native route.
   In Node REPL, import the adapter from this plugin's absolute install path:

   ```js
   var {connectBrowser} = await import('/absolute/plugin/path/server/client.mjs');
   var hiddenBrowser = await connectBrowser();
   var status = await hiddenBrowser.call('status');
   // Names omit browser_; arguments match the public tools.
   await hiddenBrowser.call('open', {browser:'chrome', url:'https://example.com/'});
   var page = await hiddenBrowser.call('snapshot', {browser:'chrome'});
   ```

   Keep that connection for the task. This requires no owner action or host restart.
   Resolve the plugin path from the skill's own install location; never use the
   literal placeholder. End a finished connection with `await hiddenBrowser.close()`.
2. Navigate with `browser_open`, then inspect `browser_snapshot`. Verify the real
   URL and signed-in identity. Sign in through the provider flow when required.
3. Use observed element IDs with `browser_click` and `browser_fill`. Refresh the
   snapshot after every meaningful action; IDs expire after navigation, an action
   or 90 seconds. `browser_type` requires the observed field to be focused inside
   the hidden browser. Inputs and errors must not echo passwords or codes.
4. Use `browser_screenshot` to inspect the agent viewport. `browser_click_at`
   uses its virtual mouse at those observed coordinates; `browser_scroll` moves
   only its virtual wheel. Never use desktop coordinates or physical input.
5. `browser_focus_window` selects an observed agent page without desktop focus.
   `browser_key` targets only the hidden page. Prefer `browser_open` for URLs.
6. Click an observed upload control, then use `browser_choose_file` with the
   existing absolute file path. Verify the filename/preview on the resulting
   page. The engine chooser never opens a native desktop dialog.

Use existing agent-profile sessions and provider account pickers normally. Do not
copy cookies, passwords, passkeys or owner browser profiles. Human checks and
new credentials remain user steps. Continue independently executable work while
preserving the original request, corrections and exact blocked state.

For email codes, prefer the connected mailbox connector. Otherwise use
`browser_email_code_route` and execute its narrowly scoped search in the agent
browser. Verify mailbox identity and the active sender/service/time window. The
route itself does not read mail. `browser_text_code` reads only recent matching
incoming Messages codes; denied access remains a real macOS permission gate.
Never persist or include credentials/codes/recovery links in receipts.

Verify actual results after every action. A timeout or successful click is not
proof of a save, send, sign-in or publication. Reconcile before retrying. There is
no foreground-browser fallback. Preserve owner, customer-message and spending
boundaries.


## Persistent workflows

Use the installed adapter `connectBrowser({profile:'black-label-social'})` when a
task calls for the same isolated account session across chats. Names are private
profile labels, not paths. The default remains chat isolated. A busy profile
requires its earlier connection to close; never copy or unlock a personal profile.

To keep one account across chats, use `browser_session` `create`, keep the returned
`acct_…` reference, and `reopen` it (or `connectBrowser({sessionRef})`). Never pass a
returned digest as a session name; that is refused. `browser_status` returns
`session_reference` for the current store. A missing reference stays missing and busy
stays busy: nothing is copied, stolen or recreated. Verify the remote account after
every reopen.

Before calling a page blocked, call `browser_settle` with a real budget and repeat it
up to about 45 seconds. A 403 alone is not a diagnosis. Report what was observed:
"challenge still showing after 45s" is a fact, "needs human verification" is not,
unless the provider says so. Never click or solve a check. If a person is needed, give
them `server/handoff.py <reference> --url <page>` so they finish it in this exact
session, then reopen the reference and verify the account before continuing.

`browser_tabs` lists stable IDs and supports open/select/close. At most five tabs
per engine are accepted, including popups. Reuse task tabs and close completed
ones. `browser_form` batches observed fields with fill/check/select actions,
prevalidates all targets, and confirms values internally without echoing them.
Read a new snapshot after each batch and before submitting. If a dynamic form
partially fails, reconcile the confirmed count and current fields before retrying.

`browser_wait` waits up to 25 seconds for text, URL or observed element state.
`browser_auth` reports visible authentication hints, never authenticated status.
Saved isolated sessions can persist; provider user-presence prompts are not bypassed.

## Loading and access failures

Inspect snapshot `readiness` and `access` before deciding a page is usable or
blocked. Readiness waits briefly for rendered content and loading indicators;
it does not prove every script or form is ready. Use `browser_wait` for the
expected field or result, then inspect readback before submitting.

`access` distinguishes a verification challenge, access denial, rate limit,
HTTP failure, Google sign-in rejection and a navigation/network failure. A Google
rejection page can return HTTP 200; `authentication_rejected` still means that
sign-in failed, and does not establish why Google rejected it. Use a supported
alternative sign-in or provider support route; do not repeat the rejected flow.
Main-document diagnostics expose
only status, safe URL path, challenge signal and retry time; never request bodies
or authentication headers. A challenge response is not a diagnosis of its cause.
`none_detected` does not prove sign-in or successful submission.

Keep the same named isolated profile for a continuing account workflow. Do not
clear cookies, change identity or reload challenges repeatedly. Honor the
reported Retry-After deadline; explicit navigation, reload and new-tab requests
are held for that origin, including after reconnecting the same profile. HTTP 429 without a
deadline uses a labeled 60-second agent backoff. No action automatically retries.
Continue independent sites and record the exact provider requirement. Preserve
the deadline in the task record. These reliability measures
do not guarantee that a provider will accept an automated browser.

## Reliable form and submit operations

`browser_form` can recover a detached control after the page rerenders only when
its recorded attributes identify exactly one replacement in the same frame.
Ambiguous replacements stop the batch. Inspect the confirmed count and fresh
snapshot before continuing. `targets_rebound` reports recovered controls.

For styled checkboxes and radios, `browser_form` can activate the exact observed
input through its single visible associated HTML label and verify its state.
`associated_labels_used` reports this route. A label that prevents activation
stops the batch; the tool never substitutes a same-text control or forces input.

For a submit or navigation with a known visible result, prefer
`browser_click_verify` with the observed element, a unique stable `receipt_id`,
and `expect: {condition: 'text' | 'url', text: 'specific new outcome'}`.
The outcome must not already be present. The tool reserves the receipt on disk
before clicking once and then waits up to `timeout_ms` (maximum 25000).
`verified` means the specified visible outcome appeared, not that a product was
published or payment settled. Still read the destination, identity and actual
receipt. `unconfirmed` or `started` never authorizes another attempt.

Use `browser_receipt` to read that action after a timeout or reconnect. Calling
`browser_click_verify` again with the same ID returns the historical receipt
without another click. Do not switch IDs to retry an uncertain operation.
Receipt IDs must be unique per intended action and contain no secrets. Expected
outcomes are fingerprinted; field values and page bodies are not saved there.

## Long pages, frames and native-resolution evidence

Use `browser_find` with `query:{name,role,tag,exact,limit}` when a control is buried
in a long page or a frame. Name matching is exact by default; set `exact:false`
for a substring. The tool returns fresh observed IDs and an explicit match count,
including controls beyond the normal snapshot limit. Multiple matches remain
ambiguous; inspect the role, tag and `frame_index` before choosing. Supported
roles are button, link, textbox, checkbox, radio, combobox, heading and file.
Open shadow-root controls are included. The lookup never clicks automatically.

`browser_viewport` sets only the selected hidden page's width and height. Read a
new snapshot afterward. `browser_capture` saves that page to a new absolute PNG
path and returns real pixel dimensions, source URL and SHA-256. `full_page:true`
captures a bounded full page. Password and code controls are masked. Files are
never overwritten. Capture the product's actual interface; a larger viewport
is not permission to fabricate UI or upscale old evidence. Virtual coordinates
always refer to the current hidden viewport, never the desktop.


For hover-only menus use `browser_hover` on an observed ID. `browser_move` points
the isolated mouse at screenshot coordinates without clicking. For an inner scroll
panel, use `browser_scroll` with its observed `element`. Snapshot `text` includes
bounded rendered text and table cells; `constraints` and `validation` explain
invalid fields without echoing secure values. For selects whose values collide,
use `browser_form` with exact `labels` instead of `values`; ambiguous choices are
rejected. Closed details/dropdown contents are not actionable until opened.


## Interrupted forms

Use `browser_checkpoint` with `action:save`, a stable `id`, the selected observed
non-secret control IDs in `fields`, the exact visible account/workspace `identity`,
and the intended final action's `receipt_id`. The private checkpoint saves only
those controls. Passwords, verification/recovery codes, payment controls, hidden
fields and file inputs are rejected. Do not select a text field containing secrets.
The page and selected frame URLs must be plain HTTP(S) without query or fragment.

After a connection restart, `action:list` returns checkpoint metadata without
field values. Navigate to the saved page, inspect the account, then call
`action:restore` with the same `id` and `identity`. The page URL, visible identity
and every control's exact observed attributes must match before any field changes.
Restore never navigates or submits. Inspect restored values and reattach files.
Use the bound `receipt_id` with `browser_click_verify` for final submission.
Any existing receipt, including an unconfirmed one, blocks restoration; reconcile
the provider result instead. Delete the checkpoint after confirmed completion
with `action:delete`, then close the completed task tab. Authentication, provider
review and publication still require their own live evidence.
