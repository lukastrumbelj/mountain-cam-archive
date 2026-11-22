// node --test tests/functions.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

const load = (p) => import(pathToFileURL(path.resolve("functions", p)).href);
const bucket = (files) => ({ get: async (k) => (k in files ? { body: files[k] } : null) });

test("status: vrne JSON ali prazen status", async () => {
  const { onRequestGet } = await load("api/status.js");
  let r = await onRequestGet({ env: { BUCKET: bucket({ "meta/status.json": '{"cameras":{"a":{}}}' }) } });
  assert.equal(r.headers.get("cache-control"), "public, max-age=60");
  assert.deepEqual(await r.json(), { cameras: { a: {} } });
  r = await onRequestGet({ env: { BUCKET: bucket({}) } });
  assert.deepEqual(await r.json(), { version: 1, cameras: {} });
});

test("cam index: pot in validacija", async () => {
  const { onRequestGet } = await load("api/cam/[id]/[date].js");
  const env = { BUCKET: bucket({ "archive/vogel/2026/11/22/index.json": '{"captures":[1]}' }) };
  let r = await onRequestGet({ params: { id: "vogel", date: "2026-11-22" }, env });
  assert.deepEqual(await r.json(), { captures: [1] });
  r = await onRequestGet({ params: { id: "vogel", date: "2026-11-23" }, env });
  assert.deepEqual((await r.json()).captures, []);
  for (const p of [{ id: "../x", date: "2026-11-22" }, { id: "a", date: "2026-1-2" }]) {
    assert.equal((await onRequestGet({ params: p, env })).status, 400);
  }
});

test("img: samo veljavne poti slik", async () => {
  const { onRequestGet } = await load("img/[[path]].js");
  const k = "archive/vogel/2026/11/22/13-00.jpg";
  const env = { BUCKET: bucket({ [k]: "JPEG", "meta/status.json": "{}" }) };
  let r = await onRequestGet({ params: { path: k.split("/") }, env });
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("content-type"), "image/jpeg");
  for (const bad of ["meta/status.json", "archive/../meta/status.json", "archive/a/2026/11/22/index.json"]) {
    assert.equal((await onRequestGet({ params: { path: bad.split("/") }, env })).status, 404);
  }
  assert.equal((await onRequestGet({ params: { path: "archive/x/2026/11/22/09-00.jpg".split("/") }, env })).status, 404);
});
