// safe-fetch.mjs — the only way the audit touches an owner-supplied URL.
//
// The plugin inspects *public* websites, so every request is limited to what a
// public crawler could do: http/https on the default ports, public hostnames only,
// bounded redirects (each hop re-validated), bounded time, bounded bytes, and an honest
// User-Agent. Nothing here follows a URL into a private network.

/**
 * The honest User-Agent. `infoUrl` is the public page that explains this fetcher (the
 * publisher's public documentation page. It is omitted when no page is supplied.
 */
export function userAgentFor(infoUrl) {
  return `BusinessSiteAudit/1.0 (${infoUrl ? `+${infoUrl}; ` : ""}on-demand public-page audit)`;
}

const PRIVATE_HOST_SUFFIXES = [
  ".local", ".localhost", ".internal", ".intranet", ".lan", ".home", ".corp", ".private", ".test", ".invalid", ".example",
];

function ipv4Parts(host) {
  const m = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  return parts.every((n) => n >= 0 && n <= 255) ? parts : null;
}

function isPrivateIpv4([a, b]) {
  return (
    a === 0 || a === 10 || a === 127 ||
    (a === 100 && b >= 64 && b <= 127) || // carrier-grade NAT
    (a === 169 && b === 254) ||           // link-local / cloud metadata
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 192 && b === 0) ||
    (a === 198 && (b === 18 || b === 19)) ||
    a >= 224                              // multicast + reserved
  );
}

/**
 * Validate a customer-supplied URL. Returns `{ ok: true, url }` with a normalized URL
 * or `{ ok: false, reason }`. Hostnames are checked lexically; the local
 * network adapter resolves and pins a public IP before opening each connection.
 */
export function checkPublicUrl(input) {
  let url;
  try {
    url = new URL(String(input ?? "").trim());
  } catch {
    return { ok: false, reason: "not a valid absolute URL" };
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return { ok: false, reason: "only http and https URLs are supported" };
  if (url.username || url.password) return { ok: false, reason: "URLs with credentials are not accepted" };
  if (url.port && !((url.protocol === "https:" && url.port === "443") || (url.protocol === "http:" && url.port === "80"))) {
    return { ok: false, reason: "only the default ports (80, 443) are supported" };
  }
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (!host) return { ok: false, reason: "missing hostname" };
  if (host.startsWith("[") || host.includes(":")) return { ok: false, reason: "IP-literal hosts are not accepted; use the site's public hostname" };
  const v4 = ipv4Parts(host);
  if (v4) return { ok: false, reason: isPrivateIpv4(v4) ? "private or reserved address" : "IP-literal hosts are not accepted; use the site's public hostname" };
  if (/^\d+$/.test(host) || /^0x[0-9a-f]+$/i.test(host)) return { ok: false, reason: "numeric hosts are not accepted" };
  if (!host.includes(".")) return { ok: false, reason: "hostname must be a public domain name" };
  if (host === "localhost" || PRIVATE_HOST_SUFFIXES.some((s) => host.endsWith(s))) return { ok: false, reason: "private or reserved hostname" };
  if (!/^[a-z0-9.-]+$/.test(host) || host.split(".").some((label) => !label || label.length > 63 || label.startsWith("-") || label.endsWith("-"))) {
    return { ok: false, reason: "hostname is not a valid public DNS name" };
  }
  url.hostname = host;
  url.hash = "";
  return { ok: true, url };
}

/** The site root (origin + "/") for a validated URL. */
export function siteRoot(url) {
  return new URL("/", url).toString();
}

/**
 * Create a bounded fetcher. `fetchImpl` is injectable for tests. Every call returns a
 * plain record for network failures so an audit can distinguish unknown checks
 * from observed HTTP responses.
 */
export function createFetcher({ fetchImpl = fetch, maxFetches = 16, timeoutMs = 8000, maxBytes = 1_500_000, maxRedirects = 5, userAgent = userAgentFor() } = {}) {
  let used = 0;
  const log = [];

  async function readLimited(response) {
    if (!response.body) return { text: "", truncated: false, bytes: 0 };
    const reader = response.body.getReader();
    const chunks = [];
    let bytes = 0;
    let truncated = false;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > maxBytes) {
        chunks.push(value.subarray(0, value.byteLength - (bytes - maxBytes)));
        truncated = true;
        try { await reader.cancel(); } catch {}
        break;
      }
      chunks.push(value);
    }
    const all = new Uint8Array(Math.min(bytes, maxBytes));
    let offset = 0;
    for (const c of chunks) { all.set(c, offset); offset += c.byteLength; }
    return { text: new TextDecoder("utf-8", { fatal: false }).decode(all), truncated, bytes: Math.min(bytes, maxBytes) };
  }

  /**
   * @param {string} target
   * @param {{ method?: "GET"|"HEAD", followRedirects?: boolean, accept?: string }} [opts]
   */
  async function get(target, { method = "GET", followRedirects = true, accept = "*/*" } = {}) {
    const hops = [];
    let current = target;
    for (let hop = 0; hop <= maxRedirects; hop++) {
      const checked = checkPublicUrl(current);
      if (!checked.ok) return { ok: false, url: current, hops, error: `blocked: ${checked.reason}` };
      if (used >= maxFetches) return { ok: false, url: current, hops, error: "fetch budget exhausted" };
      used++;
      const started = Date.now();
      let response;
      try {
        response = await fetchImpl(checked.url.toString(), {
          method,
          redirect: "manual",
          headers: { "user-agent": userAgent, accept },
          signal: AbortSignal.timeout(timeoutMs),
        });
      } catch (error) {
        const reason = error?.name === "TimeoutError" || error?.name === "AbortError" ? `timed out after ${timeoutMs} ms` : `network error: ${String(error?.message || error).slice(0, 160)}`;
        log.push({ url: checked.url.toString(), method, error: reason });
        return { ok: false, url: checked.url.toString(), hops, error: reason };
      }
      const ms = Date.now() - started;
      const status = response.status;
      const location = response.headers.get("location");
      log.push({ url: checked.url.toString(), method, status, ms });
      if (followRedirects && status >= 300 && status < 400 && location) {
        hops.push({ url: checked.url.toString(), status, location });
        try { await response.body?.cancel(); } catch {}
        current = new URL(location, checked.url).toString();
        continue;
      }
      let body;
      try {
        body = method === "HEAD" ? { text: "", truncated: false, bytes: 0 } : await readLimited(response);
      } catch (error) {
        const reason = `response stream failed: ${String(error?.message || error).slice(0, 160)}`;
        log.push({ url: checked.url.toString(), method, error: reason });
        return { ok: false, url: checked.url.toString(), hops, error: reason };
      }
      return {
        ok: true,
        url: checked.url.toString(),
        status,
        ms,
        hops,
        headers: Object.fromEntries([...response.headers].map(([k, v]) => [k.toLowerCase(), v])),
        contentType: (response.headers.get("content-type") || "").toLowerCase(),
        ...body,
      };
    }
    return { ok: false, url: current, hops, error: `more than ${maxRedirects} redirects` };
  }

  return { get, stats: () => ({ fetches: used, maxFetches, timeoutMs, maxBytes }), log };
}
