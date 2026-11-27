// Cloudflare Worker (+ statične datoteke iz frontend/).
// Statične datoteke postreže Cloudflare sam (brezplačno); ta Worker se zažene samo za /api in /img.
//   GET /api/status                      -> meta/status.json
//   GET /api/cam/:id/:date (YYYY-MM-DD)  -> archive/{id}/YYYY/MM/DD/index.json
//   GET /img/archive/{id}/YYYY/MM/DD/HH-MM.jpg -> slika
//   GET /api/weather                     -> meta/weather.json (dnevni posnetki ARSO napovedi)
//   GET /img/weather/YYYY/MM/DD/{id}.jpg -> posnetek napovedi
// R2 bucket je dostopen samo tukaj (binding BUCKET), nikoli brskalniku.

const ID_RE = /^[a-z0-9-]+$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const IMG_RE = /^archive\/[a-z0-9-]+\/\d{4}\/\d{2}\/\d{2}\/\d{2}-\d{2}\.jpg$/;
const WEATHER_IMG_RE = /^weather\/\d{4}\/\d{2}\/\d{2}\/[a-z0-9-]+\.jpg$/;
const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=60" };

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: JSON_HEADERS });

async function status(env) {
  const obj = await env.BUCKET.get("meta/status.json");
  return obj ? new Response(obj.body, { headers: JSON_HEADERS }) : json({ version: 1, cameras: {} });
}

async function weather(env) {
  const obj = await env.BUCKET.get("meta/weather.json");
  return obj ? new Response(obj.body, { headers: JSON_HEADERS }) : json({ version: 1, regions: {}, days: {} });
}

async function camIndex(env, id, date) {
  const m = DATE_RE.exec(date);
  if (!ID_RE.test(id) || !m) return json({ error: "invalid" }, 400);
  const obj = await env.BUCKET.get(`archive/${id}/${m[1]}/${m[2]}/${m[3]}/index.json`);
  return obj ? new Response(obj.body, { headers: JSON_HEADERS }) : json({ camera_id: id, date, captures: [] });
}

async function image(env, key) {
  if (!IMG_RE.test(key) && !WEATHER_IMG_RE.test(key)) return new Response("Not found", { status: 404 });
  const obj = await env.BUCKET.get(key);
  if (!obj) return new Response("Not found", { status: 404 });
  return new Response(obj.body, {
    headers: { "content-type": "image/jpeg", "cache-control": "public, max-age=86400" },
  });
}

// Sprožilci: Cloudflare cron ob vsaki polni uri (UTC); če je lokalna ura (Europe/Ljubljana) med termini,
// pokliče GitHub API (workflow_dispatch). GitHubov "schedule" je nezanesljiv.
//   SLOTS      termini zajema kamer       -> capture.yml   (uskladi z config/cameras.yaml -> settings.slots)
//   WEATHER_AT ura dnevnega posnetka ARSO -> weather.yml   (uskladi z config/weather.yaml -> settings.time)
// Python ima še svojo zaščito (--require-slot), zato napaka tukaj ne povzroči napačnih imen slik.
function isSlotHour(list, tz, when) {
  const slots = String(list || "").split(",").map((x) => x.trim()).filter(Boolean);
  if (!slots.length) return false;
  const hhmm = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz || "Europe/Ljubljana", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(when);
  return slots.includes(hhmm);
}

// Skrivnost GH_TOKEN: fine-grained PAT, samo ta repozitorij, Actions: Read and write.
async function dispatch(env, workflow) {
  if (!env.GH_TOKEN) throw new Error("manjka skrivnost GH_TOKEN");
  const url = `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${workflow}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "mountain-cam-archive-trigger",
      "content-type": "application/json",
    },
    body: JSON.stringify({ ref: env.GH_REF || "main", inputs: { mode: "slot" } }),
  });
  if (!res.ok) throw new Error(`GitHub dispatch ${workflow} ${res.status}: ${(await res.text()).slice(0, 200)}`);
}

export default {
  async scheduled(event, env, ctx) {
    const when = new Date(event.scheduledTime ?? Date.now());
    const jobs = [];
    if (isSlotHour(env.SLOTS, env.TIMEZONE, when)) jobs.push(dispatch(env, env.GH_WORKFLOW || "capture.yml"));
    if (isSlotHour(env.WEATHER_AT, env.TIMEZONE, when)) jobs.push(dispatch(env, env.GH_WEATHER_WORKFLOW || "weather.yml"));
    // allSettled: neuspel klic enega delovnega toka ne prepreči drugega; napaka se vseeno zabeleži.
    ctx.waitUntil(Promise.allSettled(jobs).then((rs) => {
      const bad = rs.find((r) => r.status === "rejected");
      if (bad) throw bad.reason;
    }));
  },

  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405 });
    }
    const path = new URL(request.url).pathname;
    if (path === "/api/status") return status(env);
    if (path === "/api/weather") return weather(env);
    let m = path.match(/^\/api\/cam\/([^/]+)\/([^/]+)$/);
    if (m) return camIndex(env, m[1], m[2]);
    if (path.startsWith("/img/")) {
      let key;
      try { key = decodeURIComponent(path.slice(5)); } catch { return new Response("Bad request", { status: 400 }); }
      return image(env, key);
    }
    return new Response("Not found", { status: 404 });
  },
};
