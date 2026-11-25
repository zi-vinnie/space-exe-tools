// TowerFix map page. Talks to server.py: GET /api/state, SSE /api/events,
// POST /api/... for controls. The true position click is kept in this page
// and only used to score fixes. It is never sent to the server.

const COLORS = ["#2f6fdf", "#d1495b", "#2a9d8f", "#e9a03b", "#8e5bd6", "#4c956c", "#c2559b", "#5c6b73"];
const towerColor = {};
const $ = (id) => document.getElementById(id);

const map = L.map("map", { zoomControl: true }).setView([50.70, -3.40], 10);
const attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
// Cached tiles: zoom 0 to 13 for the whole area, 14 to 16 round Exeter only.
L.tileLayer("/tiles/{z}/{x}/{y}.png", { maxNativeZoom: 13, maxZoom: 18, attribution }).addTo(map);
L.tileLayer("/tiles/{z}/{x}/{y}.png", {
  minZoom: 14, maxNativeZoom: 16, maxZoom: 18,
  bounds: L.latLngBounds([50.696, -3.570], [50.751, -3.485]),
}).addTo(map);
L.control.scale({ imperial: false }).addTo(map);

const layers = {
  hyper: L.layerGroup().addTo(map),
  fix: L.layerGroup().addTo(map),
  track: L.layerGroup().addTo(map),
  truth: L.layerGroup().addTo(map),
};
let towers = [];
let track = [];          // [{lat, lon}]
let truth = null;        // {lat, lon}, scoring only
let clickMode = "none";
let lastResult = null;
let status = {};

async function post(path, body = {}) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(v, d = 2) { return v === null || v === undefined ? "" : Number(v).toFixed(d); }

// Distances in metres on a local flat frame. Good enough for a few km.
function metres(a, b) {
  const R = 6371000, toRad = Math.PI / 180;
  const dn = (b.lat - a.lat) * toRad * R;
  const de = (b.lon - a.lon) * toRad * R * Math.cos(a.lat * toRad);
  return { de, dn, d: Math.hypot(de, dn) };
}

// ---- Towers -----------------------------------------------------------------

function drawTowers() {
  towers.forEach((t, i) => {
    towerColor[t.tii] = COLORS[i % COLORS.length];
    L.circleMarker([t.lat, t.lon], { radius: 7, color: "#fff", weight: 2, fillColor: towerColor[t.tii], fillOpacity: 1 })
      .bindTooltip(`${t.name} (${t.tii})`, { permanent: true, direction: "right", className: "tower-label", offset: [8, 0] })
      .addTo(map);
  });
}

function towerTable(res) {
  const body = $("towers").querySelector("tbody");
  body.innerHTML = "";
  const rows = res ? res.towers : towers.map((t) => ({ tii: t.tii, name: t.name }));
  const excluded = new Set(status.excluded || []);
  rows.sort((a, b) => (b.score_db ?? -99) - (a.score_db ?? -99));
  for (const r of rows) {
    const tr = document.createElement("tr");
    const ref = r.is_reference ? " (ref)" : "";
    const why = r.used ? "" : (r.why || "");
    tr.innerHTML = `
      <td><span class="swatch" style="background:${towerColor[r.tii]}"></span></td>
      <td>${esc(r.name)}${ref}<span class="why">${esc(r.tii)}${why ? " · " + esc(why) : ""}</span></td>
      <td class="num">${r.score_db !== undefined && r.score_db !== null ? fmt(r.score_db, 1) + " dB" : ""}</td>
      <td class="num">${r.heard ? fmt(r.delay_us, 3) + " µs" : ""}</td>
      <td class="num">${r.residual_ns !== undefined ? fmt(r.residual_ns, 0) + " ns" : ""}</td>
      <td><input type="checkbox" ${(r.excluded ?? excluded.has(r.tii)) ? "" : "checked"} data-tii="${esc(r.tii)}"></td>`;
    body.appendChild(tr);
  }
  body.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => post("/api/exclude", { tii: cb.dataset.tii, excluded: !cb.checked }).catch(showError));
  });
  const other = res && res.other_tii && res.other_tii.length
    ? "Also heard, not in towers.json: " + res.other_tii.map((o) => `${o.tower || "0E" + o.comb_hex} ${fmt(o.score_db, 1)} dB`).join(", ")
    : "";
  $("other-tii").textContent = other;
}

// ---- Results ----------------------------------------------------------------

function showResult(res) {
  lastResult = res;
  layers.hyper.clearLayers();
  layers.fix.clearLayers();
  for (const h of res.hyperbolas) {
    if (!h.points.length) continue;
    L.polyline(h.points, {
      color: towerColor[h.tii], weight: 2, opacity: h.excluded ? 0.5 : 0.9, dashArray: h.excluded ? "6 6" : null,
    }).bindTooltip(`${h.tii} minus ${h.ref}${h.excluded ? " (excluded)" : ""}`).addTo(layers.hyper);
  }
  const m = res.meta || {};
  const where = m.source === "live" ? `live chunk ${m.chunk}` : `${esc(m.source)} chunk ${m.chunk + 1} of ${m.count} (t = ${m.t_s} s)`;
  let html = `<div class="small">${where}, ${m.frames} frames, ${fmt(m.frequency_offset_hz, 1)} Hz offset` +
    (m.timing_jumps ? `, <span class="warn">${m.timing_jumps} timing jumps</span>` : "") + `</div>`;
  const f = res.fix;
  // One track point per chunk. A new result for a chunk (a re-solve after
  // a tower toggle, or going back to it) replaces its old point, and a
  // result with no fix removes it.
  const key = `${m.source}#${m.chunk}`;
  track = track.filter((p) => {
    if (p.key !== key) return true;
    layers.track.removeLayer(p.dot);
    return false;
  });
  if (f) {
    for (const a of res.alternates) {
      L.polygon(a.ellipse95, { color: "#888", weight: 1, fillOpacity: 0.05, dashArray: "4 4" }).addTo(layers.fix);
      L.circleMarker([a.lat, a.lon], { radius: 5, color: "#888", weight: 2, fillOpacity: 0 })
        .bindTooltip("Other crossing: fits the same").addTo(layers.fix);
    }
    L.polygon(f.ellipse95, { color: "#111", weight: 1.5, fillColor: "#111", fillOpacity: 0.12 })
      .bindTooltip("95% ellipse from timing noise only").addTo(layers.fix);
    L.circleMarker([f.lat, f.lon], { radius: 6, color: "#fff", weight: 2, fillColor: "#111", fillOpacity: 1 }).addTo(layers.fix);
    const dot = L.circleMarker([f.lat, f.lon], { radius: 2, color: "#111", weight: 0, fillOpacity: 0.5 }).addTo(layers.track);
    track.push({ lat: f.lat, lon: f.lon, key, dot });
    html += `<div class="big">${f.lat.toFixed(6)}, ${f.lon.toFixed(6)}</div>
      <div class="small">1 sd ${fmt(f.sd_major_m, 1)} × ${fmt(f.sd_minor_m, 1)} m (timing noise only) ·
      χ² ${fmt(f.chi2, 2)} with ${f.dof} spare ${f.dof === 1 ? "tower" : "towers"}</div>`;
    if (f.dof === 0) html += `<div class="small warn">Only 3 towers, so nothing checks this fix.</div>`;
    if (res.ambiguous) html += `<div class="small warn">Two crossings fit. Chose the one ${res.chosen_by}.</div>`;
  } else {
    html += `<div>No fix: ${esc(res.why || "unknown")}</div>`;
  }
  $("fix").innerHTML = html;
  towerTable(res);
  scoreTrack();
}

function scoreTrack() {
  if (!track.length) { $("track").textContent = ""; $("truth").textContent = truth ? "True position set." : ""; return; }
  const n = track.length;
  const mean = { lat: track.reduce((s, p) => s + p.lat, 0) / n, lon: track.reduce((s, p) => s + p.lon, 0) / n };
  const rms = Math.sqrt(track.reduce((s, p) => s + metres(mean, p).d ** 2, 0) / n);
  $("track").textContent = `${n} ${n === 1 ? "fix" : "fixes"} in the track. Scatter about their mean: ${rms.toFixed(1)} m RMS.`;
  if (truth) {
    const last = track[n - 1];
    const errs = track.map((p) => metres(truth, p).d).sort((a, b) => a - b);
    $("truth").innerHTML = `Scoring against the true position (never used for fixes).<br>
      Last fix error <b>${metres(truth, last).d.toFixed(1)} m</b> · mean fix error ${metres(truth, mean).d.toFixed(1)} m ·
      median ${errs[Math.floor(n / 2)].toFixed(1)} m · max ${errs[n - 1].toFixed(1)} m`;
  }
}

// ---- Status and offsets ----------------------------------------------------

function showStatus(s) {
  status = s;
  let txt = s.status;
  if (s.mode === "replay") {
    txt = `${s.file}: chunk ${s.index + 1} of ${s.count}, ${s.chunk_s} s each. ${s.playing ? "Playing." : s.status}`;
    $("seek").max = Math.max(0, s.count - 1);
    $("seek").value = s.index;
    $("seek").disabled = false;
  } else if (s.mode === "live") {
    txt = `Live, ${s.chunk_s} s chunks, ${s.chunks_in_run} analysed. ${s.status}`;
  }
  if (s.error) txt += ` Error: ${s.error}`;
  $("status").textContent = txt;
  $("status").className = s.error ? "bad" : "muted";
  $("play").textContent = s.playing ? "Pause" : "Play";
}

function showOffsets(o) {
  if (!o) { $("offsets").textContent = "No offsets file. Calibrate at a known site first."; return; }
  const rows = Object.entries(o.towers).map(([k, v]) => {
    const t = towers.find((t) => t.tii === k);
    return `${esc(t ? t.name : k)}: ${fmt(v.offset_us, 3)} µs`;
  });
  $("offsets").innerHTML = `Offsets vs St Thomas, from ${esc(o.site || "unnamed site")} (${esc(o.source)}, ${esc(o.created)}):<br>${rows.join("<br>")}`;
}

function showError(e) { $("status").textContent = "Error: " + e.message; $("status").className = "bad"; }

// ---- Controls ---------------------------------------------------------------

function setTab(which) {
  $("tab-replay").classList.toggle("on", which === "replay");
  $("tab-live").classList.toggle("on", which === "live");
  $("src-replay").hidden = which !== "replay";
  $("src-live").hidden = which !== "live";
}
$("tab-replay").onclick = () => setTab("replay");
$("tab-live").onclick = () => setTab("live");

function newRun() { track = []; layers.track.clearLayers(); scoreTrack(); }

$("open").onclick = () => { newRun(); post("/api/replay/open", { file: $("file").value, seconds: +$("seconds").value }).catch(showError); };
$("prev").onclick = () => post("/api/replay/seek", { index: (status.index || 0) - 1 }).catch(showError);
$("next").onclick = () => post("/api/replay/seek", { index: (status.index || 0) + 1 }).catch(showError);
$("play").onclick = () => post(status.playing ? "/api/replay/pause" : "/api/replay/play").catch(showError);
$("seek").onchange = () => post("/api/replay/seek", { index: +$("seek").value }).catch(showError);
$("live-start").onclick = () => { newRun(); post("/api/live/start", { gain: +$("gain").value, seconds: +$("live-seconds").value }).catch(showError); };
$("live-stop").onclick = () => post("/api/stop").catch(showError);
$("clear-track").onclick = newRun;

const clickHelp = {
  none: "Clicks on the map do nothing.",
  truth: "Click where the antenna really is. The page shows each fix's error. Fixes never use it.",
  calibrate: "Click where the antenna really is. The server re-measures each tower's offset from every chunk in this run and saves offsets.json. The old file is kept as offsets.prev.json.",
};
document.querySelectorAll("#click-mode .tab").forEach((b) => {
  b.onclick = () => {
    clickMode = b.dataset.mode;
    document.querySelectorAll("#click-mode .tab").forEach((x) => x.classList.toggle("on", x === b));
    $("click-help").textContent = clickHelp[clickMode];
    map.getContainer().style.cursor = clickMode === "none" ? "" : "crosshair";
  };
});

map.on("click", async (e) => {
  const { lat, lng } = e.latlng;
  if (clickMode === "truth") {
    truth = { lat, lon: lng };
    layers.truth.clearLayers();
    L.circleMarker([lat, lng], { radius: 3, color: "#1a7f37", weight: 0, fillColor: "#1a7f37", fillOpacity: 1 }).addTo(layers.truth);
    L.circleMarker([lat, lng], { radius: 9, color: "#1a7f37", weight: 3, fillOpacity: 0 }).bindTooltip("True position (scoring only)").addTo(layers.truth);
    scoreTrack();
  } else if (clickMode === "calibrate") {
    const n = status.chunks_in_run || 0;
    const site = prompt(`Calibrate at ${lat.toFixed(6)}, ${lng.toFixed(6)} using the ${n} chunks in this run?\nThis replaces offsets.json. Name the site:`, "");
    if (site === null) return;
    try {
      const r = await post("/api/calibrate", { lat, lon: lng, site });
      showOffsets(r.offsets);
      newRun();
    } catch (err) { showError(err); }
  }
});

// ---- Start ------------------------------------------------------------------

async function init() {
  const s = await (await fetch("/api/state")).json();
  towers = s.towers;
  drawTowers();
  $("file").innerHTML = s.recordings.map((r) => `<option>${esc(r)}</option>`).join("");
  showOffsets(s.offsets);
  showStatus(s.status);
  if (s.status.mode === "live") setTab("live");
  if (s.last_result) showResult(s.last_result); else towerTable(null);

  const es = new EventSource("/api/events");
  es.onopen = () => { $("conn").textContent = "connected"; $("conn").className = "pill ok"; };
  es.onerror = () => { $("conn").textContent = "disconnected"; $("conn").className = "pill bad"; };
  es.addEventListener("status", (ev) => showStatus(JSON.parse(ev.data)));
  es.addEventListener("result", (ev) => showResult(JSON.parse(ev.data)));
}
init().catch(showError);
