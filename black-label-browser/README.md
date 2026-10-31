# Black Label Browser

Browser automation runs in a separate **headless browser**, with its own profile,
virtual mouse and keyboard. Navigation, clicks, typing, scrolling, uploads,
downloads and screenshots happen inside that browser. No automation window
appears on the owner's displays, and no owner window is raised or captured.
The owner browser, physical pointer, keyboard focus
and clipboard are never automation targets.

No extension, owner debugging toggle, remote debugging TCP port, Accessibility,
Screen Recording or Apple Events is required. Engine control uses private pipes.
`chrome` runs headless Chromium through the installed Chrome engine; `safari`
runs headless WebKit. This is a separate agent profile: existing personal-browser
cookies, passwords and sessions are not copied. A requested sign-in must use the
agent browser and the normal provider authentication flow.

On macOS, headless WebKit registers rendering surfaces outside the display area.
Verification checks their bounds against every active display and checks that
the foreground application and displayed windows stay unchanged during actions.

## Install

macOS 13 or later, Python 3.9+, Apple's Command Line Tools, Node.js, Playwright and
Chrome are required. The installer finds a bundled Codex runtime when present.
`BL_BROWSER_NODE` and `BL_BROWSER_PLAYWRIGHT` select an existing runtime. Otherwise:

```sh
git clone https://github.com/mthburnsbarber-web/black-label-plugins.git
cd black-label-plugins
npm install --prefix ~/.blacklabel/browser-runtime playwright
BL_BROWSER_PLAYWRIGHT=~/.blacklabel/browser-runtime/node_modules/playwright python3 black-label-browser/install.py --with-webkit
```

The optional WebKit download enables `safari` requests. Runtime configuration,
private profiles and downloads live under `~/.blacklabel/isolated-browser/`.
Profiles are separate per chat when the host supplies `CODEX_THREAD_ID`; otherwise
per MCP connection. `BL_BROWSER_SESSION` explicitly selects a stable agent profile.
The compatibility helper remains at `~/Applications/Black Label Browser Bridge.app`.
It forwards to the hidden engine and has no desktop input or capture code.

## Use

Call `browser_status` for a real engine launch check. Use `browser_open`, then
`browser_snapshot`. Act on observed element IDs with `browser_click`,
`browser_fill` or `browser_type`, then inspect a new snapshot. IDs expire after
90 seconds, navigation or an action. Secure form values are redacted; screenshots mask password, one-time-code and credential-named input controls.

`browser_click_at` and `browser_scroll` use the agent virtual mouse inside the
current viewport (1440x1000 by default). Use only coordinates observed in `browser_screenshot`.
`browser_key` targets only the hidden page. System copy/cut/paste shortcuts are
disabled; use fill/type for agent input. `cmd+l` selects its internal address
field; fill that field and press Return, or navigate with `browser_open`.
`browser_focus_window` selects an observed agent page internally, without raising
any desktop window. `browser_choose_file` attaches a file after an observed upload
control opens the engine file chooser; no native dialog appears. Screenshots are
rendered by the engine and do not capture the desktop.

Never treat a successful click as sign-in, save, send or publication proof. Inspect
the resulting page and reconcile uncertain outcomes before retrying. There is no
fallback to the owner browser if an engine, login or website fails. Provider human
checks and device approvals remain real user steps. Verification-code tools retain
their narrowly scoped, transient handling; mail route preparation does not claim
that a mailbox was read.

If a running host retains an older native MCP process, use `connectBrowser()` from
`server/client.mjs` to open a fresh connection to the installed public MCP server.
The skill includes the exact adapter usage. No owner browser toggle, permission
change or restart of the shared Codex host is needed.

## Verify

```sh
python3 -m unittest discover -s black-label-browser/tests -p 'test_*.py' -v
python3 black-label-browser/tests/live_isolated.py
```

`live_workflow.py` and `live_capabilities.py` also need Pillow in the Python that runs them.

The live test exercises both hidden engines through the actual stdio MCP entry
point on a localhost fixture, including Unicode forms, stale IDs, virtual mouse,
scroll, file attachment, screenshots and profile persistence. It sends nothing to
external accounts and does not establish every third-party site's authentication.

## Reliable task workflows

The adapter supports `connectBrowser({profile:'black-label-social'})` to reuse a
**named isolated profile across chats**. Authentication performed normally inside
that profile persists on disk. The default remains a separate profile per chat.
Profile names accept only 1–80 letters, digits, hyphens and underscores; they are
hashed into private directories and never reference personal browser paths. An
OS lock prevents two connections from writing the same profile. Close the first
connection before reusing a busy profile. No owner cookies, passwords or passkeys
are imported. A provider may expire or revoke a saved session.

Durable account sessions use an opaque reference instead of a name:
`browser_session({action:'create',provider,account,workspace,role})` registers one
store per account and returns `acct_…`; `browser_session({action:'reopen',reference})`
or `connectBrowser({sessionRef})` binds that exact store and never derives a new
identity. `browser_status` returns `session_reference` for any store, including
`session:…` and `profile:…`, so a returned value can always be reopened. A missing
reference returns `SESSION_NOT_FOUND` and creates nothing; a busy one returns
`ISOLATED_PROFILE_BUSY` with its lease generation; a returned digest passed as a name
returns `SESSION_REFERENCE_PASSED_AS_NAME`. The reference selects the store, not a
signed-in state, so verify the remote account before writing. `server/executor.py` is
the product entry for apps built on this engine: it adds the broker-only `bound_fill` and
`page_meta` commands, which are not MCP tools and so cannot be called by a model.
`BL_BROWSER_STATE_ROOT` and `BL_BROWSER_PRODUCT` give each product its own namespace.

`browser_settle` reports what a page is doing from response and page evidence
together: observe, wait up to `budget_ms` while it is loading or showing a challenge,
inspect for change. It never reloads, clicks or types. A challenge at the deadline
does not establish that a person is needed, and `no_barrier_detected` does not prove
sign-in. If a person really is needed, `python3 server/handoff.py <reference> --url <page>`
is run by that person: it shows the exact same store in a window, the worker refuses
all input while it is open, and the waiting work then reopens the same reference.
That window is still driven by the automation engine, so a provider can refuse it:
Google has rejected a real sign-in there with "Couldn't sign you in".

- `browser_tabs({browser:'chrome',action:'list'})` returns stable tab IDs. Use
  `action:'open',url`, `action:'select',tab` or `action:'close',tab`. Each engine has
  a hard maximum of five tabs, including site-created popups. Excess popups are
  closed and reported; existing tabs are preserved. Close only completed task tabs.
- `browser_form` accepts up to 50 fields from one current snapshot: `element`,
  `action:'fill',text`, `action:'check',checked`, or `action:'select',values` (or `labels` for exact option labels).
  Supply either exact option values or exact labels. Ambiguous duplicates are rejected before any field is changed. Every target is prevalidated
  before mutation. Dynamic page changes can still cause a partial result; the
  error reports confirmed field count, never field values, and requires a new
  snapshot before further mutations. The tool does not submit or promise rollback.
- `browser_wait` waits for a `text` substring, a `url` substring, or a `visible`,
  `hidden` or `enabled` observed element. `timeout_ms` is limited to 25,000. Timeout
  is an explicit unmatched result; no submit or input action is automatically retried.
- `browser_auth` and snapshot `auth` expose visible password, verification,
  passkey/identity and human-check hints. `authenticated` remains null: only a real
  account/destination readback establishes sign-in. These hints do not intercept
  WebAuthn, emulate user presence, or read platform authenticators. Biometric,
  hardware-key and provider-required personal confirmation remain genuine steps.

Additional real-engine checks:

```sh
python3 black-label-browser/tests/live_workflow.py
```

These verify Chromium and WebKit using a local HTTP-only login cookie, including
cross-connection persistence, profile contention, isolation, five-tab limits,
form prevalidation, partial failure, wait timeouts, and screenshot masking. They
do not establish authentication or public submissions on third-party accounts.

Snapshots also include bounded rendered page text, semantic table cells, input
length/range constraints and individual validity flags. Closed disclosure controls
are omitted until opened. `browser_hover` acts on an observed element;
`browser_move` moves the virtual pointer to screenshot coordinates without a click.
`browser_scroll` accepts an optional observed `element` for nested panels/dialogs.
These controls all use the private engine pointer, never the desktop pointer.


Session-only cookies issued inside the isolated engine are atomically saved in
its private profile (`session-cookies.json`, mode 0600) and restored on the next
connection. That file is plain JSON and is not encrypted. Normal persistent cookies/local storage stay in the engine's own
profile. Logging out removes session cookies from the saved state; logout is
verified across restart. This never reads a personal Chrome profile and cannot
prevent a provider from expiring or revoking authentication.

## Verified actions and recovery

For an action with a known new result, `browser_click_verify` accepts an observed
`element`, stable unique `receipt_id`, `expect:{condition:'text'|'url',text:'...'}`
and optional `timeout_ms` (maximum 25,000). It writes a private reservation before
clicking once, then records `verified` or `unconfirmed`. An already-visible result
is rejected as a confirmation target. Reusing the ID returns saved evidence and
does not click, including after reconnect. `browser_receipt` reads the saved
record. These receipts prove the specified observation, not publication/payment.
Never change the ID to retry an uncertain submission.

Form batches recover a detached control only when its observed attributes match
exactly one replacement in the same frame. Missing or ambiguous replacements
require a fresh snapshot. Snapshots inspect the exact observed node handles in
batches to reduce round trips while retaining target identity.

Styled checkboxes and radio buttons use the exact input's single visible HTML
label when one exists. No text-match substitute or forced click is used. The
requested state is read back, repeated requests do not toggle again, and a
prevented/failed label activation stops the batch before subsequent fields.
`associated_labels_used` reports how many controls needed that input route.

Snapshot `readiness` separates loading from an accessible interface; `access`
distinguishes challenges, HTTP denials, rate limits, Google sign-in rejection and
network failures. Google can return HTTP 200 for a rejected sign-in; that page
reports `authentication_rejected`, not success. This classification does not
diagnose the provider's underlying reason or make Google accept the browser.
Retry-After deadlines persist with the isolated profile. Explicit navigation
waits for the applicable deadline without automatically retrying an action.
The private `execution-state.json` stores action fingerprints and cooldowns,
never submitted field values, cookies or complete page bodies.

```sh
node --test black-label-browser/tests/test_navigation.mjs black-label-browser/tests/test_execution.mjs
python3 black-label-browser/tests/live_navigation.py --output /tmp/browser-navigation.json
python3 black-label-browser/tests/live_execution.py --output /tmp/browser-execution.json
```

## Finding controls and exporting real screenshots

`browser_find({browser:'chrome',query:{name:'Save',role:'button',exact:true}})`
searches visible controls across the full page, open shadow roots and frames,
including controls beyond the ordinary snapshot limit. It returns fresh element
IDs, frame indices and an exact total. Duplicate matches require selection from
the observed results. Use `limit` (1–100) to bound output and `exact:false` for a
substring match. Finding controls does not clear an uncertain-action recovery gate;
read a full snapshot before continuing that workflow.

`browser_viewport({browser:'chrome',width:1600,height:1100})` resizes only the
selected hidden tab. Read a new snapshot afterward. Supported sizes are 320–3840
wide and 240–2160 high; virtual coordinates follow that actual size.

`browser_capture({browser:'chrome',path:'/absolute/new-file.png',full_page:false})`
saves a masked, native-resolution PNG and returns its actual dimensions, SHA256,
source URL without query/fragment, and capture time. Existing files are never
overwritten. Full-page capture is bounded to 3840×16000 and 32 million pixels.
It renders the real page; it does not upscale or fabricate product UI.

```sh
python3 black-label-browser/tests/live_capabilities.py --output /tmp/browser-capabilities.json
python3 black-label-browser/tests/live_styled_controls.py --output /tmp/browser-styled-controls.json
```


### Recover a reviewed draft after interruption

`browser_checkpoint` saves explicitly selected non-secret controls in the private
isolated profile. Restore requires the same plain page URL, visible account identity
and exact unambiguous controls. It restores draft fields only; files are reattached
and final submission uses its bound durable receipt. An already attempted final
action blocks restoration. Password/code/payment/file fields are excluded, and
metadata calls do not return draft text. Delete completed checkpoints explicitly.

The `tests/live_e2e.py` regression exercises login and a code, draft capture,
connection restart, guarded restoration, upload, one submission, readback,
restart-safe duplicate prevention and cleanup through the public MCP entry point.
It uses a local test provider; this is not proof of a third-party public placement.
