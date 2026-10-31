// Bounded operations on the isolated engine only. Never accepts arbitrary JS.
const fail = message => { throw new Error(message); };

export function authHints(rows, text = '', access = null) {
  const visible = rows.map(row => row.title || '').join(' ') + ' ' + text;
  const requirements = [];
  if (rows.some(row => row.type === 'password')) requirements.push('password');
  if (rows.some(row => row.autocomplete === 'one-time-code' || /verification.?code|one.time.?code/i.test(row.title || '')))
    requirements.push('verification_code');
  if (/use (a |your )?passkey|sign in with (a )?passkey|touch your security key|insert your security key|verify (it.s you|your identity)/i.test(visible))
    requirements.push('passkey_or_identity_prompt');
  if (access?.kind === 'challenge' || /verif(?:y|ying) (?:that )?you are human|i.m not a robot|complete the captcha|performing security verification/i.test(visible)) requirements.push('human_verification');
  if (access?.kind === 'authentication_rejected') requirements.push('provider_rejected_signin');
  return {status: access?.kind === 'authentication_rejected' ? 'authentication_rejected'
      : requirements.length ? 'interaction_detected' : 'not_detected', requirements,
    authenticated: null, note: 'Visible-page hints only; verify account identity and destination after sign-in. Device presence requirements remain controlled by the provider.'};
}

// Only allowlisted response facts, never cookies, request bodies or raw errors.
export function retryAfter(value, now = Date.now()) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const raw = value.trim();
  const at = /^\d+$/.test(raw) ? now + Number(raw) * 1000
    : /^[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(raw) ? Date.parse(raw) : NaN;
  return Number.isFinite(at) && at <= 8.64e15 ? Math.max(now, at) : null;
}

function safeLocation(value) {
  try { const u = new URL(value); return u.origin + u.pathname; } catch { return null; }
}

export function trackNavigation(page, cooldowns) {
  const record = {document: null, failure: null};
  const mainDocument = request => request.isNavigationRequest() && request.frame() === page.mainFrame();
  page.on('request', request => {
    if (mainDocument(request)) { record.document = null; record.failure = null; }
  });
  page.on('response', response => {
    if (!mainDocument(response.request())) return;
    const headers = response.headers();
    const now = Date.now(), status = response.status();
    const retryAt = retryAfter(headers['retry-after'], now);
    record.document = {url: safeLocation(response.url()), status,
      challenge: headers['cf-mitigated'] === 'challenge',
      retry_at: retryAt === null ? null : new Date(retryAt).toISOString(),
      received_at: new Date(now).toISOString()};
    if ([429, 503].includes(status)) {
      const until = retryAt ?? (status === 429 ? now + 60000 : null);
      if (until !== null) {
        const origin = new URL(response.url()).origin;
        const previous = cooldowns.get(origin);
        if (!previous || previous.until < until) cooldowns.set(origin, {until, status,
          source: retryAt === null ? 'agent_60_second_backoff' : 'server_retry_after'});
      }
    }
  });
  page.on('requestfailed', request => {
    if (!mainDocument(request)) return;
    const error = request.failure()?.errorText || '';
    // Browser error strings can contain URLs or submitted secrets.
    record.failure = /CERT_|certificate|SSL|TLS/i.test(error) ? 'certificate_or_tls'
      : /NAME_NOT_RESOLVED|DNS/i.test(error) ? 'dns'
      : /TIMED_OUT|timeout/i.test(error) ? 'timeout'
      : /ABORTED|cancelled/i.test(error) ? 'navigation_aborted' : 'network';
  });
  return record;
}

export function assertNavigationAllowed(cooldowns, value) {
  const limit = cooldowns.get(new URL(value).origin);
  if (!limit) return;
  if (limit.until <= Date.now()) { cooldowns.delete(new URL(value).origin); return; }
  fail('ISOLATED_RETRY_LATER: ' + limit.source + '; next navigation after ' + new Date(limit.until).toISOString() + '. No request sent.');
}

export function accessDiagnostics(record, title = '', text = '') {
  const document = record?.document ?? null;
  const evidence = [], visible = title + '\n' + text.slice(0, 2000);
  let googleSignInRejected = false;
  try {
    const location = new URL(document?.url);
    // This is a provider rejection endpoint, including localized responses.
    // HTTP 200 is not successful authentication. Do not infer Google's reason.
    googleSignInRejected = document.status === 200 && location.origin === 'https://accounts.google.com'
      && /^\/(?:v\d+\/)?signin\/rejected\/?$/.test(location.pathname);
  } catch { /* No observed main-document URL. */ }
  let kind = 'none_detected';
  if (record?.failure) { kind = 'navigation_error'; evidence.push(record.failure); }
  else if (document?.challenge || /performing security verification|verif(?:y|ying) (?:that )?you are human|checking your browser|complete the captcha/i.test(visible)
      || /^Just a moment[.\s]*$/i.test(title)) {
    kind = 'challenge'; evidence.push(document?.challenge ? 'cf-mitigated: challenge' : 'visible_verification_page');
  } else if (document?.status === 429 || /too many requests|rate limit (?:exceeded|reached)/i.test(visible)) {
    kind = 'rate_limited'; evidence.push(document?.status === 429 ? 'http_429' : 'visible_rate_limit');
  } else if (googleSignInRejected) {
    kind = 'authentication_rejected'; evidence.push('google_signin_rejected_page');
  } else if ([401,403].includes(document?.status) || /access is temporarily restricted|forbidden: bot access not allowed/i.test(visible)
      || /^(?:Access Denied|Access Restricted|Forbidden)[.!\s]*$/i.test(title)) {
    kind = 'access_denied'; evidence.push([401,403].includes(document?.status) ? 'http_' + document.status : 'visible_access_denial');
  } else if (document?.status >= 400) { kind = 'http_error'; evidence.push('http_' + document.status); }
  return {kind, evidence, document,
    next: kind === 'challenge' ? 'Preserve this session; inspect the provider verification. Do not reload or submit repeatedly.'
      : kind === 'rate_limited' ? 'Honor retry_at or the bounded backoff; continue another site. No automatic retry.'
      : kind === 'authentication_rejected' ? 'Google rejected this sign-in; authentication is not complete. Preserve the session and use a supported sign-in or provider support route. The underlying rejection reason is unverified; do not repeat the rejected flow.'
      : kind === 'access_denied' ? 'Use a supported provider access or support route; no repeated submission.'
      : kind === 'navigation_error' || kind === 'http_error' ? 'Inspect the specific failure before retrying.'
      : 'No access barrier detected; this does not prove authentication or submission success.'};
}

// One reading of what a page is doing right now, from response and page evidence together.
// Observation only: a 403 alone is not a diagnosis, and a challenge on screen does not
// establish that a person is needed.
export function classifyAccess(current, {dialog = false} = {}) {
  const access = current.access || {}, requirements = current.auth?.requirements || [], readiness = current.readiness || {};
  const status = access.document?.status ?? null;
  const evidence = [...new Set([...(access.evidence || []), ...(status === null ? [] : ['http_' + status])])];
  let kind = 'no_barrier_detected';
  if (dialog) kind = 'dialog';
  else if (access.kind === 'navigation_error') kind = 'navigation_error';
  else if (access.kind === 'challenge' || requirements.includes('human_verification')) kind = 'challenge';
  else if (access.kind === 'rate_limited') kind = 'rate_limited';
  else if (access.kind === 'authentication_rejected') kind = 'authentication_rejected';
  else if (requirements.includes('password') || requirements.includes('verification_code')) kind = 'login_required';
  else if (requirements.includes('passkey_or_identity_prompt')) kind = 'presence_prompt';
  else if (access.kind === 'access_denied') kind = 'access_denied';
  else if (access.kind === 'http_error') kind = 'http_error';
  else if (readiness.busy || readiness.placeholder || readiness.has_rendered_text === false || readiness.document_state === 'loading') kind = 'loading';
  return {kind, transient: kind === 'loading' || kind === 'challenge', evidence, status};
}

const SETTLE_NEXT = {
  challenge: 'Still showing at the deadline, with no reload and no input. A person may be needed; that is not established. Keep this session and hand it off or check again later.',
  loading: 'Still loading at the deadline. This is not a sign-in or access result.',
  login_required: 'A sign-in form is showing. Verify which account this session belongs to; do not assume one.',
  presence_prompt: 'The provider is asking for a passkey or device confirmation. That step stays with a person.',
  access_denied: 'The provider refused this page. The status alone does not establish why.',
  rate_limited: 'Honor the reported deadline. Nothing was retried.',
  http_error: 'The provider returned an error status. Inspect before retrying.',
  navigation_error: 'The page could not be reached. Inspect before retrying.',
  authentication_rejected: 'The provider rejected this sign-in. Use a supported route; do not repeat it.',
  dialog: 'A dialog is open. Inspect it before anything else.',
  no_barrier_detected: 'No barrier detected. This does not prove sign-in, account or access; read the account back.',
};

export function settleNext(kind) { return SETTLE_NEXT[kind] || SETTLE_NEXT.no_barrier_detected; }

export async function waitForPageReadiness(page) {
  const start = Date.now();
  // Readiness is bounded and observable, not an assumption that network idle
  // means an SPA is ready. Expected fields still require browser_wait/readback.
  await page.waitForLoadState('domcontentloaded', {timeout: 2000}).catch(() => {});
  await page.waitForFunction(() => {
    const text = (document.body?.innerText || '').trim();
    const busy = [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"]')]
      .some(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
    const placeholder = /^(loading|please wait|redirecting)[.\s…]*$/i.test(text);
    return document.readyState !== 'loading' && !!text && !busy && !placeholder;
  }, null, {timeout: 2000, polling: 100}).catch(() => {});
  const current = await page.evaluate(() => ({
    document_state: document.readyState,
    has_rendered_text: !!document.body?.innerText.trim(),
    busy: [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"]')]
      .some(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden'),
    placeholder: /^(loading|please wait|redirecting)[.\s…]*$/i.test((document.body?.innerText || '').trim())
  })).catch(() => ({document_state:'unavailable',has_rendered_text:false,busy:false,placeholder:false}));
  return {...current, ready_for_snapshot: ['interactive','complete'].includes(current.document_state)
      && current.has_rendered_text && !current.busy && !current.placeholder,
    waited_ms: Date.now() - start,
    note:'Snapshot readiness only; wait for the expected target and verify action readback.'};
}

export function sensitiveMasks(page) {
  const selectors = ['input[type="password"]', 'input[autocomplete="one-time-code"]',
    'input[autocomplete="current-password"]', 'input[autocomplete="new-password"]',
    'input[name*="password" i]', 'input[name*="passcode" i]', 'input[name*="token" i]',
    'input[name*="secret" i]', 'input[name*="verification" i]', 'input[name*="otp" i]'];
  return page.frames().map(frame => frame.locator(selectors.join(',')));
}

// The original node must be detached. A merely hidden/disabled original never
// authorizes selecting a different element. Scope stays in the observed frame.
export async function recoverElement(item) {
  if (await item.handle.evaluate(el=>el.isConnected).catch(()=>false)) return {handle:item.handle,rebound:false};
  const anchor = item.anchor;
  if (!anchor || !item.frame || ![anchor.id,anchor.name,anchor.label,anchor.placeholder].some(Boolean))
    fail('ELEMENT_DETACHED: take a new snapshot; this element has no unique observed identity');
  const candidates = await item.frame.$$(anchor.tag).catch(()=>[]);
  const matches = [];
  for (const handle of candidates) {
    const match = await handle.evaluate((el,a)=>el.isConnected && el.tagName.toLowerCase()===a.tag &&
      (el.getAttribute('type') || '').toLowerCase()===a.type && el.id===a.id && (el.getAttribute('name') || '')===a.name &&
      (el.getAttribute('aria-label') || '')===a.label && (el.getAttribute('placeholder') || '')===a.placeholder &&
      (el.form?.id || '')===a.formId && (el.form?.getAttribute('action') || '')===a.formAction,anchor).catch(()=>false);
    if (match) matches.push(handle); else await handle.dispose();
  }
  if (matches.length !== 1) {
    await Promise.allSettled(matches.map(h=>h.dispose()));
    fail('ELEMENT_DETACHED: no unique replacement; take a fresh snapshot');
  }
  await item.handle.dispose().catch(()=>{});
  item.handle=matches[0];
  return {handle:item.handle,rebound:true};
}

async function associatedCheckLabel(handle) {
  // This is the label of the exact observed input, never a text-match guess.
  const candidate=await handle.evaluateHandle(el=>el.labels?.length===1 ? el.labels[0] : null);
  const label=candidate.asElement();
  if (label && await label.isVisible()) return label;
  await candidate.dispose();
  return null;
}

async function setObservedCheck(handle, checked) {
  if (await handle.isChecked()===checked) return false;
  const label=await associatedCheckLabel(handle);
  try {
    // Styled forms often put the real input far outside the viewport. Activate
    // its one visible native label with normal engine input, without force.
    if (label) {
      await label.click();
      if (await handle.isChecked()!==checked) throw new Error('label readback mismatch');
      return true;
    }
    await handle.setChecked(checked);
    return false;
  } finally { await label?.dispose(); }
}

export async function fillForm(state, fields, observed) {
  if (!Array.isArray(fields) || fields.length < 1 || fields.length > 50)
    fail('INVALID_FORM: provide 1-50 observed fields');
  const plan = [], seen = new Set();
  let rebound = 0, labelsUsed = 0;
  // Resolve and validate every target before the first input event.
  for (const [index, field] of fields.entries()) {
    const item = observed(state, field.element);
    if (item.kind !== 'element' || seen.has(field.element)) fail('INVALID_FORM: targets must be unique observed form elements');
    seen.add(field.element);
    if ((await recoverElement(item)).rebound) rebound++;
    const meta = await item.handle.evaluate(el => ({tag:el.tagName.toLowerCase(),type:el.type,
      disabled:el.disabled,readOnly:el.readOnly,editable:el.isContentEditable,multiple:el.multiple,
      options:el.options ? [...el.options].map(o=>({value:o.value,label:o.label,disabled:o.disabled || o.parentElement?.disabled})) : []}));
    let visible=await item.handle.isVisible();
    if (!visible && field.action==='check' && !meta.disabled) {
      const label=await associatedCheckLabel(item.handle);
      visible=!!label;
      await label?.dispose();
    }
    if (meta.disabled || !visible) fail('INVALID_FORM: target ' + index + ' is disabled or hidden');
    if (field.action === 'fill') {
      if (typeof field.text !== 'string' || meta.readOnly || !(['input','textarea'].includes(meta.tag) || meta.editable) ||
          meta.tag === 'input' && ['checkbox','radio','file','button','submit','reset','image','hidden','range','color'].includes(meta.type))
        fail('INVALID_FORM: target ' + index + ' is not a writable text field');
    } else if (field.action === 'check') {
      if (typeof field.checked !== 'boolean' || meta.tag !== 'input' || !['checkbox','radio'].includes(meta.type) || meta.type === 'radio' && !field.checked)
        fail('INVALID_FORM: target ' + index + ' requires a checkbox state or selected radio');
    } else if (field.action === 'select') {
      const choices = field.labels ?? field.values;
      const key = field.labels ? 'label' : 'value';
      if (meta.tag !== 'select' || field.labels && field.values || !Array.isArray(choices) || !choices.length ||
          new Set(choices).size !== choices.length || !meta.multiple && choices.length !== 1 ||
          choices.some(value=>typeof value !== 'string' || meta.options.filter(o=>o[key] === value && !o.disabled).length !== 1))
        fail('INVALID_FORM: target ' + index + ' requires unambiguous enabled option values or labels');
    } else fail('INVALID_FORM: unsupported field action');
    plan.push({item,field,index});
  }
  let completed = 0;
  for (const {item,field} of plan) {
    try {
      const recovered = await recoverElement(item);
      const handle = recovered.handle;
      if (recovered.rebound) rebound++;
      if (field.action === 'fill') await handle.fill(field.text);
      else if (field.action === 'check') { if (await setObservedCheck(handle,field.checked)) labelsUsed++; }
      else await handle.selectOption(field.labels ? field.labels.map(label=>({label})) : field.values);
      const matches = await handle.evaluate((el, f) => f.action === 'fill'
        ? (el.isContentEditable ? el.textContent : el.value) === f.text
        : f.action === 'check' ? el.checked === f.checked
        : [...el.selectedOptions].map(o=>f.labels ? o.label : o.value).sort().join('\0') === [...(f.labels ?? f.values)].sort().join('\0'), field);
      if (!matches) throw new Error('readback mismatch');
      completed++;
    } catch {
      fail('ISOLATED_FORM_PARTIAL: ' + completed + ' of ' + plan.length + ' fields confirmed; the next field outcome is uncertain. Take a fresh snapshot before retrying.');
    }
  }
  return {fields_confirmed:completed,targets_rebound:rebound,associated_labels_used:labelsUsed,submitted:false,next:'Inspect fresh field validity, then use the observed submit button when authorized.'};
}

export async function waitForCondition(state, page, input, observed) {
  const timeout = input.timeout_ms ?? 10000;
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 25000) fail('INVALID_WAIT: timeout_ms must be 1-25000');
  if (!['text','url','visible','hidden','enabled'].includes(input.condition)) fail('INVALID_WAIT: unsupported condition');
  let handle;
  if (['visible','hidden','enabled'].includes(input.condition)) {
    const item = observed(state,input.element);
    if (item.kind !== 'element') fail('INVALID_WAIT: expected an observed page element');
    handle = item.handle;
  } else if (typeof input.text !== 'string' || !input.text || input.text.length > 2000)
    fail('INVALID_WAIT: provide bounded nonempty text');
  try {
    if (input.condition === 'url') await page.waitForURL(url=>url.href.includes(input.text),{timeout,waitUntil:'domcontentloaded'});
    else if (input.condition === 'text') await page.getByText(input.text,{exact:false}).first().waitFor({state:'visible',timeout});
    else await handle.waitForElementState(input.condition,{timeout});
    return {matched:true,condition:input.condition};
  } catch (error) {
    if (error?.name !== 'TimeoutError') throw error;
    return {matched:false,timed_out:true,condition:input.condition,next:'Inspect a fresh snapshot; do not repeat a prior submission blindly.'};
  }
}
