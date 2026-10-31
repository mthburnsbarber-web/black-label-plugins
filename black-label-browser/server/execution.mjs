// Durable, private evidence for one-shot actions. Never stores form values.
import {lstat, readFile, writeFile, rename, unlink} from 'node:fs/promises';
import {randomUUID, createHash} from 'node:crypto';
import path from 'node:path';

const fail = text => { throw new Error(text); };
const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(value);

export async function loadExecutionState(directory) {
  const file = path.join(directory, 'execution-state.json');
  const info = await lstat(file).catch(e => { if (e.code === 'ENOENT') return null; throw e; });
  if (!info) return {receipts:Object.create(null),cooldowns:new Map(),encoded:null};
  if (!info.isFile() || info.isSymbolicLink() || info.size > 2_000_000)
    fail('ISOLATED_EXECUTION_STATE_INVALID: expected a bounded private state file');
  let saved;
  try { saved = JSON.parse(await readFile(file, 'utf8')); }
  catch { fail('ISOLATED_EXECUTION_STATE_INVALID: state could not be decoded'); }
  if (saved.version !== 1 || !saved.receipts || !saved.cooldowns ||
      Object.keys(saved.receipts).length > 2000 || Object.keys(saved.cooldowns).length > 256)
    fail('ISOLATED_EXECUTION_STATE_INVALID: unsupported state');
  const receipts = Object.create(null);
  for (const [id,r] of Object.entries(saved.receipts)) {
    if (!validId(id) || r.receipt_id !== id || !['started','verified','unconfirmed'].includes(r.state) ||
        !/^[a-f0-9]{64}$/.test(r.expectation_fingerprint) || !Number.isFinite(Date.parse(r.attempted_at)))
      fail('ISOLATED_EXECUTION_STATE_INVALID: invalid action receipt');
    receipts[id] = {receipt_id:id,state:r.state,origin:r.origin,
      expectation_fingerprint:r.expectation_fingerprint,attempted_at:r.attempted_at,
      completed_at:r.completed_at || null,transport_failure:r.transport_failure || null};
  }
  const cooldowns = new Map();
  for (const [origin,r] of Object.entries(saved.cooldowns)) {
    let parsed;
    try { parsed = new URL(origin); } catch {}
    if (!parsed || !['http:','https:'].includes(parsed.protocol) || parsed.origin !== origin ||
        !Number.isFinite(r.until) || r.until > 8.64e15 || ![429,503].includes(r.status) ||
        !['server_retry_after','agent_60_second_backoff'].includes(r.source))
      fail('ISOLATED_EXECUTION_STATE_INVALID: invalid cooldown');
    if (r.until > Date.now()) cooldowns.set(origin, {until:r.until,status:r.status,source:r.source});
  }
  return {receipts,cooldowns,encoded:null};
}

export async function saveExecutionState(state) {
  for (const [origin,r] of state.cooldowns) if (r.until <= Date.now()) state.cooldowns.delete(origin);
  const encoded = JSON.stringify({version:1,receipts:state.execution.receipts,cooldowns:Object.fromEntries(state.cooldowns)});
  if (encoded === state.execution.encoded) return;
  if (Buffer.byteLength(encoded) > 2_000_000 || state.cooldowns.size > 256)
    fail('ISOLATED_EXECUTION_STATE_FULL: preserve existing receipts; do not retry actions');
  const target = path.join(state.directory, 'execution-state.json');
  const temp = target + '.' + randomUUID() + '.tmp';
  try { await writeFile(temp, encoded, {mode:0o600,flag:'wx'}); await rename(temp,target); state.execution.encoded=encoded; }
  finally { await unlink(temp).catch(()=>{}); }
}

export function actionReceipt(state, id) {
  if (!validId(id)) fail('INVALID_RECEIPT_ID: use 1-100 letters, digits, underscores or hyphens');
  return state.execution.receipts[id] || null;
}

export function validateExpectation(expect, timeout = 10000) {
  if (!expect || !['text','url'].includes(expect.condition) || typeof expect.text !== 'string' ||
      !expect.text || expect.text.length > 2000 || !Number.isInteger(timeout) || timeout < 1 || timeout > 25000)
    fail('INVALID_EXPECTATION: provide text or URL condition, bounded text and 1-25000ms timeout');
  return createHash('sha256').update(JSON.stringify([expect.condition,expect.text])).digest('hex');
}

export async function expectationPresent(page, expect) {
  if (expect.condition === 'url') return page.url().includes(expect.text);
  for (const frame of page.frames()) {
    // Visibility matters: old hidden toast text cannot confirm a new submission.
    const matches = await frame.getByText(expect.text,{exact:false}).all().catch(()=>[]);
    for (const match of matches.slice(0,100)) if (await match.isVisible().catch(()=>false)) return true;
  }
  return false;
}

export async function clickAndVerify(state, page, input, clickOnce) {
  const fingerprint = validateExpectation(input.expect,input.timeout_ms);
  const previous = actionReceipt(state,input.receipt_id);
  if (previous) {
    if (previous.expectation_fingerprint !== fingerprint) fail('ISOLATED_RECEIPT_CONFLICT: this ID belongs to a different expected outcome');
    return {already_recorded:true,action_attempted:false,receipt:previous,verification_current:false,
      next:'Historical receipt only. Inspect current state; this operation did not click again.'};
  }
  if (Object.keys(state.execution.receipts).length >= 2000) fail('ISOLATED_EXECUTION_STATE_FULL: preserve the receipt ledger before more actions');
  if (await expectationPresent(page,input.expect)) fail('ISOLATED_EXPECTATION_ALREADY_PRESENT: choose an outcome that changes after this action; nothing was clicked');
  // Resolve and validate the observed target before reserving the action.
  const action = await clickOnce();
  const receipt = {receipt_id:input.receipt_id,state:'started',origin:new URL(page.url()).origin,
    expectation_fingerprint:fingerprint,attempted_at:new Date().toISOString(),completed_at:null};
  state.execution.receipts[input.receipt_id] = receipt;
  await saveExecutionState(state); // Must reach disk before sending any input.
  let matched = false;
  try {
    await action();
    const until = Date.now() + (input.timeout_ms ?? 10000);
    do {
      matched = await expectationPresent(page,input.expect);
      if (matched || state.dialog) break;
      await page.waitForTimeout(Math.min(100,Math.max(1,until-Date.now())));
    } while (Date.now() < until);
  } catch { /* The click outcome may be unknown. Never automatically retry. */ }
  receipt.state = matched ? 'verified' : 'unconfirmed';
  receipt.completed_at = new Date().toISOString();
  // A dropped connection can make the engine itself resend this request; say so on the record.
  receipt.transport_failure = state.navigation?.get(page)?.failure || null;
  await saveExecutionState(state);
  return {already_recorded:false,action_attempted:true,receipt,verification_current:matched,
    next:matched ? 'The specified visible outcome appeared. Inspect a fresh snapshot for the final destination and identity.'
      : 'Outcome unconfirmed. Inspect current state and this receipt; do not repeat the submission.'};
}
