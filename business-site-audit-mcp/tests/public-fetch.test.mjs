import test from 'node:test';
import assert from 'node:assert/strict';
import { createPublicFetch } from '../src/public-fetch.mjs';

const dnsError = (code) => Object.assign(new Error(code), { code });

test('public target is checked before the outbound request', async () => {
  const calls = [];
  const publicFetch = createPublicFetch({
    lookup4: async (host) => { calls.push(`dns:${host}`); return ['93.184.215.14']; },
    lookup6: async () => { throw dnsError('ENODATA'); },
    fetchImpl: async (url, options) => { calls.push(`fetch:${url}`); assert.equal(options.redirect, 'manual'); return new Response('ok'); },
  });
  await publicFetch('https://example.com/', { method: 'GET' });
  assert.deepEqual(calls, ['dns:example.com', 'fetch:https://example.com/']);
});

test('private target and DNS answers never reach fetch', async () => {
  let fetched = 0;
  const publicFetch = createPublicFetch({
    lookup4: async () => ['93.184.215.14', '127.0.0.1'],
    lookup6: async () => { throw dnsError('ENODATA'); },
    fetchImpl: async () => { fetched++; return new Response('bad'); },
  });
  await assert.rejects(() => publicFetch('http://127.0.0.1/'), /blocked/);
  await assert.rejects(() => publicFetch('https://example.com/'), /private, reserved or unknown/);
  assert.equal(fetched, 0);
});

test('resolver failure is not treated as an absent address family', async () => {
  let fetched = 0;
  const publicFetch = createPublicFetch({
    lookup4: async () => ['93.184.215.14'],
    lookup6: async () => { throw dnsError('ESERVFAIL'); },
    fetchImpl: async () => { fetched++; return new Response('bad'); },
  });
  await assert.rejects(() => publicFetch('https://example.com/'), /public DNS check failed/);
  assert.equal(fetched, 0);
});
