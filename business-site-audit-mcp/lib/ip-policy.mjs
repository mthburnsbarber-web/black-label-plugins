import { BlockList } from 'node:net';

// A conservative public-address policy shared by the local and hosted fetchers.
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
