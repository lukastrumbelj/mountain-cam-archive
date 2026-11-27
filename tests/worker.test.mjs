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

test("scheduled: pokliče GitHub dispatch z mode=slot", async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => { calls.push([url, init]); return new Response(null, { status: 204 }); };
  try {
    let p;
    const ALL = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0") + ":00").join(",");
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-27T11:00:00Z") }, { GH_TOKEN: "t", GH_REPO: "o/r", SLOTS: ALL }, { waitUntil: (x) => (p = x) });
    await p;
    assert.equal(calls[0][0], "https://api.github.com/repos/o/r/actions/workflows/capture.yml/dispatches");
    assert.equal(calls[0][1].headers.authorization, "Bearer t");
    assert.deepEqual(JSON.parse(calls[0][1].body), { ref: "main", inputs: { mode: "slot" } });
    globalThis.fetch = async () => new Response("bad", { status: 401 });
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-27T11:00:00Z") }, { GH_TOKEN: "t", GH_REPO: "o/r", SLOTS: ALL }, { waitUntil: (x) => (p = x) });
    await assert.rejects(p, /401/);
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-27T11:00:00Z") }, { GH_REPO: "o/r", SLOTS: ALL }, { waitUntil: (x) => (p = x) });
    await assert.rejects(p, /GH_TOKEN/);
  } finally { globalThis.fetch = realFetch; }
});

test("scheduled: zunaj terminov ne kliče GitHuba, ob terminu (poletni/zimski čas) kliče", async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (u, i) => { calls.push(u); return new Response(null, { status: 204 }); };
  const env = { GH_TOKEN: "t", GH_REPO: "o/r", SLOTS: "07:00,19:00,23:00" };
  const run = async (iso) => { let p; await worker.scheduled({ scheduledTime: Date.parse(iso) }, env, { waitUntil: (x) => (p = x) }); await p; };
  try {
    await run("2026-11-25T20:00:00Z");  // 21:00 CET: ni v SLOTS
    await run("2026-11-25T06:00:00Z");  // 07:00 CET: termin
    await run("2026-07-25T05:00:00Z");  // 07:00 CEST: termin
    await run("2026-07-25T06:00:00Z");  // 08:00 CEST: ni termin
    await run("2026-11-25T22:00:00Z");  // 23:00 CET: termin
    assert.equal(calls.length, 3);
  } finally { globalThis.fetch = realFetch; }
});

test("weather: API in slike (samo veljavne poti)", async () => {
  const files = {
    "meta/weather.json": '{"days":{"2026-11-27":{}}}',
    "weather/2026/11/27/karavanke.jpg": "JPEG",
    "weather/2026/11/27/index.json": "{}",
  };
  assert.deepEqual(await (await call("/api/weather", files)).json(), { days: { "2026-11-27": {} } });
  assert.deepEqual(await (await call("/api/weather")).json(), { version: 1, regions: {}, days: {} });
  assert.equal((await call("/img/weather/2026/11/27/karavanke.jpg", files)).status, 200);
  assert.equal((await call("/img/weather/2026/11/27/index.json", files)).status, 404);
  assert.equal((await call("/img/weather/2026/11/27/..%2F..%2Fmeta%2Fstatus.jpg", files)).status, 404);
  assert.equal((await call("/img/meta/weather.json", files)).status, 404);
});

test("scheduled: ob 12:00 sproži kamere in vreme; napaka enega ne ustavi drugega", async () => {
  const urls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (u) => { urls.push(u); return new Response(u.includes("weather") ? "err" : null, { status: u.includes("weather") ? 500 : 204 }); };
  const env = { GH_TOKEN: "t", GH_REPO: "o/r", SLOTS: "11:00,12:00", WEATHER_AT: "12:00" };
  const run = async (iso) => { let p; await worker.scheduled({ scheduledTime: Date.parse(iso) }, env, { waitUntil: (x) => (p = x) }); return p; };
  try {
    await run("2026-11-27T10:00:00Z");                      // 11:00 CET: samo kamere
    assert.deepEqual(urls.map((u) => u.split("/workflows/")[1]), ["capture.yml/dispatches"]);
    urls.length = 0;
    await assert.rejects(run("2026-11-27T11:00:00Z"), /weather\.yml 500/);   // 12:00 CET: oba; vreme vrne napako
    assert.deepEqual(urls.map((u) => u.split("/workflows/")[1]).sort(), ["capture.yml/dispatches", "weather.yml/dispatches"]);
    urls.length = 0;
    await run("2026-07-27T10:00:00Z").catch(() => {});      // 12:00 CEST: poletni čas
    assert.equal(urls.length, 2);
  } finally { globalThis.fetch = realFetch; }
});
