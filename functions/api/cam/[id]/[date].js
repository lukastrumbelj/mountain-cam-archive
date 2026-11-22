// GET /api/cam/:id/:date (YYYY-MM-DD) -> archive/{id}/YYYY/MM/DD/index.json
const ID_RE = /^[a-z0-9-]+$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export async function onRequestGet({ params, env }) {
  const headers = {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "public, max-age=60",
  };
  const m = DATE_RE.exec(params.date || "");
  if (!ID_RE.test(params.id || "") || !m) {
    return new Response(JSON.stringify({ error: "invalid" }), { status: 400, headers });
  }
  const obj = await env.BUCKET.get(`archive/${params.id}/${m[1]}/${m[2]}/${m[3]}/index.json`);
  if (!obj) {
    return new Response(JSON.stringify({ camera_id: params.id, date: params.date, captures: [] }), { headers });
  }
  return new Response(obj.body, { headers });
}
