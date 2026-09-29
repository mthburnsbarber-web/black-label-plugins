import { resolve4, resolve6 } from 'node:dns/promises';
import { checkPublicUrl } from '../lib/safe-fetch.mjs';
import { isPublicAddress } from '../lib/ip-policy.mjs';

const ABSENT_DNS_CODES = new Set(['ENODATA', 'ENOTFOUND']);

/** Resolve every available address before the Worker makes a subrequest. */
export function createPublicFetch({ lookup4 = resolve4, lookup6 = resolve6, fetchImpl = fetch } = {}) {
  return async function publicFetch(input, options = {}) {
    const checked = checkPublicUrl(input);
    if (!checked.ok) throw new Error(`blocked: ${checked.reason}`);
    const host = checked.url.hostname;
    const results = await Promise.allSettled([lookup4(host), lookup6(host)]);
    const addresses = [];
    for (let index = 0; index < results.length; index++) {
      const result = results[index];
      if (result.status === 'rejected') {
        if (!ABSENT_DNS_CODES.has(result.reason?.code)) throw new Error('public DNS check failed');
        continue;
      }
      if (!Array.isArray(result.value)) throw new Error('public DNS check returned no address list');
      for (const address of result.value) addresses.push({ address, family: index === 0 ? 4 : 6 });
    }
    if (!addresses.length || addresses.some(({ address, family }) => !isPublicAddress(address, family))) {
      throw new Error('hostname resolves to a private, reserved or unknown address');
    }
    // Workers fetch enforces its own egress rules. Redirects are handled and
    // rechecked by createFetcher, which always requests redirect: manual.
    return fetchImpl(checked.url.toString(), { ...options, redirect: 'manual' });
  };
}
