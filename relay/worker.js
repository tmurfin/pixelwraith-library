// The PixelWraith Grid submission relay. The app posts a tile or projector submission here and this worker opens
// the GitHub issue with a token the app never holds, so users need no GitHub account. See README.md to deploy.
const REPOSITORY = "tmurfin/pixelwraith-library";
const MAX_BYTES = 32 * 1024;
const KINDS = new Set(["tile", "projector"]);

const APP_COMMENT = "Updated from the app.";

// POST /submit {kind, title, body} → 201 {number, url, key}; with issue {number, key} → 200 {number, url, key}
// after updating that issue, or 403 {error} when the key is not this worker's; 400 {error} for a bad request or
// GitHub rejecting the item; 502 {error} when GitHub is unavailable. POST /status {issues: [{number, key}]} →
// 200 {issues: [{number, state, needsChanges, comment}]} (see `status`). 405 / 404 otherwise. `githubFetch` is
// swapped for a fake by the test.
export async function handle(request, env, githubFetch = fetch) {
  const url = new URL(request.url);
  if (url.pathname !== "/submit" && url.pathname !== "/status") return json(404, { error: "not found" });
  if (request.method !== "POST") return json(405, { error: "POST only" });
  // Sixty posts a minute per address (the RATE_LIMITER binding in wrangler.toml), checked before the body is read
  // so a flood costs nothing; over that, 429, which the app treats as "try again later"
  // /status has its own, tighter limiter when one is bound: a check costs up to two GitHub calls per issue
  const limiter = url.pathname === "/status" ? (env.STATUS_LIMITER || env.RATE_LIMITER) : env.RATE_LIMITER;
  if (limiter) {
    const key = request.headers.get("cf-connecting-ip") || "unknown";
    const { success } = await limiter.limit({ key });
    if (!success) return json(429, { error: "too many submissions from this address; try again in a minute" });
  }
  if (Number(request.headers.get("content-length") || 0) > MAX_BYTES) return json(400, { error: "too large" });
  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BYTES) return json(400, { error: "too large" });
  let submission;
  try { submission = JSON.parse(text); } catch { return json(400, { error: "not JSON" }); }
  if (url.pathname === "/status") return status(submission, env, githubFetch);
  const problem = validate(submission);
  if (problem) return json(400, { error: problem });
  const headers = githubHeaders(env);
  const issues = `https://api.github.com/repos/${REPOSITORY}/issues`;

  if (submission.issue) {
    // An update: only the client that made the submission holds its key (the HMAC of the number under the
    // signing secret), so a wrong key, or no secret, is refused before GitHub is called
    const { number, key } = submission.issue;
    if (!env.SIGNING_SECRET || !(await matches(env.SIGNING_SECRET, number, key))) return json(403, { error: "not this app's submission" });
    const answer = await githubFetch(`${issues}/${number}`, {
      method: "PATCH", headers,
      body: JSON.stringify({ title: submission.title, body: submission.body, state: "open", labels: ["submission", submission.kind] }),
    });
    // An issue that no longer exists is a dead end for its key: 403, so the app forgets it and opens a new one
    if (answer.status === 404 || answer.status === 410) return json(403, { error: "that issue is gone" });
    if (answer.status !== 200) return githubFailure(answer);
    const issue = await answer.json();
    // The comment notifies the maintainer even when the issue was already open; a failed comment is not fatal
    try { await githubFetch(`${issues}/${number}/comments`, { method: "POST", headers, body: JSON.stringify({ body: APP_COMMENT }) }); } catch {}
    return json(200, { number: issue.number, url: issue.html_url, key });
  }

  const answer = await githubFetch(issues, {
    method: "POST", headers,
    body: JSON.stringify({ title: submission.title, body: submission.body, labels: ["submission", submission.kind] }),
  });
  if (answer.status !== 201) return githubFailure(answer);
  const issue = await answer.json();
  const key = env.SIGNING_SECRET ? await sign(env.SIGNING_SECRET, issue.number) : undefined;
  return json(201, { number: issue.number, url: issue.html_url, key });
}

// POST /status {issues: [{number, key}]} → 200 {issues: [{number, state, needsChanges, comment}]}: for every
// reference whose key is this worker's, GitHub's state ("gone" for 404/410), whether the needs-changes label is
// on, and the latest comment by the repository's owner, a member or a collaborator that is not the app's own
// (the repository is public, so anyone may comment; only the maintainers' words reach the app). Wrong keys and
// GitHub failures leave the issue out
const MAINTAINER_ROLES = new Set(["OWNER", "MEMBER", "COLLABORATOR"]);
export async function status(body, env, githubFetch = fetch) {
  const list = body && body.issues;
  if (!Array.isArray(list) || list.length < 1 || list.length > 25
      || !list.every(i => i && typeof i === "object" && Number.isInteger(i.number) && i.number >= 1 && typeof i.key === "string")) {
    return json(400, { error: "issues must be a list of 1 to 25 number and key pairs" });
  }
  const out = [];
  if (!env.SIGNING_SECRET) return json(200, { issues: out });
  const headers = githubHeaders(env);
  const issues = `https://api.github.com/repos/${REPOSITORY}/issues`;
  for (const { number, key } of list) {
    if (!(await matches(env.SIGNING_SECRET, number, key))) continue;
    const answer = await githubFetch(`${issues}/${number}`, { headers });
    if (answer.status === 404 || answer.status === 410) { out.push({ number, state: "gone", needsChanges: false, comment: null }); continue; }
    if (answer.status !== 200) continue;
    const issue = await answer.json();
    const needsChanges = (issue.labels || []).some(label => (typeof label === "string" ? label : label.name) === "needs-changes");
    let comment = null;
    if (issue.comments > 0) {
      const comments = await githubFetch(`${issues}/${number}/comments?per_page=100`, { headers });
      if (comments.status === 200) {
        const all = await comments.json();
        for (let i = all.length - 1; i >= 0; i--) {
          if (MAINTAINER_ROLES.has(all[i].author_association) && all[i].body !== APP_COMMENT) { comment = all[i].body; break; }
        }
      }
    }
    out.push({ number, state: issue.state, needsChanges, comment });
  }
  return json(200, { issues: out });
}

function githubHeaders(env) {
  return {
    "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "pixelwraith-library-submit",
    "Content-Type": "application/json",
  };
}

// GitHub rejecting this item (422, 404, 410…) is final for it: 400, so the app drops it and shows why. GitHub
// unavailable, the token lapsed or rate limited: 502, so the app keeps it and tries later
async function githubFailure(answer) {
  let message = "";
  try { message = (await answer.json()).message || ""; } catch {}
  if (answer.status >= 400 && answer.status < 500 && ![401, 403, 429].includes(answer.status)) {
    return json(400, { error: `GitHub refused it${message ? ": " + message : ""}` });
  }
  return json(502, { error: `GitHub answered ${answer.status}${message ? ": " + message : ""}` });
}

// The hex HMAC-SHA256 of the issue number under the signing secret: the key the app must present to update it
export async function sign(secret, number) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(String(number)));
  return [...new Uint8Array(signature)].map(b => b.toString(16).padStart(2, "0")).join("");
}

// Constant-time comparison of the presented key with the right one
async function matches(secret, number, presented) {
  const expected = await sign(secret, number);
  if (typeof presented !== "string" || presented.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ presented.charCodeAt(i);
  return diff === 0;
}

// null when the submission has the shape the app sends, else what is wrong with it
export function validate(s) {
  if (!s || typeof s !== "object") return "not an object";
  if (!KINDS.has(s.kind)) return "kind must be tile or projector";
  if (typeof s.title !== "string" || s.title.length < 1 || s.title.length > 200) return "title must be 1–200 characters";
  if (typeof s.body !== "string" || s.body.length < 1 || s.body.length > 20000) return "body must be 1–20000 characters";
  if (!/```json\s*\{[\s\S]*?\}\s*```/.test(s.body)) return "body has no json block";
  if (s.issue !== undefined && s.issue !== null) {
    const i = s.issue;
    if (!i || typeof i !== "object" || !Number.isInteger(i.number) || i.number < 1 || typeof i.key !== "string") return "issue must have a number and a key";
  }
  return null;
}

function json(status, value) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

export default { fetch: (request, env) => handle(request, env) };
