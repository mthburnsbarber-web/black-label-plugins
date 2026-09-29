import { lookup } from 'node:dns/promises';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { Readable } from 'node:stream';
import { isPublicAddress } from './ip-policy.mjs';

// Resolve once and pin the selected address for the actual connection. A lexical
// hostname check alone would still allow a public-looking name to resolve locally.
export { isPublicAddress } from './ip-policy.mjs';

export async function pinnedPublicFetch(input, { method = 'GET', headers = {}, signal } = {}) {
  const url = new URL(input);
  const addresses = await lookup(url.hostname, { all: true, verbatim: true });
  if (!addresses.length || addresses.some(({ address, family }) => !isPublicAddress(address, family))) {
    throw new Error('hostname resolves to a private, reserved or unknown address');
  }
  const selected = addresses.find((row) => row.family === 4) ?? addresses[0];
  const send = url.protocol === 'https:' ? httpsRequest : httpRequest;
  return await new Promise((resolve, reject) => {
    const req = send(url, {
      method,
      headers,
      agent: false,
      lookup: (_hostname, options, callback) => options.all
        ? callback(null, [{ address: selected.address, family: selected.family }])
        : callback(null, selected.address, selected.family),
    }, (res) => {
      const responseHeaders = new Headers();
      for (const [key, value] of Object.entries(res.headers)) {
        if (Array.isArray(value)) value.forEach((part) => responseHeaders.append(key, part));
        else if (value != null) responseHeaders.set(key, String(value));
      }
      resolve({ status: res.statusCode, headers: responseHeaders,
        body: method === 'HEAD' ? null : Readable.toWeb(res) });
    });
    req.once('error', reject);
    const abort = () => req.destroy(signal.reason instanceof Error ? signal.reason : new Error('request aborted'));
    if (signal?.aborted) abort();
    else signal?.addEventListener('abort', abort, { once: true });
    req.end();
  });
}
