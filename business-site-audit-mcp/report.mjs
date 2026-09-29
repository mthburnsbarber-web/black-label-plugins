import { runAudit } from './lib/audit.mjs';
import { pinnedPublicFetch } from './lib/network.mjs';

export function auditWebsite(url, { fetchImpl = pinnedPublicFetch, clock } = {}) {
  return runAudit(url, { fetchImpl, clock });
}
