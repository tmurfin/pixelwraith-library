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
