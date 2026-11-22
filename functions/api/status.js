// GET /api/status -> meta/status.json iz R2
export async function onRequestGet({ env }) {
  const obj = await env.BUCKET.get("meta/status.json");
  const headers = {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "public, max-age=60",
  };
  if (!obj) {
    return new Response(JSON.stringify({ version: 1, cameras: {} }), { headers });
  }
  return new Response(obj.body, { headers });
}
