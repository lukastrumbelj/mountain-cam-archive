// Cloudflare Worker (+ statične datoteke iz frontend/).
// Statične datoteke postreže Cloudflare sam (brezplačno); ta Worker se zažene samo za /api in /img.
//   GET /api/status                      -> meta/status.json
//   GET /api/cam/:id/:date (YYYY-MM-DD)  -> archive/{id}/YYYY/MM/DD/index.json
//   GET /img/archive/{id}/YYYY/MM/DD/HH-MM.jpg -> slika
// R2 bucket je dostopen samo tukaj (binding BUCKET), nikoli brskalniku.

const ID_RE = /^[a-z0-9-]+$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const IMG_RE = /^archive\/[a-z0-9-]+\/\d{4}\/\d{2}\/\d{2}\/\d{2}-\d{2}\.jpg$/;
const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=60" };

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: JSON_HEADERS });

async function status(env) {
  const obj = await env.BUCKET.get("meta/status.json");
  return obj ? new Response(obj.body, { headers: JSON_HEADERS }) : json({ version: 1, cameras: {} });
}

async function camIndex(env, id, date) {
  const m = DATE_RE.exec(date);
  if (!ID_RE.test(id) || !m) return json({ error: "invalid" }, 400);
  const obj = await env.BUCKET.get(`archive/${id}/${m[1]}/${m[2]}/${m[3]}/index.json`);
  return obj ? new Response(obj.body, { headers: JSON_HEADERS }) : json({ camera_id: id, date, captures: [] });
}

async function image(env, key) {
  if (!IMG_RE.test(key)) return new Response("Not found", { status: 404 });
  const obj = await env.BUCKET.get(key);
  if (!obj) return new Response("Not found", { status: 404 });
  return new Response(obj.body, {
    headers: { "content-type": "image/jpeg", "cache-control": "public, max-age=86400" },
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405 });
    }
    const path = new URL(request.url).pathname;
    if (path === "/api/status") return status(env);
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
