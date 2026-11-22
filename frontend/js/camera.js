import { api, el, fmtDate, fmtDateTime, health, imgUrl, slotLabel } from "./common.js";

const $ = (s) => document.querySelector(s);
const id = new URLSearchParams(location.search).get("id") || "";
const cache = new Map();

/** Uspešni zajemi dneva (samo shranjene slike, brez ustvarjanja videa). */
async function day(date) {
  if (!cache.has(date)) {
    try {
      const j = await api(`/api/cam/${encodeURIComponent(id)}/${date}`);
      cache.set(date, (j.captures || []).filter((c) => c.status === "ok" && c.path));
    } catch {
      cache.set(date, []);
    }
  }
  return cache.get(date);
}

const fillDates = (sel, dates, value) =>
  sel.replaceChildren(...dates.map((d) => el("option", { value: d, textContent: fmtDate(d), selected: d === value })));

let dates = []; // padajoče (najnovejši prvi)

/* ---------- Pregled ---------- */
const view = { date: null, i: 0, caps: [] };

async function showDay(date, i = null) {
  view.date = date;
  view.caps = await day(date);
  view.i = i === null ? Math.max(view.caps.length - 1, 0) : i;
  $("#dateSel").value = date;
  paintView();
}

function paintView() {
  const c = view.caps[view.i];
  $("#big").src = c ? imgUrl(c.path) : "";
  $("#big").alt = c ? `${$("#title").textContent}, ${view.date} ${slotLabel(c.slot)}` : "";
  $("#caption").textContent = c
    ? `${fmtDate(view.date)} ob ${slotLabel(c.slot)}` +
      (c.captured_at_local ? ` (zajeto ob ${c.captured_at_local.slice(11, 16)})` : "")
    : "Za ta dan ni slik.";
  $("#hours").replaceChildren(...view.caps.map((cap, k) =>
    el("button", { textContent: slotLabel(cap.slot), onclick: () => { view.i = k; paintView(); } },
    )).map((b, k) => { b.setAttribute("aria-pressed", String(k === view.i)); return b; }));
  const di = dates.indexOf(view.date);
  $("#prev").disabled = view.i === 0 && di >= dates.length - 1;
  $("#next").disabled = view.i >= view.caps.length - 1 && di <= 0;
}

async function step(dir) {
  const j = view.i + dir;
  if (j >= 0 && j < view.caps.length) { view.i = j; return paintView(); }
  const di = dates.indexOf(view.date) - dir; // dates so padajoče
  for (let k = di; k >= 0 && k < dates.length; k -= dir) {
    const caps = await day(dates[k]);
    if (caps.length) return showDay(dates[k], dir > 0 ? 0 : caps.length - 1);
  }
}

/* ---------- Časovni posnetek ---------- */
const lapse = { frames: [], i: 0, timer: null };

async function buildLapse() {
  stopLapse();
  const scope = $("#lapseScope").value;
  $("#lapseDate").hidden = scope !== "day";
  const use = scope === "day" ? [$("#lapseDate").value] : dates.slice(0, 7);
  const all = [];
  for (const d of [...use].sort()) for (const c of await day(d)) all.push({ d, c });
  lapse.frames = all;
  all.forEach((f) => { new Image().src = imgUrl(f.c.path); }); // predpomnjenje
  $("#lapseRange").max = Math.max(all.length - 1, 0);
  lapseShow(0);
}

function lapseShow(i) {
  lapse.i = i;
  const f = lapse.frames[i];
  $("#lapseRange").value = i;
  $("#lapseImg").src = f ? imgUrl(f.c.path) : "";
  $("#lapseCaption").textContent = f
    ? `${fmtDate(f.d)} ob ${slotLabel(f.c.slot)} (${i + 1}/${lapse.frames.length})`
    : "Ni slik za predvajanje.";
}

function stopLapse() {
  clearTimeout(lapse.timer);
  lapse.timer = null;
  $("#playBtn").textContent = "▶ Predvajaj";
}

function playLapse() {
  if (lapse.timer) return stopLapse();
  if (lapse.frames.length < 2) return;
  $("#playBtn").textContent = "⏸ Ustavi";
  const tick = () => {
    lapseShow((lapse.i + 1) % lapse.frames.length);
    lapse.timer = setTimeout(tick, 900 / Number($("#lapseSpeed").value));
  };
  lapse.timer = setTimeout(tick, 900 / Number($("#lapseSpeed").value));
}

/* ---------- Primerjava ---------- */
async function cmpSide(side, hourPreferred) {
  const caps = await day($(`#date${side}`).value);
  const hs = $(`#hour${side}`);
  hs.replaceChildren(...caps.map((c) => el("option", { value: c.path, textContent: slotLabel(c.slot) })));
  const pick = caps.find((c) => c.slot === hourPreferred) || caps[caps.length - 1];
  if (pick) hs.value = pick.path;
  $(`#img${side}`).src = pick ? imgUrl(hs.value) : "";
}

/* ---------- zagon ---------- */
try {
  const status = await api("/api/status");
  const cam = status.cameras?.[id];
  if (!cam) throw new Error("Kamera ne obstaja.");
  document.title = `${cam.name} – arhiv`;
  $("#title").textContent = cam.name;
  $("#sub").textContent = `${cam.location || ""} · zadnji zajem ${fmtDateTime(cam.last_success_utc)}`;
  const h = health(cam);
  $("#badge").replaceChildren(el("span", { className: `badge ${h.key}`, textContent: h.label }));
  if (cam.status === "error" && cam.error) {
    $("#err").replaceChildren(el("div", { className: "error-box", textContent: `Zadnji poskus ni uspel: ${cam.error}` }));
  }

  dates = [...(cam.dates || [])].sort().reverse();
  if (!dates.length) throw new Error("Za to kamero še ni slik.");
  for (const s of ["#dateSel", "#lapseDate", "#dateA", "#dateB"]) fillDates($(s), dates, dates[0]);
  $("#dateB").value = dates[1] || dates[0];

  await showDay(dates[0]);
  $("#dateSel").onchange = (e) => showDay(e.target.value);
  $("#prev").onclick = () => step(-1);
  $("#next").onclick = () => step(1);
  document.addEventListener("keydown", (e) => {
    if ($("#view").hidden || ["SELECT", "INPUT"].includes(document.activeElement.tagName)) return;
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  });

  const tabs = { view: $("#view"), lapse: $("#lapse"), cmp: $("#cmp") };
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = async () => {
    stopLapse();
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    Object.entries(tabs).forEach(([k, s]) => (s.hidden = k !== b.dataset.tab));
    if (b.dataset.tab === "lapse") await buildLapse();
    if (b.dataset.tab === "cmp") {
      const slot = view.caps[view.i]?.slot;
      await cmpSide("A", slot);
      await cmpSide("B", slot);
    }
  }));

  $("#lapseScope").onchange = buildLapse;
  $("#lapseDate").onchange = buildLapse;
  $("#playBtn").onclick = playLapse;
  $("#lapsePrev").onclick = () => { stopLapse(); lapseShow(Math.max(lapse.i - 1, 0)); };
  $("#lapseNext").onclick = () => { stopLapse(); lapseShow(Math.min(lapse.i + 1, lapse.frames.length - 1)); };
  $("#lapseRange").oninput = (e) => { stopLapse(); lapseShow(Number(e.target.value)); };

  for (const s of ["A", "B"]) {
    $(`#date${s}`).onchange = () => cmpSide(s, $(`#hour${s}`).selectedOptions[0]?.textContent.replace(":", "-"));
    $(`#hour${s}`).onchange = (e) => { $(`#img${s}`).src = imgUrl(e.target.value); };
  }
} catch (e) {
  $("#title").textContent = "Napaka";
  $("#err").replaceChildren(el("div", { className: "error-box", textContent: e.message }));
}
