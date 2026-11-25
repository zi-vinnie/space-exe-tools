// Lattice, the TowerFix map page. Talks to server.py: GET /api/state, SSE
// /api/events, POST /api/... for controls. The true position click is kept
// in this page and only used to score fixes. It is never sent to the server.
//
// Like a Decca chart, the reference tower (St Thomas) is the master, in navy,
// and every other tower is a lane with its own colour and letter. The letter
// is shown wherever the colour is, so colour is never the only signal.

const INK = "#0b1450";
const LANE_COLORS = ["#c8302a", "#1f7a3a", "#6b2e8f", "#1d5fa8", "#0f7c7c", "#a3306b", "#7a5230", "#5a6270"];
const TRUTH = "#d46b00";
const towerColor = {};
const towerLane = {};   // tii -> "M" for the master, else "A", "B", ...
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
  lanes: L.layerGroup().addTo(map),
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

// Offsets are measured against St Thomas, so it is the master. If it is
// missing from towers.json, the first tower is.
function drawTowers() {
  const master = towers.find((t) => t.name === "St Thomas") || towers[0];
  let n = 0;
  for (const t of towers) {
    if (t === master) {
      towerColor[t.tii] = INK;
      towerLane[t.tii] = "M";
    } else {
      towerColor[t.tii] = LANE_COLORS[n % LANE_COLORS.length];
      towerLane[t.tii] = String.fromCharCode(65 + n);
      n++;
    }
    L.circleMarker([t.lat, t.lon], { radius: 7, color: "#fff", weight: 2.5, fillColor: towerColor[t.tii], fillOpacity: 1 })
      .bindTooltip(`${towerLane[t.tii]} · ${esc(t.name)}`, {
        permanent: true, direction: "right", className: "tower-label", offset: [10, 0],
      })
      .on("tooltipopen", (e) => e.tooltip.getElement()?.style.setProperty("--c", towerColor[t.tii]))
      .addTo(map);
  }
}

function laneChip(tii) {
  const lane = towerLane[tii] || "?";
  const cls = lane === "M" ? "lane master" : "lane";
  const title = lane === "M" ? "Master: every lane is timed against it" : `Lane ${lane}`;
  return `<span class="${cls}" style="--c:${towerColor[tii] || INK}" title="${title}">${lane}</span>`;
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
    const off = r.excluded ?? excluded.has(r.tii);
    tr.className = off ? "off" : "";
    tr.innerHTML = `
      <td>${laneChip(r.tii)}</td>
      <td><span class="name">${esc(r.name)}</span>${ref}<span class="why">${esc(r.tii)}${why ? " · " + esc(why) : ""}</span></td>
      <td class="num">${r.score_db !== undefined && r.score_db !== null ? fmt(r.score_db, 1) + " dB" : ""}</td>
      <td class="num">${r.heard ? fmt(r.delay_us, 3) + " µs" : ""}</td>
      <td class="num">${r.residual_ns !== undefined ? fmt(r.residual_ns, 0) + " ns" : ""}</td>
      <td class="use"><input type="checkbox" ${off ? "" : "checked"} data-tii="${esc(r.tii)}" aria-label="Use ${esc(r.name)}"></td>`;
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

// Where to put a hyperbola's lane tag: about 110 px along it from the fix
// on screen, so it sits near the crossing without covering it at any zoom.
// The tags move on zoom. With no fix, the middle of the line.
const TAG_PX = 110;
function lanePoint(points, fix) {
  if (!fix) return points[Math.floor(points.length / 2)];
  const px = (p) => map.latLngToLayerPoint(p);
  const at = px([fix.lat, fix.lon]);
  let best = 0, bestD = Infinity;
  points.forEach((p, i) => { const d = px(p).distanceTo(at); if (d < bestD) { bestD = d; best = i; } });
  const step = best < points.length / 2 ? 1 : -1;
  for (let i = best; i >= 0 && i < points.length; i += step) {
    if (px(points[i]).distanceTo(at) > TAG_PX) return points[i];
  }
  return points[step > 0 ? points.length - 1 : 0];
}

function drawLaneTags() {
  layers.lanes.clearLayers();
  if (!lastResult) return;
  for (const h of lastResult.hyperbolas) {
    if (!h.points.length) continue;
    L.marker(lanePoint(h.points, lastResult.fix), {
      interactive: false, keyboard: false,
      icon: L.divIcon({
        className: "", iconSize: null,
        html: `<div class="lane-tag${h.excluded ? " off" : ""}" style="--c:${towerColor[h.tii]}">${towerLane[h.tii] || "?"}</div>`,
      }),
    }).addTo(layers.lanes);
  }
}
map.on("zoomend", drawLaneTags);

// Chi-squared 95% point for k degrees of freedom (Wilson-Hilferty). Above
// it, the spare towers disagree with the fix more than timing noise explains.
function chi2Limit(k) {
  const a = 2 / (9 * k);
  return k * (1 - a + 1.6449 * Math.sqrt(a)) ** 3;
}

const ICON = {
  ok: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 7.5l3 3 7-7" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>',
  warn: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 1.5l6 11H1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M7 5.5v3.2M7 10.2v.6" stroke="currentColor" stroke-width="1.8"/></svg>',
};

function verdict(f, res) {
  if (res.ambiguous) return ["warn", "Two crossings fit"];
  if (f.dof === 0) return ["warn", "Unchecked: only 3 towers"];
  if (f.chi2 > chi2Limit(f.dof)) return ["bad", "Towers disagree"];
  return ["ok", `Checked by ${f.dof} spare ${f.dof === 1 ? "tower" : "towers"}`];
}

function showResult(res) {
  lastResult = res;
  layers.hyper.clearLayers();
  layers.fix.clearLayers();
  const f = res.fix;
  for (const h of res.hyperbolas) {
    if (!h.points.length) continue;
    const c = towerColor[h.tii];
    const name = (towers.find((t) => t.tii === h.tii) || {}).name || h.tii;
    L.polyline(h.points, {
      color: c, weight: h.excluded ? 2 : 3, opacity: h.excluded ? 0.6 : 0.95, dashArray: h.excluded ? "6 6" : null,
    }).bindTooltip(`Lane ${towerLane[h.tii]}: ${esc(name)} against ${esc(h.ref)}${h.excluded ? " (not used)" : ""}`)
      .addTo(layers.hyper);
  }
  drawLaneTags();
  const m = res.meta || {};
  const where = m.source === "live" ? `live chunk ${m.chunk}` : `${esc(m.source)} chunk ${m.chunk + 1} of ${m.count} (t = ${m.t_s} s)`;
  let html = `<div class="where">${where}, ${m.frames} frames, ${fmt(m.frequency_offset_hz, 1)} Hz offset` +
    (m.timing_jumps ? `, <span class="warn">${m.timing_jumps} timing jumps</span>` : "") + `</div>`;
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
      L.polygon(a.ellipse95, { color: "#3d4677", weight: 1.5, fillOpacity: 0.04, dashArray: "4 4" }).addTo(layers.fix);
      L.circleMarker([a.lat, a.lon], { radius: 6, color: "#3d4677", weight: 2, fillOpacity: 0, dashArray: "3 3" })
        .bindTooltip("Other crossing: fits the same").addTo(layers.fix);
    }
    L.polygon(f.ellipse95, { color: INK, weight: 1.5, fillColor: INK, fillOpacity: 0.1 })
      .bindTooltip("95% ellipse from timing noise only").addTo(layers.fix);
    // Chart fix symbol: a navy ring with a dot, white halo so it reads on any lane.
    L.circleMarker([f.lat, f.lon], { radius: 8, color: INK, weight: 3, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip("Fix").addTo(layers.fix);
    const dot = L.circleMarker([f.lat, f.lon], { radius: 2.5, color: INK, weight: 0, fillOpacity: 0.55 }).addTo(layers.track);
    track.push({ lat: f.lat, lon: f.lon, key, dot });
    const [kind, words] = verdict(f, res);
    html += `<div class="big">${f.lat.toFixed(6)}, ${f.lon.toFixed(6)}</div>
      <div class="verdict ${kind}">${ICON[kind === "ok" ? "ok" : "warn"]}${words}</div>
      <div class="small muted" style="margin-top:8px">1 sd ${fmt(f.sd_major_m, 1)} × ${fmt(f.sd_minor_m, 1)} m (timing noise only) ·
      χ² ${fmt(f.chi2, 2)} with ${f.dof} spare ${f.dof === 1 ? "tower" : "towers"}</div>`;
    if (f.dof === 0) html += `<div class="small warn">Only 3 towers, so nothing checks this fix.</div>`;
    if (res.ambiguous) html += `<div class="small warn">Two crossings fit. Chose the one ${res.chosen_by}.</div>`;
  } else {
    html += `<div class="verdict bad">${ICON.warn}No fix</div><div style="margin-top:8px">No fix: ${esc(res.why || "unknown")}</div>`;
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
    L.circleMarker([lat, lng], { radius: 3, color: TRUTH, weight: 0, fillColor: TRUTH, fillOpacity: 1 }).addTo(layers.truth);
    L.circleMarker([lat, lng], { radius: 10, color: TRUTH, weight: 3, fillOpacity: 0, dashArray: "4 3" }).bindTooltip("True position (scoring only)").addTo(layers.truth);
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
