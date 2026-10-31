// All input is delivered inside a headless engine over private pipes.
// No desktop events, OS clipboard, browser activation, or desktop capture.
import {createRequire} from 'node:module';
import {createInterface} from 'node:readline';
import {mkdir, stat, chmod, readFile, lstat, writeFile, rename, unlink, link} from 'node:fs/promises';
import {homedir} from 'node:os';
import path from 'node:path';
import {randomUUID, createHash} from 'node:crypto';
import {authHints, sensitiveMasks, fillForm, waitForCondition, trackNavigation,
  assertNavigationAllowed, accessDiagnostics, waitForPageReadiness, recoverElement, classifyAccess, settleNext} from './workflow.mjs';
import {checkpoint} from './checkpoint.mjs';
import {loadExecutionState, saveExecutionState, actionReceipt, clickAndVerify} from './execution.mjs';

const require = createRequire(import.meta.url);
const playwright = require(process.env.BL_BROWSER_PLAYWRIGHT);
const session = process.env.BL_BROWSER_SESSION || randomUUID();
if (!/^[a-zA-Z0-9_-]{1,80}$/.test(session)) throw new Error('Invalid isolated session');
const profileId = process.env.BL_BROWSER_PROFILE_ID;
if (profileId && !/^[a-f0-9]{24}$/.test(profileId)) throw new Error('Invalid private profile ID');
const accountId = process.env.BL_BROWSER_ACCOUNT_REF;
if (accountId && !/^[a-f0-9]{24}$/.test(accountId)) throw new Error('Invalid account session reference');
const stateRoot = process.env.BL_BROWSER_STATE_ROOT || path.join(homedir(), '.blacklabel/isolated-browser');
if (!path.isAbsolute(stateRoot)) throw new Error('Invalid state root');
const PROTOCOL = 'bl-account-exec/1';
// An owner-run handoff shows this exact store to a person. It reads the page and sends no input.
const handoff = process.env.BL_BROWSER_HANDOFF === '1';
const HANDOFF_COMMANDS = ['status','open','snapshot','settle','page_meta','auth'];
// Its checks only: stays hidden, and tab controls stand in for the person's own hands.
const handoffCheck = handoff && process.env.BL_BROWSER_HANDOFF_HIDDEN === '1';
const MAX_TABS = 5;
const states = new Map();
const failure = message => { throw new Error(message); };
const ownError = /^(STALE_ELEMENT|INVALID_|ISOLATED_|NO_|ELEMENT_|UNSUPPORTED_|FILE_|FOCUS_|CREDENTIAL_|SESSION_)/;

function urlFor(value) {
  let url;
  try { url = new URL(value); } catch { failure('INVALID_URL: expected an HTTP(S) URL'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
    failure('INVALID_URL: expected HTTP(S) without embedded credentials');
  return url.href;
}

async function invalidate(state) {
  const handles = [...state.elements.values()].map(x => x.handle).filter(Boolean);
  state.elements.clear(); state.generation = ''; state.observed = 0;
  await Promise.allSettled(handles.map(x => x.dispose()));
}

function registerPage(state, page) {
  if (state.pages.has(page)) return;
  state.pages.set(page, randomUUID());
  state.navigation.set(page, trackNavigation(page, state.cooldowns));
  page.on('filechooser', chooser => { state.choosers.set(page,chooser); });
  page.on('dialog', dialog => { state.dialogs.set(page,dialog); });
  page.on('close', () => { state.pages.delete(page); state.choosers.delete(page); state.dialogs.delete(page); state.navigation.delete(page); });
  // A navigation invalidates observations even when caused by a site's timer.
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) { state.observed = 0; state.choosers.delete(page); }
  });
  page.on('download', async download => {
    const directory = path.join(state.directory, 'downloads');
    await mkdir(directory, {recursive: true, mode: 0o700});
    const target = path.join(directory, randomUUID() + '-' + path.basename(download.suggestedFilename()));
    try { await download.saveAs(target); state.downloads.push({path: target, name: download.suggestedFilename()}); }
    catch { state.downloads.push({status: 'failed'}); }
  });
}

async function restoreSessionCookies(context, directory) {
  const file = path.join(directory,'session-cookies.json');
  const info = await lstat(file).catch(error=>{if(error.code === 'ENOENT')return null;throw error;});
  if (!info) return;
  if (!info.isFile() || info.isSymbolicLink() || info.size > 2_000_000)
    failure('ISOLATED_PROFILE_STATE_INVALID: private session state is not a bounded regular file');
  let saved;
  try { saved=JSON.parse(await readFile(file,'utf8')); }
  catch { failure('ISOLATED_PROFILE_STATE_INVALID: private session state cannot be decoded'); }
  if (saved.version !== 1 || !Array.isArray(saved.cookies) || saved.cookies.length > 3000)
    failure('ISOLATED_PROFILE_STATE_INVALID: unsupported private session state');
  try { await context.addCookies(saved.cookies); }
  catch { failure('ISOLATED_PROFILE_STATE_INVALID: private session cookies could not be restored'); }
}

async function saveSessionCookies(state) {
  // Only this isolated engine's own cookies; no personal-profile import surface.
  // An account session keeps persistent cookies here too: the engine's own store
  // commits on a delay, so a crash just after login would otherwise lose the login.
  const all = await state.context.cookies();
  const cookies = accountId && all.length <= 2500 ? all : all.filter(cookie=>cookie.expires === -1);
  const encoded = JSON.stringify({version:1,cookies});
  if (encoded === state.savedCookies) return;
  const target = path.join(state.directory,'session-cookies.json');
  const temporary = target + '.' + randomUUID() + '.tmp';
  try {
    await writeFile(temporary,encoded,{mode:0o600,flag:'wx'});
    await rename(temporary,target);
    state.savedCookies=encoded;
  } finally { await unlink(temporary).catch(()=>{}); }
}

async function stateFor(browser = 'chrome') {
  if (!['chrome', 'safari'].includes(browser)) failure('INVALID_BROWSER: expected chrome or safari');
  if (states.has(browser)) return states.get(browser);
  const directory = accountId ? path.join(stateRoot, 'accounts', accountId, browser)
    : path.join(stateRoot, profileId ? 'profiles' : 'sessions', profileId || session, browser);
  await mkdir(directory, {recursive: true, mode: 0o700});
  await chmod(directory, 0o700);
  const engine = browser === 'safari' ? playwright.webkit : playwright.chromium;
  const options = {headless: true, viewport: {width: 1440, height: 1000},
    acceptDownloads: true, timeout: 25000};
  if (handoff && !handoffCheck) options.headless = false;
  if (browser === 'chrome') options.channel = 'chrome';
  let context;
  try { context = await engine.launchPersistentContext(directory, options); }
  catch { failure('ISOLATED_ENGINE_UNAVAILABLE: run install.py to verify the private engine; desktop fallback is disabled'); }
  let execution;
  try { await restoreSessionCookies(context,directory); execution=await loadExecutionState(directory); }
  catch(error) { await context.close();throw error; }
  context.setDefaultTimeout(6000);
  context.setDefaultNavigationTimeout(20000);
  const state = {context, directory, pages: new Map(), elements: new Map(), generation: '',
    observed: 0, page: null, choosers: new Map(), dialogs: new Map(), navigation: new Map(), execution, cooldowns: execution.cooldowns, addressFocused: false, address: '', downloads: [], events: [], pendingPages: new Set()};
  Object.defineProperties(state, {
    chooser:{get(){return this.choosers.get(this.page) || null;},set(value){if(value)this.choosers.set(this.page,value);else this.choosers.delete(this.page);}},
    dialog:{get(){return this.dialogs.get(this.page) || null;},set(value){if(value)this.dialogs.set(this.page,value);else this.dialogs.delete(this.page);}}
  });
  states.set(browser, state);
  context.on('page', page => {
    if (state.pages.size >= MAX_TABS) {
      state.events.push({type:'popup_blocked',reason:'five_tab_limit'});
      state.events = state.events.slice(-20);
      const closing = page.close().catch(()=>{}).finally(()=>state.pendingPages.delete(closing));
      state.pendingPages.add(closing);
      return;
    }
    registerPage(state, page); state.page = page;
  });
  for (const page of context.pages()) {
    if (state.pages.size < MAX_TABS) registerPage(state, page);
    else await page.close();
  }
  state.page = [...state.pages.keys()].at(-1) || await context.newPage();
  return state;
}

async function selectedPage(state) {
  if (!state.page || state.page.isClosed()) {
    const remaining = [...state.pages.keys()].at(-1);
    // A person closing the last window ends an owner handoff. Opening another would trap them.
    if (!remaining && handoff) failure('ISOLATED_HANDOFF_CLOSED: the person closed the window');
    state.page = remaining || await state.context.newPage();
  }
  return state.page;
}

function observed(state, id) {
  const item = state.elements.get(id);
  if (!item || !state.observed || Date.now() - state.observed > 90000 || item.page !== state.page)
    failure('STALE_ELEMENT: take a fresh snapshot and use its current IDs');
  return item;
}

function semanticQuery(input) {
  const q=input || {};
  const roles=['button','link','textbox','checkbox','combobox','heading','file','radio'];
  const tags=['a','button','input','textarea','select','summary'];
  if (!(q.name || q.role || q.tag) || q.name !== undefined && (typeof q.name !== 'string' || !q.name.trim() || q.name.length>200) ||
      q.role !== undefined && !roles.includes(q.role) || q.tag !== undefined && !tags.includes(q.tag) ||
      q.exact !== undefined && typeof q.exact !== 'boolean' || q.limit !== undefined && (!Number.isInteger(q.limit) || q.limit<1 || q.limit>100))
    failure('INVALID_FIND: provide a bounded name, supported role or tag, and limit 1-100');
  return {...q,exact:q.exact ?? true,limit:q.limit ?? 20};
}

function semanticMatch(row, q) {
  if (!q) return true;
  const normalized=text=>String(text || '').replace(/\s+/g,' ').trim().toLowerCase();
  if (q.name) {
    const actual=normalized(row.title), wanted=normalized(q.name);
    if (q.exact ? actual!==wanted : !actual.includes(wanted)) return false;
  }
  if (q.tag && row.tag!==q.tag) return false;
  if (q.role) {
    const aliases={button:['AXButton','button'],link:['AXLink','link'],textbox:['AXTextField','AXTextArea','textbox'],
      checkbox:['AXCheckBox','checkbox'],combobox:['AXPopUpButton','combobox'],heading:['AXHeading','heading'],radio:['radio']};
    if (q.role==='file') { if (row.tag!=='input' || row.type!=='file') return false; }
    else if (q.role==='radio') { if (row.type!=='radio' && row.role!=='radio') return false; }
    else if (!aliases[q.role].includes(row.role)) return false;
  }
  return true;
}

async function snapshot(state, browser, query = null) {
  const page = await selectedPage(state);
  await invalidate(state);
  const readiness = state.dialog ? null : await waitForPageReadiness(page);
  state.generation = randomUUID().slice(0, 8);
  state.observed = Date.now();
  const idFor = suffix => state.generation + ':' + suffix;
  const rows = [];
  const windows = [];
  if (state.dialog) {
    return {browser,headless:true,desktop_untouched:true,url:page.url(),generation:state.generation,
      elements:[{id:idFor('dialog'),role:'AXDialog',title:state.dialog.type(),description:state.dialog.message().slice(0,1000)}],
      windows:[],truncated:false,captured_at:new Date().toISOString(),
      next:'Inspect the dialog; browser_key return accepts or escape dismisses in the agent browser.'};
  }
  for (const [candidate, id] of state.pages) {
    if (candidate.isClosed()) continue;
    const element = idFor('window:' + id);
    state.elements.set(element, {page, targetPage: candidate, kind: 'window'});
    windows.push({id: element, title: state.dialogs.has(candidate) ? '[dialog open]' : await candidate.title(), url: candidate.url()});
  }
  const addressId = idFor('address');
  state.elements.set(addressId, {page, kind: 'address'});
  rows.push({id: addressId, role: 'AXTextField', description: 'Agent browser address',
    value: state.addressFocused ? state.address : page.url(), focused: state.addressFocused});
  const frames = page.frames();
  let matching = 0;
  for (const [frameIndex,frame] of frames.entries()) {
    const handles = await frame.$$('a,button,input,textarea,select,option,[role],[contenteditable],h1,h2,h3,p,li,output,label,summary,td,th,dt,dd,legend');
    let inspected;
    try {
      // Serialize the exact observed handles in one engine round trip. Indices
      // retain node identity even if DOM ordering changes during inspection.
      inspected = await frame.evaluate(elements => elements.map(el => {
          // Closed details can retain nonzero child rectangles. They are not actionable.
          for (let parent = el.parentElement; parent; parent = parent.parentElement) {
            if (parent.tagName === 'DETAILS' && !parent.open &&
                !parent.querySelector(':scope > summary')?.contains(el)) return null;
          }
          const rect = el.getBoundingClientRect();
          const css = getComputedStyle(el);
          if (!rect.width || !rect.height || css.visibility === 'hidden' || css.display === 'none') return null;
          const tag = el.tagName.toLowerCase();
          const type = (el.getAttribute('type') || '').toLowerCase();
          const role = el.getAttribute('role') || (tag === 'input' && ['checkbox','radio'].includes(type) ? 'AXCheckBox' : ({a:'AXLink',button:'AXButton',input:'AXTextField',textarea:'AXTextArea',select:'AXPopUpButton',option:'AXMenuItem',h1:'AXHeading',h2:'AXHeading',h3:'AXHeading'}[tag])) || 'AXStaticText';
          const labels = el.labels ? [...el.labels].map(x => x.innerText).join(' ') : '';
          const labelledby = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.innerText || '').join(' ');
          const name = (el.getAttribute('aria-label') || labelledby.trim() || labels || el.getAttribute('placeholder') || el.innerText || el.getAttribute('title') || '').slice(0, 1800);
          const secure = type === 'password' || ['one-time-code','current-password','new-password'].includes(el.autocomplete) || /password|passcode|verification.?code|token|secret|otp/i.test(el.name || '');
          const value = secure ? '[secure field]' : String(el.value ?? el.innerText ?? '').slice(0, 2000);
          return {role,tag,type,title:name,description:name,value,
            url:tag === 'a' ? el.href : '', enabled:!el.disabled, focused:document.activeElement === el,
            frame:[rect.x,rect.y,rect.width,rect.height], actions:['press'], secure, autocomplete:el.autocomplete || '', required:!!el.required,
            invalid:el.validity ? !el.validity.valid : el.getAttribute('aria-invalid') === 'true',
            constraints:el.validity ? {minLength:el.minLength,maxLength:el.maxLength,min:el.min,max:el.max,step:el.step} : undefined,
            validation:el.validity ? Object.fromEntries(['valueMissing','typeMismatch','tooShort','tooLong','rangeUnderflow','rangeOverflow','stepMismatch','patternMismatch','customError'].map(key=>[key,el.validity[key]])) : undefined,
            checked:typeof el.checked === 'boolean' ? el.checked : undefined,
            options:tag === 'select' ? [...el.options].map(x=>({label:x.label,value:x.value,selected:x.selected,disabled:x.disabled})) : undefined,
            anchor:{tag,type,id:el.id || '',name:el.getAttribute('name') || '',label:el.getAttribute('aria-label') || '',
              placeholder:el.getAttribute('placeholder') || '',formId:el.form?.id || '',formAction:el.form?.getAttribute('action') || ''}};
      }), handles);
    } catch {
      await Promise.allSettled(handles.map(handle=>handle.dispose()));
      continue;
    }
    const discarded = [];
    for (const [index,handle] of handles.entries()) {
      const row = inspected[index];
      if (!row || !semanticMatch(row,query)) { discarded.push(handle); continue; }
      matching++;
      if (rows.length >= (query ? query.limit+1 : 700)) { discarded.push(handle); continue; }
      const {anchor,...publicRow} = row;
      const id = idFor(rows.length);
      state.elements.set(id, {handle, page, frame, anchor, kind: 'element'});
      rows.push({id, ...publicRow,frame_index:frameIndex});
    }
    await Promise.allSettled(discarded.map(handle=>handle.dispose()));
  }
  if (state.dialog) rows.push({id:idFor('dialog'),role:'AXDialog',title:state.dialog.type(),description:state.dialog.message().slice(0,1000)});
  if (state.chooser) rows.push({id:idFor('filechooser'),role:'AXFileChooser',title:'Choose a file in the agent browser'});
  const renderedText = await page.locator('body').innerText({timeout:3000}).catch(()=> '');
  const title = await page.title();
  const access = accessDiagnostics(state.navigation.get(page), title, renderedText);
  return {browser,engine:browser === 'safari' ? 'webkit' : 'chromium',headless:true,
    desktop_untouched:true,url:page.url(),title,generation:state.generation,readiness,access,viewport:page.viewportSize(),frame_count:frames.length,
    text:renderedText.slice(0,20000),text_truncated:renderedText.length>20000,elements:rows,windows,tabs_limit:MAX_TABS,events:[...state.events],auth:authHints(rows,renderedText,access),matching_elements:matching,truncated:matching>rows.length-1,downloads:state.downloads,
    captured_at:new Date().toISOString()};
}

// Observe, wait with a deadline, inspect for change, then report. Never reloads, clicks or types.
async function settleAccess(state, browser, input) {
  const budget = input.budget_ms ?? 20000;
  if (!Number.isInteger(budget) || budget < 0 || budget > 25000) failure('INVALID_SETTLE: budget_ms must be 0-25000; call again to extend');
  const started = Date.now(), stages = [];
  const safe = location => { try { const url = new URL(location); return url.origin + url.pathname; } catch { return ''; } };
  let current, reading, previous = null, changes = 0;
  for (;;) {
    current = await snapshot(state,browser);
    reading = classifyAccess(current,{dialog:!!state.dialog});
    const signature = current.url + '\n' + (current.title || '') + '\n' + (current.text || '').slice(0,2000);
    const changed = previous !== null && signature !== previous;
    if (changed) changes++;
    if (!stages.length || changed || stages.at(-1).kind !== reading.kind)
      stages.push({stage:stages.length ? 'inspect' : 'observe',at_ms:Date.now()-started,kind:reading.kind,status:reading.status,url:safe(current.url),changed});
    previous = signature;
    const remaining = budget-(Date.now()-started);
    if (!reading.transient || remaining <= 0) break;
    await (await selectedPage(state)).waitForTimeout(Math.min(1000,remaining));
  }
  return {browser,headless:!handoff,desktop_untouched:!handoff,kind:reading.kind,transient:reading.transient,evidence:reading.evidence,status:reading.status,
    retry_at:current.access?.document?.retry_at ?? null,waited_ms:Date.now()-started,budget_ms:budget,reloads:0,input_sent:false,changes,stages:stages.slice(-30),
    url:safe(current.url),title:current.title,next:settleNext(reading.kind)};
}

// Named metadata only, for a provider's stable identity tag. Never arbitrary script.
async function pageMeta(page, names) {
  if (!Array.isArray(names) || !names.length || names.length > 10 || names.some(name=>typeof name !== 'string' || !/^[a-zA-Z0-9:_.-]{1,80}$/.test(name)))
    failure('INVALID_META: request 1-10 plain metadata names');
  return page.evaluate(list=>Object.fromEntries(list.map(name=>[name,document.querySelector(`meta[name="${name}"],meta[property="${name}"]`)?.content ?? null])),names);
}

// Broker-only: not an MCP tool, so the model can neither call it nor name a target
// origin. The value goes only into the observed field of the bound origin and type.
async function boundFill(state, page, input) {
  const item = observed(state,input.element);
  if (item.kind !== 'element') failure('INVALID_ELEMENT: expected an observed page element');
  const allowed = input.allowed_origins, value = String(input.text ?? '');
  if (!Array.isArray(allowed) || !allowed.length || allowed.length > 8) failure('CREDENTIAL_BINDING_INVALID: permitted origins are required; no value was sent');
  if (!value || value.length > 4096) failure('CREDENTIAL_VALUE_INVALID: no value was sent');
  const originOf = location=>{ try { return new URL(location).origin; } catch { return null; } };
  const current = new URL(page.url());
  const pageOrigin = current.origin, frameOrigin = item.frame === page.mainFrame() ? pageOrigin : originOf(item.frame.url());
  const privateChannel = current.protocol === 'https:' || ['localhost','127.0.0.1','[::1]'].includes(current.hostname);
  if (!allowed.includes(pageOrigin) || !allowed.includes(frameOrigin) || !privateChannel)
    failure('CREDENTIAL_ORIGIN_MISMATCH: this page is not a permitted origin for the bound account; no value was sent');
  const field = await item.handle.evaluate(el=>({tag:el.tagName.toLowerCase(),type:(el.getAttribute('type') || 'text').toLowerCase(),
    autocomplete:el.autocomplete || '',disabled:!!el.disabled,readOnly:!!el.readOnly}));
  const textual = ['text','email','tel','number','search'].includes(field.type);
  const permitted = field.tag === 'input' && !field.disabled && !field.readOnly && (
    input.kind === 'password' ? field.type === 'password'
    : input.kind === 'username' ? textual
    : input.kind === 'code' ? textual || field.autocomplete === 'one-time-code' : false);
  if (!permitted) failure('CREDENTIAL_FIELD_MISMATCH: the observed field is not the expected kind; no value was sent');
  await item.handle.fill(value);
  if (!await item.handle.evaluate((el,expected)=>el.value === expected,value)) failure('CREDENTIAL_FILL_UNCONFIRMED: the field did not retain the value');
  return {filled:true,kind:input.kind,origin:pageOrigin,next:'Inspect a fresh snapshot; a filled field is not a sign-in.'};
}

async function perform(input) {
  const {command} = input;
  if (command === 'status') {
    // Exercise the actual launch path; a config flag is not readiness evidence.
    await stateFor('chrome');
    return {ready:true,mode:'isolated-headless',headless:true,session,
      owner_cursor_protected:true,physical_pointer_input:false,desktop_keyboard_input:false,
      desktop_screen_capture:false,desktop_activation:false,extension_required:false,
      owner_debugging_toggle_required:false,debugging_transport:'private pipe; no listening TCP port',
      accessibility_required:false,screen_recording_required:false,
      profile:accountId ? 'account session' : profileId ? 'named isolated profile' : 'chat-isolated profile',profile_id:profileId || session,
      session_reference:process.env.BL_BROWSER_REFERENCE || (accountId ? 'acct_'+accountId : profileId ? 'profile:'+profileId : 'session:'+session),
      protocol_version:PROTOCOL,lease_generation:Number(process.env.BL_BROWSER_LEASE_GENERATION) || null,owner_handoff:handoff,
      named_profile:!!profileId,tabs_limit:MAX_TABS,owner_profile_imported:false,
      navigation_diagnostics:true,retry_after_guard:true,durable_receipts:true,rerender_recovery:true,semantic_lookup:true,native_resolution_capture:true,draft_checkpoints:true,
      browsers:[...states.keys()].map(name=>({name,running:true,headless:true}))};
  }
  if (!['open','snapshot','focus_window','click','fill','type','key','click_at','scroll','choose_file','screenshot','tabs','form','wait','auth','hover','move','click_verify','receipt','find','viewport','capture','checkpoint','bound_fill','page_meta','settle'].includes(command))
    failure('UNSUPPORTED_COMMAND: unknown isolated browser operation');
  if (handoff && !HANDOFF_COMMANDS.includes(command) && !(handoffCheck && command === 'tabs')) failure('ISOLATED_HANDOFF_READ_ONLY: a person has this session; no automated input is sent');
  if (command === 'open') urlFor(input.url);
  const browser = input.browser;
  const state = await stateFor(browser);
  await Promise.allSettled([...state.pendingPages]);
  if (command === 'receipt') return {receipt:actionReceipt(state,input.receipt_id),verification_current:false,
    next:'Saved action evidence only; inspect the current page to verify current status.'};
  if (command === 'tabs') {
    const action = input.action || 'list';
    try {
      if (action === 'open') {
        const target = urlFor(input.url);
        assertNavigationAllowed(state.cooldowns, target);
        if (state.pages.size >= MAX_TABS) failure('ISOLATED_TAB_LIMIT: close a completed tab before opening another; maximum five');
        const newPage = await state.context.newPage();
        state.page = newPage;
        await newPage.goto(target,{waitUntil:'domcontentloaded'});
      } else if (['select','close'].includes(action)) {
        const target = [...state.pages].find(([,id])=>id === input.tab)?.[0];
        if (!target || target.isClosed()) failure('INVALID_TAB: use a current tab ID from browser_tabs');
        if (action === 'select') state.page = target;
        else {
          if (state.page === target) { state.page = null; state.dialog = null; state.chooser = null; }
          await target.close();
          if (!state.page) state.page = [...state.pages.keys()].at(-1) || null;
        }
        state.addressFocused = false;
      } else if (action !== 'list') failure('INVALID_TAB_ACTION');
      const tabs = await Promise.all([...state.pages].map(async ([p,id])=>({id,url:p.url(),title:state.dialogs.has(p) ? '[dialog open]' : await p.title(),selected:p === state.page})));
      return {tabs,limit:MAX_TABS,events:[...state.events],headless:true,desktop_untouched:true};
    } finally { if (action !== 'list') await invalidate(state); }
  }
  const page = await selectedPage(state);
  if (command === 'checkpoint') {
    try {return {browser,headless:true,desktop_untouched:true,...await checkpoint(state,page,input,observed)};}
    finally {if (input.action==='restore') await invalidate(state);}
  }
  if (command === 'auth') {
    const current = await snapshot(state,browser);
    return {url:current.url,...(current.auth || authHints(current.elements)),access:current.access,readiness:current.readiness};
  }
  if (command === 'snapshot') return snapshot(state, browser);
  if (command === 'page_meta') return {browser,headless:true,desktop_untouched:true,url:page.url(),meta:await pageMeta(page,input.names)};
  if (command === 'settle') return settleAccess(state,browser,input);
  if (command === 'find') {
    const q=semanticQuery(input.query), current=await snapshot(state,browser,q);
    return {browser,headless:true,desktop_untouched:true,url:current.url,generation:current.generation,
      matches:current.elements.filter(e=>e.tag),match_count:current.matching_elements,truncated:current.truncated,query:q,
      viewport:current.viewport,frame_count:current.frame_count,access:current.access,
      next:'Use an exact returned element ID. Multiple matches require inspection; no target is selected automatically.'};
  }
  if (command === 'viewport') {
    if (![input.width,input.height].every(Number.isInteger) || input.width<320 || input.width>3840 || input.height<240 || input.height>2160)
      failure('INVALID_VIEWPORT: width 320-3840 and height 240-2160 are required');
    try {
      await page.setViewportSize({width:input.width,height:input.height});
      return {browser,viewport:page.viewportSize(),headless:true,desktop_untouched:true,next:'Read a fresh snapshot; coordinates and layout have changed.'};
    } finally { await invalidate(state); }
  }
  if (command === 'capture') {
    if (typeof input.path !== 'string' || !path.isAbsolute(input.path) || !input.path.toLowerCase().endsWith('.png') ||
        input.full_page !== undefined && typeof input.full_page !== 'boolean') failure('INVALID_CAPTURE: choose an absolute PNG path and optional full_page boolean');
    if (await lstat(input.path).catch(e=>{if(e.code==='ENOENT')return null;throw e;})) failure('FILE_EXISTS: choose a new capture filename; existing files are preserved');
    await waitForPageReadiness(page);
    const size=await page.evaluate(()=>({width:Math.max(document.documentElement.scrollWidth,innerWidth),height:Math.max(document.documentElement.scrollHeight,innerHeight)}));
    if (input.full_page && (size.width>3840 || size.height>16000 || size.width*size.height>32_000_000)) failure('INVALID_CAPTURE: full page exceeds the bounded image size; use a viewport capture');
    const temporary=path.join(path.dirname(input.path),'.browser-capture-'+randomUUID()+'.png');
    try {
      await page.screenshot({path:temporary,type:'png',fullPage:!!input.full_page,scale:'css',timeout:15000,
        mask:sensitiveMasks(page),maskColor:'#111111'});
      await chmod(temporary,0o600);
      const bytes=await readFile(temporary);
      await link(temporary,input.path); // Atomic no-overwrite publication of the local file.
      const source=new URL(page.url());source.search='';source.hash='';
      return {path:input.path,width:bytes.readUInt32BE(16),height:bytes.readUInt32BE(20),sha256:createHash('sha256').update(bytes).digest('hex'),
        source_url:source.href,captured_at:new Date().toISOString(),native_resolution:true,secure_fields_masked:true,headless:true,desktop_untouched:true};
    } finally { await unlink(temporary).catch(()=>{}); }
  }
  if (command === 'screenshot') {
    if (typeof input.path !== 'string' || !path.isAbsolute(input.path)) failure('INVALID_PATH: screenshot requires an absolute path');
    await page.screenshot({path:input.path,type:'png',timeout:10000,mask:sensitiveMasks(page),maskColor:'#111111'});
    return {path:input.path,headless:true,desktop_untouched:true,secure_fields_masked:true};
  }
  try {
    if (command === 'click_verify') {
      const result = await clickAndVerify(state,page,input,async()=>{
        const item = observed(state,input.element);
        if (item.kind !== 'element') failure('INVALID_ELEMENT: expected an observed page element');
        await recoverElement(item);
        return async()=>{
          let onDialog;
          const dialog=new Promise(resolve=>{onDialog=resolve;page.once('dialog',onDialog);});
          try { await Promise.race([item.handle.click(),dialog]); }
          finally { page.off('dialog',onDialog); }
        };
      });
      return {browser,headless:true,desktop_untouched:true,...result};
    } else if (command === 'bound_fill') {
      return {browser,headless:true,desktop_untouched:true,...await boundFill(state,page,input)};
    } else if (command === 'form') {
      return {browser,headless:true,desktop_untouched:true,...await fillForm(state,input.fields,observed)};
    } else if (command === 'wait') {
      return {browser,headless:true,desktop_untouched:true,...await waitForCondition(state,page,input,observed)};
    } else if (command === 'open') {
      const target = urlFor(input.url);
      assertNavigationAllowed(state.cooldowns, target);
      await page.goto(target, {waitUntil:'domcontentloaded'});
      state.addressFocused = false; state.chooser = null;
    } else if (command === 'focus_window') {
      const item = observed(state, input.element);
      if (item.kind !== 'window') failure('INVALID_ELEMENT: expected an observed agent page ID');
      state.page = item.targetPage; // No bringToFront, OS activation or desktop focus.
    } else if (command === 'hover') {
      const item = observed(state,input.element);
      if (item.kind !== 'element') failure('INVALID_ELEMENT: hover requires an observed page element');
      await item.handle.hover();
    } else if (['click','fill','type'].includes(command)) {
      const item = observed(state, input.element);
      if (item.kind === 'address') {
        if (command === 'click') state.addressFocused = true;
        else if (command === 'fill') { state.address = String(input.text ?? ''); state.addressFocused = true; }
        else if (state.addressFocused) state.address += String(input.text ?? '');
        else failure('FOCUS_CHANGED: agent address field is not selected');
      } else {
        if (item.kind !== 'element') failure('INVALID_ELEMENT: expected an observed page element');
        state.addressFocused = false;
        if (command === 'click') {
          let onDialog;
          const dialog = new Promise(resolve=>{ onDialog=resolve; page.once('dialog',onDialog); });
          try { await Promise.race([item.handle.click(),dialog]); }
          finally { page.off('dialog',onDialog); }
        }
        else if (command === 'fill') {
          const tag = await item.handle.evaluate(el=>el.tagName.toLowerCase());
          if (tag === 'select') await item.handle.selectOption({label:String(input.text ?? '')});
          else await item.handle.fill(String(input.text ?? ''));
        } else {
          if (!await item.handle.evaluate(el=>document.activeElement === el)) failure('FOCUS_CHANGED: snapshot field is not focused');
          await page.keyboard.insertText(String(input.text ?? ''));
        }
      }
    } else if (command === 'key') {
      const key = String(input.key || '').toLowerCase();
      if (/^(cmd|ctrl|control|meta)\+[cxv]$/.test(key)) {
        failure('UNSUPPORTED_KEY: use browser_fill or browser_type; system clipboard shortcuts are disabled');
      } else if (['cmd+l','ctrl+l','control+l','meta+l'].includes(key)) { state.addressFocused = true; state.address = ''; }
      else if (state.addressFocused && ['return','enter'].includes(key)) {
        const target = urlFor(state.address);
        assertNavigationAllowed(state.cooldowns, target);
        await page.goto(target,{waitUntil:'domcontentloaded'}); state.addressFocused = false;
      } else if (['cmd+w','ctrl+w','meta+w'].includes(key)) {
        await page.close();
      } else if (['cmd+r','ctrl+r','meta+r'].includes(key)) {
        assertNavigationAllowed(state.cooldowns, page.url());
        await page.reload({waitUntil:'domcontentloaded'});
      } else if (state.dialog && ['return','enter','escape'].includes(key)) {
        const dialog = state.dialog; state.dialog = null;
        if (key === 'escape') await dialog.dismiss(); else await dialog.accept();
      } else {
        const names = {cmd:'Meta',meta:'Meta',ctrl:'Control',control:'Control',shift:'Shift',alt:'Alt',option:'Alt',return:'Enter',enter:'Enter',tab:'Tab',escape:'Escape',space:'Space',backspace:'Backspace',delete:'Backspace',up:'ArrowUp',down:'ArrowDown',left:'ArrowLeft',right:'ArrowRight',home:'Home',end:'End',pageup:'PageUp',pagedown:'PageDown'};
        const chord = key.split('+').map(part=>names[part] || (/^[a-z0-9]$/.test(part)?part:null));
        if (!chord.length || chord.some(x=>!x)) failure('UNSUPPORTED_KEY: use a documented agent browser shortcut');
        await page.keyboard.press(chord.join('+'));
      }
    } else if (['click_at','move'].includes(command)) {
      const viewport=page.viewportSize();
      if (![input.x,input.y].every(x=>typeof x === 'number' && Number.isFinite(x) && x >= 0) || input.x >= viewport.width || input.y >= viewport.height)
        failure('INVALID_COORDINATES: use coordinates from the agent viewport screenshot');
      if (command === 'move') await page.mouse.move(input.x,input.y);
      else await page.mouse.click(input.x,input.y);
    } else if (command === 'scroll') {
      if (!Number.isInteger(input.amount) || Math.abs(input.amount)>20000) failure('INVALID_SCROLL: amount must be an integer within 20000 pixels');
      if (input.element) {
        const item = observed(state,input.element);
        if (item.kind !== 'element') failure('INVALID_ELEMENT: scroll target must be an observed page element');
        await item.handle.hover();
      }
      await page.mouse.wheel(0,input.amount);
      await page.waitForTimeout(100);
    } else if (command === 'choose_file') {
      if (typeof input.path !== 'string' || !path.isAbsolute(input.path)) failure('INVALID_PATH: choose an existing absolute file path');
      const file = await stat(input.path).catch(()=>null);
      if (!file?.isFile()) failure('FILE_NOT_FOUND: choose an existing regular file');
      if (!state.chooser) failure('NO_FILE_CHOOSER: click an observed upload control first');
      const chooser = state.chooser; state.chooser = null;
      await chooser.setFiles(input.path);
    }
    return {action_performed:true,browser,headless:true,desktop_untouched:true,url:(await selectedPage(state)).url(),
      next:'Take a fresh browser_snapshot and verify the actual result.'};
  } finally { await invalidate(state); }
}

const lines = createInterface({input:process.stdin,crlfDelay:Infinity});
for await (const line of lines) {
  if (!line.trim()) continue;
  let response;
  try {
    if (line.length>2_000_000) failure('INVALID_REQUEST: request exceeds 2MB');
    response = {ok:true,result:await perform(JSON.parse(line))};
    for (const state of states.values()) await saveSessionCookies(state);
  } catch (error) {
    // Engine call logs may include submitted secrets. Return only controlled errors.
    const message = String(error?.message || '');
    const safe = ownError.test(message) ? message : error?.name === 'TimeoutError'
      ? 'ISOLATED_ACTION_TIMEOUT: inspect a fresh snapshot; do not automatically repeat a mutation'
      : 'ISOLATED_ACTION_FAILED: inspect a fresh snapshot; desktop fallback is disabled';
    response = {ok:false,error:safe};
  }
  try { for (const state of states.values()) await saveExecutionState(state); }
  catch { response = {ok:false,error:'ISOLATED_EXECUTION_STATE_WRITE_FAILED: preserve and inspect action receipts before another mutation'}; }
  process.stdout.write(JSON.stringify(response)+'\n');
}
// Stdin closed: nobody can reach this worker again, so it must end. A stuck page or engine close
// cannot keep the store's lease alive. The engine's pipe closes with this process.
setTimeout(() => process.exit(0), 8000).unref();
for (const state of states.values()) {
  try { await saveSessionCookies(state); await saveExecutionState(state); } finally { await state.context.close(); }
}
process.exit(0);
