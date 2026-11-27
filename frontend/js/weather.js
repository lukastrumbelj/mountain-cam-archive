import { api, el, fmtDateTime, imgUrl } from "./common.js";

const $ = (id) => document.getElementById(id);
const summary = $("summary");
const q = new URLSearchParams(location.search);
let data, regionIds, dates;
const state = { region: q.get("region"), date: q.get("date"), zoom: false };

const dayLabel = (iso) => {
  const [y, m, d] = iso.split("-").map(Number);
  const w = new Intl.DateTimeFormat("sl-SI", { weekday: "short" }).format(new Date(y, m - 1, d));
  return `${w} ${d}. ${m}.`;
};
const pressed = (btn, on) => { btn.setAttribute("aria-pressed", String(on)); return btn; };
const entry = (region, date) => (data.days[date] || {})[region];
const hasImg = (region, date) => entry(region, date)?.status === "ok";

function sync() {
  const u = new URL(location.href);
  u.searchParams.set("region", state.region);
  u.searchParams.set("date", state.date);
  history.replaceState(null, "", u);
}

function render() {
  $("regions").replaceChildren(...regionIds.map((id) => pressed(el("button", {
    type: "button", textContent: data.regions[id].name,
    onclick: () => { state.region = id; render(); },
  }), id === state.region)));
  $("days").replaceChildren(...dates.map((d) => pressed(el("button", {
    type: "button", textContent: dayLabel(d),
    className: hasImg(state.region, d) ? "" : "missing", title: hasImg(state.region, d) ? "" : "Ni posnetka",
    onclick: () => { state.date = d; render(); },
  }), d === state.date)));

  const i = dates.indexOf(state.date);
  $("newer").disabled = i <= 0;
  $("older").disabled = i >= dates.length - 1;
  pressed($("zoom"), state.zoom);
  $("zoom").textContent = state.zoom ? "Prilagodi širini" : "Prava velikost";
  $("orig").href = data.regions[state.region].url;

  const e = entry(state.region, state.date);
  const v = $("viewer");
  v.classList.toggle("zoomed", state.zoom);
  if (e && e.status === "ok") {
    $("info").textContent = `${data.regions[state.region].name} · zajeto ${fmtDateTime(e.captured_at_utc)}`;
    v.replaceChildren(el("img", {
      className: "wx-img", src: imgUrl(e.path), loading: "lazy",
      alt: `ARSO napoved: ${data.regions[state.region].name}, ${dayLabel(state.date)}`,
    }));
  } else {
    $("info").textContent = "";
    v.replaceChildren(el("div", { className: e ? "error-box" : "muted wx-empty",
      textContent: e ? `Zajem ni uspel: ${e.error || "neznana napaka"}` : "Za ta dan ni posnetka." }));
  }
  sync();
}

function step(delta) {
  const i = dates.indexOf(state.date) + delta;
  if (i >= 0 && i < dates.length) { state.date = dates[i]; render(); }
}

try {
  data = await api("/api/weather");
  regionIds = Object.keys(data.regions || {});
  dates = Object.keys(data.days || {}).sort().reverse();
  if (!regionIds.length || !dates.length) {
    summary.textContent = "Še ni nobenega posnetka vremena.";
  } else {
    if (!regionIds.includes(state.region)) state.region = regionIds[0];
    if (!dates.includes(state.date)) state.date = dates.find((d) => hasImg(state.region, d)) || dates[0];
    summary.textContent = `${regionIds.length} območij, ${dates.length} dni arhiva`;
    $("app").hidden = false;
    $("newer").onclick = () => step(-1);
    $("older").onclick = () => step(1);
    $("zoom").onclick = () => { state.zoom = !state.zoom; render(); };
    document.addEventListener("keydown", (ev) => {
      if (ev.target.closest("input,select,textarea")) return;
      if (ev.key === "ArrowLeft") step(1);   // levo = starejši dan
      if (ev.key === "ArrowRight") step(-1);
    });
    render();
  }
} catch (e) {
  summary.replaceWith(el("div", { className: "error-box", textContent: `Napaka pri nalaganju: ${e.message}` }));
}
