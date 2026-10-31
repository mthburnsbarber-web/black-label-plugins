// Explicit private draft checkpoints. No automatic navigation or submission.
import {lstat, readFile, writeFile, rename, unlink} from 'node:fs/promises';
import {randomUUID, createHash} from 'node:crypto';
import path from 'node:path';
import {fillForm} from './workflow.mjs';
import {actionReceipt} from './execution.mjs';

const fail = message => { throw new Error(message); };
const validId = id => typeof id === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(id);
const fingerprint = value => createHash('sha256').update(value).digest('hex');
const sensitive = /password|passcode|verification|one.?time|token|secret|otp|recovery|credit.?card|card.?number|cc-|cvv|cvc/i;
function cleanURL(value) {
  let u; try { u=new URL(value); } catch {}
  if (!u || !['https:','http:'].includes(u.protocol) || u.username || u.password || u.search || u.hash)
    fail('INVALID_CHECKPOINT: use a plain HTTP(S) page URL without query strings, fragments or credentials');
  return u.href;
}
function identityHash(value) {
  if (typeof value !== 'string' || !value.trim() || value.length>500)
    fail('INVALID_CHECKPOINT: provide the exact visible account or workspace identity');
  return fingerprint(value);
}
async function readStore(state) {
  const file=path.join(state.directory,'draft-checkpoints.json');
  const info=await lstat(file).catch(e=>{if(e.code==='ENOENT')return null;throw e;});
  if (!info) return Object.create(null);
  if (!info.isFile() || info.isSymbolicLink() || info.size>2_000_000)
    fail('ISOLATED_CHECKPOINT_INVALID: expected bounded private state');
  let value; try {value=JSON.parse(await readFile(file,'utf8'));} catch {}
  if (value?.version!==1 || !value.drafts || typeof value.drafts!=='object' || Array.isArray(value.drafts) || Object.keys(value.drafts).length>100)
    fail('ISOLATED_CHECKPOINT_INVALID: unsupported draft state');
  for (const [id,d] of Object.entries(value.drafts)) {
    if (!validId(id) || d.id!==id || !validId(d.receipt_id) || !/^[a-f0-9]{64}$/.test(d.identity_hash) ||
        !Array.isArray(d.fields) || !d.fields.length || d.fields.length>50 || !Number.isFinite(Date.parse(d.saved_at)))
      fail('ISOLATED_CHECKPOINT_INVALID: invalid draft record');
    cleanURL(d.url);
  }
  return Object.assign(Object.create(null),value.drafts);
}
async function writeStore(state,drafts) {
  const encoded=JSON.stringify({version:1,drafts});
  if (Object.keys(drafts).length>100 || Buffer.byteLength(encoded)>2_000_000) fail('ISOLATED_CHECKPOINT_FULL: preserve existing drafts');
  const file=path.join(state.directory,'draft-checkpoints.json'),temp=file+'.'+randomUUID()+'.tmp';
  try {await writeFile(temp,encoded,{flag:'wx',mode:0o600});await rename(temp,file);}
  finally {await unlink(temp).catch(()=>{});}
}
function summary(state,draft) {
  const receipt=actionReceipt(state,draft.receipt_id);
  return {id:draft.id,url:draft.url,fields_saved:draft.fields.length,saved_at:draft.saved_at,
    receipt_id:draft.receipt_id,receipt_state:receipt?.state || null,
    status:receipt ? 'action_recorded_reconcile' : 'draft_saved',form_values_returned:false};
}
async function checkIdentity(page,identity,hash) {
  let visible=false;
  if (identityHash(identity)===hash) for (const frame of page.frames()) {
    for (const match of (await frame.getByText(identity,{exact:true}).all()).slice(0,20))
      if (await match.isVisible()) visible=true;
  }
  if (!visible)
    fail('ISOLATED_CHECKPOINT_IDENTITY_MISMATCH: inspect the signed-in account; no fields changed');
}
async function captureField(item, validateOnly=false) {
  if (item.kind!=='element' || !item.anchor || ![item.anchor.id,item.anchor.name,item.anchor.label,item.anchor.placeholder].some(Boolean))
    fail('INVALID_CHECKPOINT_FIELD: use an observed uniquely named form control');
  const data=await item.handle.evaluate(el=>({connected:el.isConnected,tag:el.tagName.toLowerCase(),type:el.type || '',
    autocomplete:el.autocomplete || '',description:[el.id,el.name,el.getAttribute('aria-label'),el.getAttribute('placeholder'),
      ...Array.from(el.labels || [],label=>label.innerText)].join(' '),
    value:el.value,checked:el.checked,labels:el.options ? Array.from(el.selectedOptions,o=>o.label):null,
    disabled:el.disabled,readOnly:el.readOnly}));
  if (!data.connected || data.disabled || data.readOnly || sensitive.test(data.description+' '+data.autocomplete) ||
      ['password','file','hidden','submit','button','reset','image'].includes(data.type) ||
      !['input','select','textarea'].includes(data.tag))
    fail('INVALID_CHECKPOINT_FIELD: credentials, files, hidden and non-editable controls cannot be saved');
  const field={anchor:item.anchor,frame_url:cleanURL(item.frame.url())};
  if (validateOnly) return field;
  if (['checkbox','radio'].includes(data.type)) {
    if (data.type==='radio' && !data.checked) fail('INVALID_CHECKPOINT_FIELD: save only the selected radio');
    Object.assign(field,{action:'check',checked:data.checked});
  } else if (data.tag==='select') {
    if (!data.labels.length) fail('INVALID_CHECKPOINT_FIELD: select has no selected option');
    Object.assign(field,{action:'select',labels:data.labels});
  } else {
    if (typeof data.value!=='string' || data.value.length>20000) fail('INVALID_CHECKPOINT_FIELD: text is too large');
    Object.assign(field,{action:'fill',text:data.value});
  }
  return field;
}
async function matchField(page,field) {
  // Exact frame URL and all observed identity attributes; no fuzzy substitution.
  const frames=page.frames().filter(f=>f.url()===field.frame_url);
  const matches=[];
  for (const frame of frames) {
    if (!['input','select','textarea'].includes(field.anchor?.tag)) fail('ISOLATED_CHECKPOINT_INVALID: invalid control');
    for (const handle of await frame.$$(field.anchor.tag)) {
      const equal=await handle.evaluate((el,a)=>(el.getAttribute('type') || '').toLowerCase()===a.type &&
        (el.id || '')===a.id && (el.getAttribute('name') || '')===a.name &&
        (el.getAttribute('aria-label') || '')===a.label && (el.getAttribute('placeholder') || '')===a.placeholder &&
        (el.form?.id || '')===a.formId && (el.form?.getAttribute('action') || '')===a.formAction,field.anchor);
      if (equal) matches.push({handle,frame,anchor:field.anchor,kind:'element'});else await handle.dispose();
    }
  }
  if (matches.length!==1) {
    await Promise.allSettled(matches.map(item=>item.handle.dispose()));
    fail('ISOLATED_CHECKPOINT_TARGET_MISMATCH: control missing or ambiguous; no fields changed');
  }
  return matches[0];
}
export async function checkpoint(state,page,input,observed) {
  const drafts=await readStore(state), action=input.action || 'list';
  if (action==='list') return {checkpoints:Object.values(drafts).map(d=>summary(state,d)),form_values_returned:false};
  if (!validId(input.id)) fail('INVALID_CHECKPOINT_ID: use 1-100 letters, digits, underscores or hyphens');
  const draft=drafts[input.id];
  if (action==='delete') {
    if (!draft) fail('INVALID_CHECKPOINT_ID: saved draft not found');
    delete drafts[input.id];await writeStore(state,drafts);return {id:input.id,deleted:true};
  }
  if (action==='save') {
    if (draft) fail('ISOLATED_CHECKPOINT_EXISTS: existing draft preserved; explicitly delete before replacing');
    if (!validId(input.receipt_id)) fail('INVALID_RECEIPT_ID: bind the draft to its intended final action receipt');
    if (actionReceipt(state,input.receipt_id)) fail('ISOLATED_CHECKPOINT_ACTION_RECORDED: reconcile the existing final action');
    if (!Array.isArray(input.fields) || !input.fields.length || input.fields.length>50 || new Set(input.fields).size!==input.fields.length)
      fail('INVALID_CHECKPOINT: provide 1-50 unique observed control IDs');
    const hash=identityHash(input.identity);await checkIdentity(page,input.identity,hash);
    const fields=[];for (const id of input.fields) fields.push(await captureField(observed(state,id)));
    drafts[input.id]={id:input.id,url:cleanURL(page.url()),identity_hash:hash,receipt_id:input.receipt_id,
      viewport:page.viewportSize(),fields,saved_at:new Date().toISOString()};
    await writeStore(state,drafts);return summary(state,drafts[input.id]);
  }
  if (action!=='restore' || !draft) fail('INVALID_CHECKPOINT: choose a saved draft and supported action');
  if (actionReceipt(state,draft.receipt_id)) return {...summary(state,draft),restored:false,
    next:'Final action already attempted. Read its receipt and current provider state; do not restore or resubmit this draft.'};
  if (cleanURL(page.url())!==draft.url) fail('ISOLATED_CHECKPOINT_URL_MISMATCH: navigate to the saved page and inspect it first');
  await checkIdentity(page,input.identity,draft.identity_hash);
  const items=[];
  try {
    for (const field of draft.fields) {
      const item=await matchField(page,field);items.push(item);
      // Reapply the same no-secret/no-file policy to the live replacement.
      await captureField(item,true);
    }
    const fields=draft.fields.map((field,index)=>({element:String(index),action:field.action,
      ...(field.action==='fill'?{text:field.text}:field.action==='check'?{checked:field.checked}:{labels:field.labels})}));
    const result=await fillForm(state,fields,(_,id)=>items[Number(id)]);
    return {...summary(state,draft),restored:true,fields_confirmed:result.fields_confirmed,submitted:false,
      next:'Inspect every restored field, reattach required files, then use the bound receipt ID for the final action.'};
  } finally {await Promise.allSettled(items.map(item=>item.handle.dispose()));}
}
