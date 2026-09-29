// robots.mjs — a small RFC 9309 robots.txt evaluator.
//
// Group selection: the group whose user-agent line matches the crawler's product token
// (case-insensitive) wins; otherwise the "*" group applies. Rule matching: the longest
// matching path pattern wins; on a tie, Allow wins. `*` and `$` are supported.

/** Known crawlers, grouped by what blocking them costs the site. */
export const CRAWLERS = [
  // Classic search indexes — blocking these removes the site from search and from
  // most AI answers that cite search results.
  { token: "Googlebot", kind: "search" },
  { token: "Bingbot", kind: "search" },
  { token: "Applebot", kind: "search" },
  // AI search and user-triggered fetchers — these read pages to answer a person's
  // question right now, usually with a citation back to the site.
  { token: "OAI-SearchBot", kind: "ai-answer" },
  { token: "ChatGPT-User", kind: "ai-answer" },
  { token: "Claude-SearchBot", kind: "ai-answer" },
  { token: "Claude-User", kind: "ai-answer" },
  { token: "PerplexityBot", kind: "ai-answer" },
  { token: "Perplexity-User", kind: "ai-answer" },
  { token: "DuckAssistBot", kind: "ai-answer" },
  { token: "MistralAI-User", kind: "ai-answer" },
  // Model-training crawlers — blocking these is a legitimate policy choice, not a defect.
  { token: "GPTBot", kind: "ai-training" },
  { token: "ClaudeBot", kind: "ai-training" },
  { token: "Google-Extended", kind: "ai-training" },
  { token: "Applebot-Extended", kind: "ai-training" },
  { token: "CCBot", kind: "ai-training" },
  { token: "Bytespider", kind: "ai-training" },
  { token: "meta-externalagent", kind: "ai-training" },
  { token: "cohere-ai", kind: "ai-training" },
];

/** Parse robots.txt text into `{ groups: [{ agents, rules }], sitemaps, contentSignals }`. */
export function parseRobots(text) {
  const groups = [];
  const sitemaps = [];
  const contentSignals = [];
  let current = null;
  let lastWasAgent = false;
  for (const rawLine of String(text ?? "").split(/\r?\n/)) {
    const line = rawLine.replace(/#.*$/, "").trim();
    if (!line) continue;
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const field = line.slice(0, idx).trim().toLowerCase();
    const value = line.slice(idx + 1).trim();
    if (field === "user-agent") {
      if (!current || !lastWasAgent) {
        current = { agents: [], rules: [] };
        groups.push(current);
      }
      current.agents.push(value.toLowerCase());
      lastWasAgent = true;
      continue;
    }
    lastWasAgent = false;
    if (field === "sitemap") {
      if (value) sitemaps.push(value);
      continue;
    }
    if (field === "content-signal") {
      if (value) contentSignals.push(value);
      continue;
    }
    if ((field === "allow" || field === "disallow") && current) {
      current.rules.push({ type: field, path: value });
    }
  }
  return { groups, sitemaps, contentSignals };
}

function patternToRegex(path) {
  const anchored = path.endsWith("$");
  const body = (anchored ? path.slice(0, -1) : path)
    .split("*")
    .map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp("^" + body + (anchored ? "$" : ""));
}

function specificity(path) {
  return path.replace(/\*/g, "").replace(/\$$/, "").length;
}

/**
 * The rules that apply to a crawler token, or null when none apply.
 *
 * A group applies when its user-agent equals the crawler's product token or is a prefix of
 * it ("googlebot" covers "Googlebot-News"), and the most specific (longest) match wins. A
 * group for "Applebot-Extended" never applies to "Applebot": the crawler token would have to
 * start with the group's token, not the other way round.
 */
export function groupFor(robots, token) {
  const t = token.toLowerCase();
  let best = -1;
  let rules = [];
  for (const g of robots.groups) {
    for (const a of g.agents) {
      if (a === "*" || !(t === a || t.startsWith(a))) continue;
      if (a.length > best) {
        best = a.length;
        rules = [];
      }
      if (a.length === best) rules.push(...g.rules);
    }
  }
  if (best >= 0) return { rules, matchedBy: "named" };
  const star = robots.groups.filter((g) => g.agents.includes("*"));
  if (star.length) return { rules: star.flatMap((g) => g.rules), matchedBy: "*" };
  return null;
}

/** Whether `token` may fetch `path` ("/" by default). Returns "allowed" | "blocked". */
export function evaluate(robots, token, path = "/") {
  const group = groupFor(robots, token);
  if (!group) return { verdict: "allowed", matchedBy: "no-rules" };
  let best = null;
  for (const rule of group.rules) {
    if (rule.type === "disallow" && rule.path === "") continue; // empty Disallow allows everything
    if (!patternToRegex(rule.path).test(path)) continue;
    const s = specificity(rule.path);
    if (!best || s > best.s || (s === best.s && rule.type === "allow" && best.rule.type !== "allow")) best = { rule, s };
  }
  if (!best) return { verdict: "allowed", matchedBy: group.matchedBy };
  return { verdict: best.rule.type === "allow" ? "allowed" : "blocked", matchedBy: group.matchedBy, rule: `${best.rule.type}: ${best.rule.path}` };
}
