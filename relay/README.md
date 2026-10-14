# Submission relay

PixelWraith Grid posts a user's tile or projector to this Cloudflare Worker, which opens the GitHub issue with a
token kept in the worker's secret store. Users need no GitHub account. The issue body is the same as a
hand-filed one, so `scripts/merge.py` reads it unchanged.

## Contract

`POST /submit` with JSON `{ "kind": "tile" | "projector", "title": "…", "body": "…" }` answers
`201 { "number": 12, "url": "https://github.com/tmurfin/pixelwraith-library/issues/12" }`. A bad request answers
`400 { "error": "…" }` before GitHub is called (wrong kind, title outside 1–200 characters, body outside 1–20,000
characters or without a ```json block, anything over 32 KB); `429 { "error": "…" }` past sixty posts a minute
from one address (the rate-limit binding in `wrangler.toml`); any other method `405`, any other path `404`;
GitHub rejecting the item (422, 404…) answers `400 { "error": "GitHub refused it: …" }`; GitHub unavailable, the
token lapsed or rate limited (5xx, 401, 403, 429) answers `502 { "error": "GitHub answered 503" }`. The app marks
an entry sent only on a 201 carrying the number, drops it on a 4xx carrying `error`, and otherwise keeps it
queued for its next launch (that includes the undeployed `workers.dev` placeholder, which answers a bare 404).

A request may carry `"issue": { "number": 12, "key": "…" }`, the number and key a create answered; the worker
then updates that issue's title and body, reopens it, leaves the comment "Updated from the app." and answers
`200 { "number", "url", "key" }`. The key is the HMAC-SHA256 of the number under the worker secret
`SIGNING_SECRET`, so only the app that made a submission can change it; a wrong key, or a worker without the
secret, answers `403 { "error": "not this app's submission" }`, and the app then opens a new issue instead.

`POST /status` with `{ "issues": [ { "number": 12, "key": "…" } ] }` (up to 25) answers, for each reference whose
key is this worker's, `{ "number", "state", "needsChanges", "comment" }`: GitHub's `open` or `closed` (`gone`
when the issue was deleted), whether the `needs-changes` label is on, and the latest comment by the repository's
owner, a member or a collaborator that is not the app's own "Updated from the app." (the repository is public, so
a stranger's comment never reaches the app). Wrong keys and GitHub failures leave the issue out; an issue
without comments costs one GitHub call, with comments two. The app checks at launch and on Settings ▸ Check
Now; `/status` has its own limiter, ten a minute per address. An update also resets the issue's labels to `submission` and the kind, taking
`needs-changes` off.

## Deploying (maintainer, once)

1. A fine-grained personal access token at github.com ▸ Settings ▸ Developer settings: repository access
   limited to `tmurfin/pixelwraith-library`, permission Issues: Read and write, expiry one year (note the date;
   the relay answers 502 once it lapses).
2. `npm install -g wrangler`, then `wrangler login` (opens the browser once).
3. In this folder: `wrangler deploy`, then `wrangler secret put GITHUB_TOKEN` and paste the token.
   Then `wrangler secret put SIGNING_SECRET` and paste any long random string, for instance the output of
   `openssl rand -hex 32`. Without it submissions still work, but every resubmit opens a new issue.
4. The deploy prints the `workers.dev` URL; put `https://<that host>/submit` in `LibrarySubmission.endpoint` in
   the app and ship it. The rate limit needs no dashboard step: the binding in `wrangler.toml` deploys with the
   worker (Wrangler 4.36 or newer). Cloudflare counts it per edge server and calls it approximate: a burst over one
   connection trips at exactly sixty, while requests spread over many connections can exceed it. To check it after a
   deploy, send eighty empty POSTs over one reused connection (`curl -X POST -d '{}' <url> <url> …`): sixty answer
   400, the rest 429. Empty POSTs never reach GitHub.

Issues the relay opens are authored by the token's account. Cost: the Workers free plan allows 100,000
requests a day; a submission is one request.

## Testing

`node --test relay/worker.test.mjs` runs the worker against a fake GitHub (Node 20 or newer, no dependencies).
