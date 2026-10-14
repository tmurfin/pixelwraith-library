import { test } from "node:test";
import assert from "node:assert/strict";
import { handle, validate } from "./worker.js";

const env = { GITHUB_TOKEN: "t" };
const good = { kind: "projector", title: "Projector: Barco UDM-4K22", body: "Spec sheet: x\n\n```json\n{\"manufacturer\":\"Barco\"}\n```" };
const request = (value, path = "/submit", method = "POST") =>
  new Request("https://relay.test" + path, { method, body: method === "POST" ? JSON.stringify(value) : undefined });
const calls = [];
const github = (status, body) => async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify(body), { status }); };

test("GET is refused and another path is not found", async () => {
  assert.equal((await handle(request(good, "/submit", "GET"), env)).status, 405);
  assert.equal((await handle(request(good, "/other"), env)).status, 404);
});

test("bad shapes are refused before GitHub is called", async () => {
  assert.equal(validate({ ...good, kind: "lens" }), "kind must be tile or projector");
  assert.equal(validate({ ...good, title: "x".repeat(201) }), "title must be 1–200 characters");
  assert.equal(validate({ ...good, title: "" }), "title must be 1–200 characters");
  assert.equal(validate({ ...good, body: "no block" }), "body has no json block");
  assert.equal(validate({ ...good, body: "```json\n{}\n```" + "x".repeat(20000) }), "body must be 1–20000 characters");
  assert.equal(validate("text"), "not an object");
  calls.length = 0;
  const notJSON = await handle(new Request("https://relay.test/submit", { method: "POST", body: "{" }), env, github(201, {}));
  assert.equal(notJSON.status, 400);
  assert.deepEqual(await notJSON.json(), { error: "not JSON" });
  const big = await handle(request({ ...good, body: "```json\n{}\n```" + "x".repeat(40 * 1024) }), env, github(201, {}));
  assert.equal(big.status, 400);
  assert.deepEqual(await big.json(), { error: "too large" });
  assert.equal(calls.length, 0);
});

test("the rate limiter answers 429 before GitHub is called, keyed by the client address", async () => {
  calls.length = 0;
  const keys = [];
  const limiter = { limit: async ({ key }) => { keys.push(key); return { success: false }; } };
  const limited = new Request("https://relay.test/submit", { method: "POST", body: JSON.stringify(good), headers: { "cf-connecting-ip": "203.0.113.7" } });
  const answer = await handle(limited, { ...env, RATE_LIMITER: limiter }, github(201, {}));
  assert.equal(answer.status, 429);
  assert.deepEqual(await answer.json(), { error: "too many submissions from this address; try again in a minute" });
  assert.deepEqual(keys, ["203.0.113.7"]);
  assert.equal(calls.length, 0);
  const allowed = { limit: async () => ({ success: true }) };
  const ok = await handle(request(good), { ...env, RATE_LIMITER: allowed }, github(201, { number: 1, html_url: "u" }));
  assert.equal(ok.status, 201);
  // The limit is checked before the body is read, so a flood of junk is turned away as cheaply as a real one
  const junk = await handle(request({}), { ...env, RATE_LIMITER: limiter }, github(201, {}));
  assert.equal(junk.status, 429);
});

test("a good submission opens the issue with the labels and the body unchanged", async () => {
  calls.length = 0;
  const answer = await handle(request(good), env, github(201, { number: 12, html_url: "https://github.com/tmurfin/pixelwraith-library/issues/12" }));
  assert.equal(answer.status, 201);
  assert.deepEqual(await answer.json(), { number: 12, url: "https://github.com/tmurfin/pixelwraith-library/issues/12" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.github.com/repos/tmurfin/pixelwraith-library/issues");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, "Bearer t");
  assert.deepEqual(JSON.parse(calls[0].init.body), { title: good.title, body: good.body, labels: ["submission", "projector"] });
});

test("GitHub rejecting the item becomes 400, so the app drops that one item", async () => {
  const answer = await handle(request(good), env, github(422, { message: "Validation Failed" }));
  assert.equal(answer.status, 400);
  assert.deepEqual(await answer.json(), { error: "GitHub refused it: Validation Failed" });
  assert.equal((await handle(request(good), env, github(404, { message: "Not Found" }))).status, 400);
});

test("GitHub being unavailable, or the token lapsing, becomes 502, so the app tries again later", async () => {
  const silent = await handle(request(good), env, github(500, "x"));
  assert.equal(silent.status, 502);
  assert.deepEqual(await silent.json(), { error: "GitHub answered 500" });
  assert.equal((await handle(request(good), env, github(401, { message: "Bad credentials" }))).status, 502);
  assert.equal((await handle(request(good), env, github(403, { message: "rate limited" }))).status, 502);
  assert.equal((await handle(request(good), env, github(429, {}))).status, 502);
});

import { createHmac } from "node:crypto";
import { sign } from "./worker.js";

const signed = { ...env, SIGNING_SECRET: "s3cret" };
const expectedKey = createHmac("sha256", "s3cret").update("12").digest("hex");

test("a create answers the issue's key, the HMAC of its number under the signing secret", async () => {
  assert.equal(await sign("s3cret", 12), expectedKey);
  const answer = await handle(request(good), signed, github(201, { number: 12, html_url: "u12" }));
  assert.deepEqual(await answer.json(), { number: 12, url: "u12", key: expectedKey });
  const unsigned = await handle(request(good), env, github(201, { number: 12, html_url: "u12" }));
  assert.deepEqual(await unsigned.json(), { number: 12, url: "u12" });
});

test("an update with the right key patches the issue open, comments, and answers 200", async () => {
  calls.length = 0;
  const gh = async (url, init) => {
    calls.push({ url, init });
    if (init.method === "PATCH") return new Response(JSON.stringify({ number: 12, html_url: "u12" }), { status: 200 });
    return new Response(JSON.stringify({ id: 1 }), { status: 201 });
  };
  const answer = await handle(request({ ...good, issue: { number: 12, key: expectedKey } }), signed, gh);
  assert.equal(answer.status, 200);
  assert.deepEqual(await answer.json(), { number: 12, url: "u12", key: expectedKey });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, "https://api.github.com/repos/tmurfin/pixelwraith-library/issues/12");
  assert.equal(calls[0].init.method, "PATCH");
  assert.deepEqual(JSON.parse(calls[0].init.body), { title: good.title, body: good.body, state: "open", labels: ["submission", "projector"] });
  assert.equal(calls[1].url, "https://api.github.com/repos/tmurfin/pixelwraith-library/issues/12/comments");
  assert.deepEqual(JSON.parse(calls[1].init.body), { body: "Updated from the app." });
});

test("a failed comment does not fail the update", async () => {
  const gh = async (url, init) => init.method === "PATCH"
    ? new Response(JSON.stringify({ number: 12, html_url: "u12" }), { status: 200 })
    : new Response("", { status: 500 });
  assert.equal((await handle(request({ ...good, issue: { number: 12, key: expectedKey } }), signed, gh)).status, 200);
});

test("a wrong key, or no signing secret, answers 403 without touching GitHub", async () => {
  calls.length = 0;
  const wrong = await handle(request({ ...good, issue: { number: 12, key: "nope" } }), signed, github(200, {}));
  assert.equal(wrong.status, 403);
  assert.deepEqual(await wrong.json(), { error: "not this app's submission" });
  const other = await handle(request({ ...good, issue: { number: 13, key: expectedKey } }), signed, github(200, {}));
  assert.equal(other.status, 403);
  const noSecret = await handle(request({ ...good, issue: { number: 12, key: expectedKey } }), env, github(200, {}));
  assert.equal(noSecret.status, 403);
  assert.equal(calls.length, 0);
});

test("a malformed issue reference is a bad request", async () => {
  assert.equal(validate({ ...good, issue: { number: "12", key: "k" } }), "issue must have a number and a key");
  assert.equal(validate({ ...good, issue: { number: 0, key: "k" } }), "issue must have a number and a key");
  assert.equal(validate({ ...good, issue: { number: 12 } }), "issue must have a number and a key");
  assert.equal(validate({ ...good, issue: "12" }), "issue must have a number and a key");
  assert.equal(validate(good), null);
});

test("an issue that is gone answers 403, so the app forgets it and opens a new one", async () => {
  calls.length = 0;
  const gone = await handle(request({ ...good, issue: { number: 12, key: expectedKey } }), signed, github(404, { message: "Not Found" }));
  assert.equal(gone.status, 403);
  assert.deepEqual(await gone.json(), { error: "that issue is gone" });
  assert.equal((await handle(request({ ...good, issue: { number: 12, key: expectedKey } }), signed, github(410, {}))).status, 403);
  assert.equal(calls.length, 2, "GitHub was asked both times; only its answer was re-read");
});

test("a null issue reads as no issue", async () => {
  assert.equal(validate({ ...good, issue: null }), null);
});

test("GitHub rejecting or failing an update maps like a create", async () => {
  const rejected = await handle(request({ ...good, issue: { number: 12, key: expectedKey } }), signed, github(422, { message: "Validation Failed" }));
  assert.equal(rejected.status, 400);
  assert.deepEqual(await rejected.json(), { error: "GitHub refused it: Validation Failed" });
  const down = await handle(request({ ...good, issue: { number: 12, key: expectedKey } }), signed, github(503, {}));
  assert.equal(down.status, 502);
});

const statusRequest = (issues) => new Request("https://relay.test/status", { method: "POST", body: JSON.stringify({ issues }) });
const ghStatus = (issueBody, comments, issueStatus = 200) => async (url, init) => {
  calls.push({ url, init });
  if (url.includes("/comments?per_page=100")) return new Response(JSON.stringify(comments), { status: 200 });
  return new Response(JSON.stringify({ comments: comments.length, ...issueBody }), { status: issueStatus });
};
const owner = (body) => ({ body, author_association: "OWNER" });
const stranger = (body) => ({ body, author_association: "NONE" });

test("status answers state, the label and the latest maintainer comment, skipping the app's own", async () => {
  calls.length = 0;
  const gh = ghStatus({ number: 12, state: "open", labels: [{ name: "submission" }, { name: "needs-changes" }] },
                      [owner("First look"), owner("Updated from the app."), owner("Add the pitch"), owner("Updated from the app."), stranger("Buy my tiles")]);
  const answer = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, gh);
  assert.equal(answer.status, 200);
  assert.deepEqual(await answer.json(), { issues: [{ number: 12, state: "open", needsChanges: true, approved: false, comment: "Add the pitch" }] });
  assert.equal(calls[0].init.method ?? "GET", "GET");
  assert.equal(calls[0].url, "https://api.github.com/repos/tmurfin/pixelwraith-library/issues/12");
  assert.equal(calls[1].url, "https://api.github.com/repos/tmurfin/pixelwraith-library/issues/12/comments?per_page=100&page=1");
});

test("status asks for comments only when the issue has some, and counts only the maintainer's", async () => {
  calls.length = 0;
  const none = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "open", labels: [] }, []));
  assert.deepEqual(await none.json(), { issues: [{ number: 12, state: "open", needsChanges: false, approved: false, comment: null }] });
  assert.equal(calls.length, 1, "no comments fetch for an issue without comments");
  const strangers = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "open", labels: [{ name: "needs-changes" }] }, [stranger("Spam"), { body: "Hi", author_association: "CONTRIBUTOR" }]));
  assert.deepEqual(await strangers.json(), { issues: [{ number: 12, state: "open", needsChanges: true, approved: false, comment: null }] });
  const member = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "open", labels: [] }, [{ body: "From a collaborator", author_association: "COLLABORATOR" }, stranger("later noise")]));
  assert.deepEqual(await member.json(), { issues: [{ number: 12, state: "open", needsChanges: false, approved: false, comment: "From a collaborator" }] });
});

test("a tighter limiter guards /status when one is bound", async () => {
  const limited = { limit: async () => ({ success: false }) };
  const answer = await handle(statusRequest([{ number: 12, key: expectedKey }]), { ...signed, RATE_LIMITER: { limit: async () => ({ success: true }) }, STATUS_LIMITER: limited }, ghStatus({}, []));
  assert.equal(answer.status, 429);
  const submit = await handle(request(good), { ...signed, RATE_LIMITER: { limit: async () => ({ success: true }) }, STATUS_LIMITER: limited }, github(201, { number: 1, html_url: "u" }));
  assert.equal(submit.status, 201, "the status limiter does not touch /submit");
});

test("status: no comment, closed, gone, a wrong key, a GitHub failure", async () => {
  const plain = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "closed", labels: [] }, []));
  assert.deepEqual(await plain.json(), { issues: [{ number: 12, state: "closed", needsChanges: false, approved: false, comment: null }] });
  const gone = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({}, [], 404));
  assert.deepEqual(await gone.json(), { issues: [{ number: 12, state: "gone", needsChanges: false, approved: false, comment: null }] });
  calls.length = 0;
  const wrong = await handle(statusRequest([{ number: 12, key: "nope" }, { number: 13, key: expectedKey }]), signed, ghStatus({ number: 12, state: "open", labels: [] }, []));
  assert.deepEqual(await wrong.json(), { issues: [] }, "a wrong key and a key for another number are both left out");
  assert.equal(calls.length, 0);
  const failing = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({}, [], 503));
  assert.deepEqual(await failing.json(), { issues: [] }, "a GitHub failure leaves the issue out");
  const noSecret = await handle(statusRequest([{ number: 12, key: expectedKey }]), env, ghStatus({ number: 12, state: "open", labels: [] }, []));
  assert.deepEqual(await noSecret.json(), { issues: [] });
});

test("status refuses a bad list before GitHub", async () => {
  calls.length = 0;
  assert.equal((await handle(statusRequest([]), signed, ghStatus({}, []))).status, 400);
  assert.equal((await handle(statusRequest(Array.from({ length: 26 }, (_, i) => ({ number: i + 1, key: "k" }))), signed, ghStatus({}, []))).status, 400);
  assert.equal((await handle(statusRequest([{ number: "12", key: "k" }]), signed, ghStatus({}, []))).status, 400);
  assert.equal((await handle(new Request("https://relay.test/status", { method: "POST", body: "{}" }), signed, ghStatus({}, []))).status, 400);
  assert.equal((await handle(new Request("https://relay.test/status", { method: "GET" }), signed, ghStatus({}, []))).status, 405);
  assert.equal(calls.length, 0);
});

test("status reports the approved label", async () => {
  const yes = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "open", labels: [{ name: "approved" }] }, []));
  assert.deepEqual(await yes.json(), { issues: [{ number: 12, state: "open", needsChanges: false, approved: true, comment: null }] });
  const no = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "open", labels: [] }, []));
  assert.deepEqual(await no.json(), { issues: [{ number: 12, state: "open", needsChanges: false, approved: false, comment: null }] });
});

test("status counts the repository's own workflow bot as the maintainer", async () => {
  const bot = { body: "Added in version 7", author_association: "NONE", user: { login: "github-actions[bot]", type: "Bot" } };
  const answer = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "closed", labels: [] }, [bot]));
  assert.deepEqual(await answer.json(), { issues: [{ number: 12, state: "closed", needsChanges: false, approved: false, comment: "Added in version 7" }] });
  const otherBot = { body: "Spam", author_association: "NONE", user: { login: "some-other[bot]", type: "Bot" } };
  const skipped = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, ghStatus({ number: 12, state: "open", labels: [] }, [otherBot]));
  assert.deepEqual(await skipped.json(), { issues: [{ number: 12, state: "open", needsChanges: false, approved: false, comment: null }] });
});

test("status reads the last page of comments on a long issue", async () => {
  calls.length = 0;
  const gh = async (url, init) => {
    calls.push({ url, init });
    if (url.includes("/comments")) return new Response(JSON.stringify([owner("Latest word")]), { status: 200 });
    return new Response(JSON.stringify({ number: 12, state: "open", labels: [], comments: 150 }), { status: 200 });
  };
  const answer = await handle(statusRequest([{ number: 12, key: expectedKey }]), signed, gh);
  assert.deepEqual(await answer.json(), { issues: [{ number: 12, state: "open", needsChanges: false, approved: false, comment: "Latest word" }] });
  assert.ok(calls[1].url.endsWith("/comments?per_page=100&page=2"), calls[1].url);
});
