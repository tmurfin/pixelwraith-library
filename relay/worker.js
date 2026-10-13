// The PixelWraith Grid submission relay. The app posts a tile or projector submission here and this worker opens
// the GitHub issue with a token the app never holds, so users need no GitHub account. See README.md to deploy.
const REPOSITORY = "tmurfin/pixelwraith-library";
const MAX_BYTES = 32 * 1024;
const KINDS = new Set(["tile", "projector"]);

// POST /submit {kind, title, body} → 201 {number, url}; 400 {error} for a bad request; 405 / 404 otherwise;
// 502 {error} when GitHub refuses. `githubFetch` is swapped for a fake by the test.
export async function handle(request, env, githubFetch = fetch) {
  const url = new URL(request.url);
  if (url.pathname !== "/submit") return json(404, { error: "not found" });
  if (request.method !== "POST") return json(405, { error: "POST only" });
  if (Number(request.headers.get("content-length") || 0) > MAX_BYTES) return json(400, { error: "too large" });
  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BYTES) return json(400, { error: "too large" });
  let submission;
  try { submission = JSON.parse(text); } catch { return json(400, { error: "not JSON" }); }
  const problem = validate(submission);
  if (problem) return json(400, { error: problem });
  const answer = await githubFetch(`https://api.github.com/repos/${REPOSITORY}/issues`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "pixelwraith-library-submit",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title: submission.title, body: submission.body, labels: ["submission", submission.kind] }),
  });
  if (answer.status !== 201) {
    let message = "";
    try { message = (await answer.json()).message || ""; } catch {}
    // GitHub rejecting this item (422, 404, 410…) is final for it: 400, so the app drops it and shows why.
    // GitHub unavailable, the token lapsed or rate limited: 502, so the app keeps it and tries later
    if (answer.status >= 400 && answer.status < 500 && ![401, 403, 429].includes(answer.status)) {
      return json(400, { error: `GitHub refused it${message ? ": " + message : ""}` });
    }
    return json(502, { error: `GitHub answered ${answer.status}${message ? ": " + message : ""}` });
  }
  const issue = await answer.json();
  return json(201, { number: issue.number, url: issue.html_url });
}

// null when the submission has the shape the app sends, else what is wrong with it
export function validate(s) {
  if (!s || typeof s !== "object") return "not an object";
  if (!KINDS.has(s.kind)) return "kind must be tile or projector";
  if (typeof s.title !== "string" || s.title.length < 1 || s.title.length > 200) return "title must be 1–200 characters";
  if (typeof s.body !== "string" || s.body.length < 1 || s.body.length > 20000) return "body must be 1–20000 characters";
  if (!/```json\s*\{[\s\S]*?\}\s*```/.test(s.body)) return "body has no json block";
  return null;
}

function json(status, value) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

export default { fetch: (request, env) => handle(request, env) };
