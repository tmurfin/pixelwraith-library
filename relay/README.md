# Submission relay

PixelWraith Grid posts a user's tile or projector to this Cloudflare Worker, which opens the GitHub issue with a
token kept in the worker's secret store. Users need no GitHub account. The issue body is the same as a
hand-filed one, so `scripts/merge.py` reads it unchanged.

## Contract

`POST /submit` with JSON `{ "kind": "tile" | "projector", "title": "…", "body": "…" }` answers
`201 { "number": 12, "url": "https://github.com/tmurfin/pixelwraith-library/issues/12" }`. A bad request answers
`400 { "error": "…" }` before GitHub is called (wrong kind, title outside 1–200 characters, body outside 1–20,000
characters or without a ```json block, anything over 32 KB); any other method `405`, any other path `404`;
GitHub rejecting the item (422, 404…) answers `400 { "error": "GitHub refused it: …" }`; GitHub unavailable, the
token lapsed or rate limited (5xx, 401, 403, 429) answers `502 { "error": "GitHub answered 503" }`. The app marks
an entry sent only on a 201 carrying the number, drops it on a 4xx carrying `error`, and otherwise keeps it
queued for its next launch (that includes the undeployed `workers.dev` placeholder, which answers a bare 404).

## Deploying (maintainer, once)

1. A fine-grained personal access token at github.com ▸ Settings ▸ Developer settings: repository access
   limited to `tmurfin/pixelwraith-library`, permission Issues: Read and write, expiry one year (note the date;
   the relay answers 502 once it lapses).
2. `npm install -g wrangler`, then `wrangler login` (opens the browser once).
3. In this folder: `wrangler deploy`, then `wrangler secret put GITHUB_TOKEN` and paste the token.
4. In the Cloudflare dashboard, Workers & Pages ▸ pixelwraith-library-submit ▸ Settings ▸ Triggers, note the
   `workers.dev` URL; in Security ▸ WAF ▸ Rate limiting rules add one for that hostname: 10 requests per minute
   per IP, block for 1 minute.
5. Put `https://<the workers.dev host>/submit` in `LibrarySubmission.endpoint` in the app and ship it.

Issues the relay opens are authored by the token's account. Cost: the Workers free plan allows 100,000
requests a day; a submission is one request.

## Testing

`node --test relay/worker.test.mjs` runs the worker against a fake GitHub (Node 20 or newer, no dependencies).
