import { lookup } from 'node:dns/promises';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { BlockList } from 'node:net';
import { Readable } from 'node:stream';

// Resolve once and pin the selected address for the actual connection. A lexical
// hostname check alone would still allow a public-looking name to resolve locally.
const blocked = new BlockList();
for (const [network, bits] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10],
  ['127.0.0.0', 8], ['169.254.0.0', 16], ['172.16.0.0', 12],
  ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.168.0.0', 16],
  ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24],
  ['224.0.0.0', 4], ['240.0.0.0', 4],
]) blocked.addSubnet(network, bits, 'ipv4');
for (const [network, bits] of [
  ['2001::', 32], ['2001:10::', 28], ['2001:20::', 28],
  ['2001:db8::', 32], ['2002::', 16],
]) blocked.addSubnet(network, bits, 'ipv6');
const globalV6 = new BlockList();
globalV6.addSubnet('2000::', 3, 'ipv6');

export function isPublicAddress(address, family) {
  if (family === 4) return !blocked.check(address, 'ipv4');
  if (family === 6) return globalV6.check(address, 'ipv6') && !blocked.check(address, 'ipv6');
  return false;
}

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
