// GET /img/archive/{id}/YYYY/MM/DD/HH-MM.jpg -> slika iz R2 (samo ta oblika poti)
const KEY_RE = /^archive\/[a-z0-9-]+\/\d{4}\/\d{2}\/\d{2}\/\d{2}-\d{2}\.jpg$/;

export async function onRequestGet({ params, env }) {
  const key = [].concat(params.path || []).join("/");
  if (!KEY_RE.test(key)) return new Response("Not found", { status: 404 });
  const obj = await env.BUCKET.get(key);
  if (!obj) return new Response("Not found", { status: 404 });
  return new Response(obj.body, {
    headers: { "content-type": "image/jpeg", "cache-control": "public, max-age=86400" },
  });
}
