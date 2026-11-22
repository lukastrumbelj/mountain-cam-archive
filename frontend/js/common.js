export const TZ = "Europe/Ljubljana";
const STALE_HOURS = 14; // največji normalen razmik je 19:00 -> 07:00 (12 h)

export async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

export const imgUrl = (path) => "/img/" + path;

export function fmtDateTime(iso) {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("sl-SI", {
    timeZone: TZ, day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(iso));
}

export function fmtDate(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("sl-SI", { weekday: "short", day: "numeric", month: "numeric", year: "numeric" })
    .format(new Date(y, m - 1, d));
}

export const slotLabel = (slot) => slot.replace("-", ":");

/** Stanje kamere: ok | stale | error | none */
export function health(cam) {
  if (cam.status === "error") return { key: "error", label: "Napaka" };
  if (!cam.last_success_utc) return { key: "none", label: "Ni podatkov" };
  const hours = (Date.now() - new Date(cam.last_success_utc).getTime()) / 3.6e6;
  if (hours > STALE_HOURS) return { key: "stale", label: "Zastarelo" };
  return { key: "ok", label: "Deluje" };
}

export const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  kids.flat().forEach((k) => e.append(k));
  return e;
};
