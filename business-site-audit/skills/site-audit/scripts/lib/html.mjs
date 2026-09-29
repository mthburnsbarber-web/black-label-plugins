// html.mjs — tolerant, dependency-free extraction of the head facts an audit needs.
// This reads served HTML the way a non-JavaScript crawler does; it does not render.

const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&apos;": "'", "&nbsp;": " " };

export function decodeEntities(text) {
  return String(text ?? "")
    .replace(/&(amp|lt|gt|quot|apos|nbsp|#39);/g, (m) => ENTITIES[m] ?? m)
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)));
}

function attrs(tag) {
  const out = {};
  const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
  const inner = tag.replace(/^<\s*[a-zA-Z0-9-]+/, "").replace(/\/?>$/, "");
  let m;
  while ((m = re.exec(inner))) out[m[1].toLowerCase()] = decodeEntities(m[2] ?? m[3] ?? m[4] ?? "");
  return out;
}

/** Everything in <head> (or the first 200 KB) with scripts other than JSON-LD removed. */
function headOf(html) {
  const lower = html.toLowerCase();
  const end = lower.indexOf("</head>");
  return end === -1 ? html.slice(0, 200_000) : html.slice(0, end);
}

/** Every `application/ld+json` block in the document: `{ ok, value }` or `{ ok: false, error, sample }`. */
export function jsonLdBlocks(html) {
  const blocks = [];
  for (const m of String(html ?? "").matchAll(/<script\b[^>]*type\s*=\s*["']?application\/ld\+json["']?[^>]*>([\s\S]*?)<\/script>/gi)) {
    const raw = m[1].trim();
    try {
      blocks.push({ ok: true, value: JSON.parse(raw) });
    } catch (error) {
      blocks.push({ ok: false, error: String(error?.message || error).slice(0, 120), sample: raw.slice(0, 80) });
    }
  }
  return blocks;
}

/** Every attribute of the first tag matching `re`, or null. */
export function tagAttrs(html, re) {
  const m = String(html ?? "").match(re);
  return m ? attrs(m[0]) : null;
}

/** `<a>` elements anywhere in the document: `{ href, text, rel }`. */
export function anchors(html) {
  return [...String(html ?? "").matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/gi)].map((m) => {
    const a = attrs(`<a ${m[1]}>`);
    return { href: a.href ?? null, rel: (a.rel ?? "").toLowerCase(), text: stripTags(m[2]) };
  }).filter((a) => a.href);
}

/** Visible text of an HTML fragment: no scripts, no tags, collapsed whitespace. */
export function stripTags(fragment) {
  return decodeEntities(
    String(fragment ?? "")
      .replace(/<(script|style|template)\b[^>]*>[\s\S]*?<\/\1>/gi, " ")
      .replace(/<[^>]+>/g, " "),
  ).replace(/\s+/g, " ").trim();
}

export function extractPage(html) {
  const source = String(html ?? "");
  const head = headOf(source);
  const metas = [...head.matchAll(/<meta\b[^>]*>/gi)].map((m) => attrs(m[0]));
  const links = [...head.matchAll(/<link\b[^>]*>/gi)].map((m) => attrs(m[0]));
  const meta = (key) => {
    const hit = metas.find((a) => (a.name || a.property || "").toLowerCase() === key);
    return hit ? (hit.content ?? "").trim() : null;
  };
  const titleMatch = head.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i);
  const htmlTag = source.match(/<html\b[^>]*>/i);
  const canonical = links.find((l) => (l.rel || "").toLowerCase().split(/\s+/).includes("canonical"));
  const h1Count = (source.match(/<h1\b/gi) || []).length;

  const jsonLd = jsonLdBlocks(source);
  const types = new Set();
  const collect = (node) => {
    if (Array.isArray(node)) return node.forEach(collect);
    if (!node || typeof node !== "object") return;
    const t = node["@type"];
    (Array.isArray(t) ? t : t ? [t] : []).forEach((x) => types.add(String(x)));
    if (node["@graph"]) collect(node["@graph"]);
  };
  jsonLd.filter((b) => b.ok).forEach((b) => collect(b.value));

  return {
    meta,
    metas,
    links,
    title: titleMatch ? decodeEntities(titleMatch[1]).replace(/\s+/g, " ").trim() : null,
    description: meta("description"),
    robots: meta("robots"),
    canonical: canonical?.href ?? null,
    lang: htmlTag ? attrs(htmlTag[0]).lang ?? null : null,
    viewport: meta("viewport"),
    og: { title: meta("og:title"), description: meta("og:description"), image: meta("og:image"), type: meta("og:type") },
    twitterCard: meta("twitter:card"),
    h1Count,
    alternates: links.filter((l) => (l.rel || "").toLowerCase() === "alternate").map((l) => ({ type: l.type ?? null, href: l.href ?? null, hreflang: l.hreflang ?? null })),
    jsonLd: { blocks: jsonLd.length, invalid: jsonLd.filter((b) => !b.ok).map(({ error, sample }) => ({ error, sample })), types: [...types].sort() },
  };
}

/** Parse an HTTP Link header into [{ href, rel }]. */
export function parseLinkHeader(value) {
  if (!value) return [];
  return String(value)
    .split(/,(?=\s*<)/)
    .map((part) => {
      const href = part.match(/<([^>]*)>/)?.[1] ?? null;
      const rel = part.match(/;\s*rel\s*=\s*"?([^";]+)"?/i)?.[1] ?? null;
      return href ? { href, rel } : null;
    })
    .filter(Boolean);
}
