// Fresh stdio adapter for hosts retaining an older loaded MCP connection.
// All browser actions still use this plugin's public MCP entry point.
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';

export async function connectBrowser({session, profile, sessionRef} = {}) {
  if (session && !/^[a-zA-Z0-9_-]{1,80}$/.test(session)) throw new Error('INVALID_SESSION');
  // A digest from status is a reference. Hashing it again would open a second, blank store.
  if (session && /^[a-f0-9]{24}$/.test(session)) throw new Error('SESSION_REFERENCE_PASSED_AS_NAME: reopen it with connectBrowser({sessionRef:"session:' + session + '"})');
  if (sessionRef !== undefined && !/^(acct_|session:|profile:)[a-f0-9]{24}$/.test(sessionRef)) throw new Error('INVALID_SESSION_REFERENCE');
  if (profile !== undefined && !/^[a-zA-Z0-9_-]{1,80}$/.test(profile)) throw new Error('INVALID_PROFILE');
  const server = fileURLToPath(new URL('./server.py', import.meta.url));
  // Default spawn inheritance also works in hosts without a process global.
  const variables = [...(session ? ['BL_BROWSER_SESSION=' + session] : []), ...(profile !== undefined ? ['BL_BROWSER_PROFILE=' + profile] : []), ...(sessionRef ? ['BL_BROWSER_SESSION_REF=' + sessionRef] : [])];
  const command = variables.length ? '/usr/bin/env' : '/usr/bin/python3';
  const args = variables.length ? [...variables, '/usr/bin/python3', server] : [server];
  const child = spawn(command, args, {stdio: ['pipe', 'pipe', 'ignore']});
  let sequence = 0;
  let closed = false;
  let needsSnapshot = false;
  const pending = new Map();
  const lines = createInterface({input: child.stdout});
  const failPending = () => {
    closed = true;
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error('ISOLATED_CONNECTION_CLOSED: inspect a fresh connection before repeating an action'));
    }
    pending.clear();
  };
  child.once('exit', failPending);
  child.once('error', failPending);
  child.stdin.on('error', failPending);
  lines.on('line', line => {
    let response;
    try { response = JSON.parse(line); } catch { needsSnapshot = true; return; }
    const request = pending.get(response.id);
    if (!request) return; // Discard a late response by ID, never reuse it.
    pending.delete(response.id);
    clearTimeout(request.timer);
    if (response.error) request.reject(new Error(response.error.message));
    else request.resolve(response.result);
  });
  function rpc(method, params) {
    if (closed) return Promise.reject(new Error('ISOLATED_CONNECTION_CLOSED'));
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        needsSnapshot = true;
        reject(new Error('ISOLATED_RESULT_UNKNOWN: inspect a fresh snapshot before another action'));
      }, 50000);
      pending.set(id, {resolve, reject, timer});
      child.stdin.write(JSON.stringify({jsonrpc: '2.0', id, method, params}) + '\n');
    });
  }
  await rpc('initialize', {protocolVersion: '2025-06-18', capabilities: {}, clientInfo: {name: 'black-label-hidden-browser', version: '1.1.0'}});
  return {
    async call(name, args = {}) {
      const command = name.replace(/^browser_/, '');
      const readOnly = ['snapshot', 'status', 'screenshot', 'auth', 'receipt', 'find', 'capture', 'settle'].includes(command) || ['tabs','checkpoint'].includes(command) && (!args.action || args.action === 'list') || command === 'session' && ['current','list','create'].includes(args.action);
      if (needsSnapshot && !readOnly)
        throw new Error('ISOLATED_RECONCILIATION_REQUIRED: inspect a fresh snapshot first');
      const result = await rpc('tools/call', {name: 'browser_' + command, arguments: args});
      if (result.isError) {
        const message = result.content[0].text;
        if (/ISOLATED_(ACTION_|FORM_PARTIAL|BROWSER_(CLOSED|TIMEOUT)|RESULT_UNKNOWN|EXECUTION_STATE_WRITE_FAILED)/.test(message)) needsSnapshot = true;
        throw new Error(message);
      }
      if (command === 'snapshot') needsSnapshot = false;
      const value = result.content[0].type === 'image' ? result.content[0] : JSON.parse(result.content[0].text);
      if (command === 'click_verify' && ['started','unconfirmed'].includes(value.receipt?.state)) needsSnapshot = true;
      return value;
    },
    async close() {
      if (closed) return;
      const exited = new Promise(resolve => child.once('exit', resolve));
      child.stdin.end(); // Normal EOF shutdown; never signal host infrastructure.
      let timer;
      try {
        await Promise.race([exited, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error('ISOLATED_SHUTDOWN_PENDING: preserve the connection until it exits')), 10000);
        })]);
      } finally { clearTimeout(timer); }
    },
  };
}
