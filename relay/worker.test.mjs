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
  assert.deepEqual(JSON.parse(calls[0].init.body), { title: good.title, body: good.body, state: "open" });
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
