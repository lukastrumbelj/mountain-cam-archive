// node --test tests/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/worker.js";

const bucket = (files) => ({ get: async (k) => (k in files ? { body: files[k] } : null) });
const call = (path, files = {}, method = "GET") =>
  worker.fetch(new Request("https://x.test" + path, { method }), { BUCKET: bucket(files) });

test("status: vrne JSON ali prazen status", async () => {
  let r = await call("/api/status", { "meta/status.json": '{"cameras":{"a":{}}}' });
  assert.equal(r.headers.get("cache-control"), "public, max-age=60");
  assert.deepEqual(await r.json(), { cameras: { a: {} } });
  assert.deepEqual(await (await call("/api/status")).json(), { version: 1, cameras: {} });
});

test("cam index: pot, prazen dan in validacija", async () => {
  const files = { "archive/vogel/2026/11/22/index.json": '{"captures":[1]}' };
  assert.deepEqual(await (await call("/api/cam/vogel/2026-11-22", files)).json(), { captures: [1] });
  assert.deepEqual((await (await call("/api/cam/vogel/2026-11-23", files)).json()).captures, []);
  assert.equal((await call("/api/cam/a/2026-1-2", files)).status, 400);
  assert.equal((await call("/api/cam/..%2Fx/2026-11-22", files)).status, 400);
  assert.equal((await call("/api/cam/A_B/2026-11-22", files)).status, 400);
});

test("img: samo veljavne poti slik", async () => {
  const k = "archive/vogel/2026/11/22/13-00.jpg";
  const files = { [k]: "JPEG", "meta/status.json": "{}", "archive/a/2026/11/22/index.json": "{}" };
  const r = await call("/img/" + k, files);
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("content-type"), "image/jpeg");
  for (const bad of ["meta/status.json", "archive/../meta/status.json", "archive/a/2026/11/22/index.json", "%E0%A4%A"]) {
    assert.notEqual((await call("/img/" + bad, files)).status, 200);
  }
  assert.equal((await call("/img/archive/x/2026/11/22/09-00.jpg", files)).status, 404);
});

test("druge poti in metode", async () => {
  assert.equal((await call("/nekaj")).status, 404);
  assert.equal((await call("/api/status", {}, "POST")).status, 405);
});
