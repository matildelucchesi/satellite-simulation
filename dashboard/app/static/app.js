"use strict";

const state = { pausedLogs: false, lastLogs: [], inFlight: false };
const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
  createStars();
  $("pauseLogs").addEventListener("click", () => {
    state.pausedLogs = !state.pausedLogs;
    $("pauseLogs").textContent = state.pausedLogs ? "Riprendi log" : "Pausa log";
  });
  refresh();
  window.setInterval(refresh, 1000);
});

async function refresh() {
  if (state.inFlight) return;
  state.inFlight = true;
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`Dashboard HTTP ${response.status}`);
    const data = await response.json();
    render(data);
    setConnection(true, data.generated_at);
  } catch (error) {
    setConnection(false);
    showErrors([{ source: "dashboard", message: error.message }]);
  } finally {
    state.inFlight = false;
  }
}

function render(data) {
  const constellation = data.constellation || {};
  const satellites = constellation.satellites || {};
  const heartbeatMap = (data.heartbeats || {}).heartbeats || {};
  const evaluation = (data.scores || {}).evaluation || {};
  const scores = evaluation.scores || {};
  const controllerState = data.controller_state || {};
  const migrations = data.migrations || {};
  const currentController = findController(heartbeatMap, evaluation);

  renderKpis(satellites, heartbeatMap, currentController, migrations);
  renderNetwork(satellites, constellation.distances_km || {}, controllerState.topology || {}, scores, currentController);
  renderSatelliteTable(satellites, heartbeatMap, scores, currentController);
  renderRouting(controllerState.routing_table || {});
  renderMigrations(migrations);
  if (!state.pausedLogs) {
    state.lastLogs = data.logs || [];
    renderLogs(state.lastLogs);
  }
  showErrors(data.errors || []);
}

function renderKpis(satellites, heartbeats, controller, migrations) {
  const ids = Object.keys(satellites);
  const states = ids.map((id) => satellites[id]?.illumination?.state);
  const sunlit = states.filter((value) => value === "sunlight").length;
  const shadow = states.filter((value) => value === "shadow").length;
  const fresh = Object.values(heartbeats).filter((hb) => heartbeatAge(hb) < 15).length;
  const migrationList = migrations.migrations || [];
  const latest = migrations.latest;
  $("onlineCount").textContent = `${fresh} / ${ids.length}`;
  $("controllerCurrent").textContent = controller || "—";
  $("controllerStatus").textContent = controller ? "Controller attivo" : "Non determinato";
  $("sunlightCount").textContent = sunlit;
  $("shadowCount").textContent = `${shadow} in ombra`;
  $("migrationCount").textContent = migrationList.length;
  $("migrationStatus").textContent = latest ? `${latest.mode?.toUpperCase()} · ${latest.status}` : "Nessun evento";
}

function renderNetwork(satellites, distances, topology, scores, controller) {
  const ids = Object.keys(satellites).sort();
  const linksGroup = $("networkLinks");
  const nodesGroup = $("networkNodes");
  linksGroup.replaceChildren();
  nodesGroup.replaceChildren();
  if (!ids.length) return;

  const positions = projectPositions(ids, satellites);
  const topologyLinks = Array.isArray(topology.links) ? topology.links : [];
  const links = topologyLinks.length ? topologyLinks.map((link) => ({ ...link, derived: false })) : deriveLinks(ids, distances);
  links.forEach((link) => {
    const source = positions[link.source];
    const target = positions[link.target];
    if (!source || !target) return;
    const line = svg("line", {
      x1: source.x, y1: source.y, x2: target.x, y2: target.y,
      class: `network-link${link.derived ? " derived" : ""}`,
    });
    linksGroup.appendChild(line);
  });

  ids.forEach((id) => {
    const satellite = satellites[id] || {};
    const point = positions[id];
    const illumination = satellite.illumination?.state === "shadow" ? "shadow" : "sunlit";
    const group = svg("g", { class: `satellite-node ${illumination}`, transform: `translate(${point.x} ${point.y})` });
    group.appendChild(svg("rect", { x: -26, y: -7, width: 16, height: 14, rx: 2, class: "node-wing" }));
    group.appendChild(svg("rect", { x: 10, y: -7, width: 16, height: 14, rx: 2, class: "node-wing" }));
    if (id === controller) group.appendChild(svg("circle", { r: 24, class: "controller-ring" }));
    group.appendChild(svg("circle", { r: 14, class: "node-core" }));
    const label = svg("text", { x: 0, y: 39, "text-anchor": "middle", class: "node-label" });
    label.textContent = id;
    group.appendChild(label);
    const score = svg("text", { x: 0, y: 53, "text-anchor": "middle", class: "node-score" });
    score.textContent = scores[id] ? `score ${formatNumber(scores[id].score, 1)}` : "score —";
    group.appendChild(score);
    const title = svg("title");
    title.textContent = `${id}\n${illumination === "sunlit" ? "In luce" : "In ombra"}\nAltitudine ${formatNumber(satellite.geodetic?.altitude_km, 1)} km`;
    group.appendChild(title);
    nodesGroup.appendChild(group);
  });
}

function projectPositions(ids, satellites) {
  const cx = 500, cy = 220, rx = 270, ry = 155;
  const raw = ids.map((id, index) => {
    const position = satellites[id]?.position_km || {};
    const x = Number(position.x), y = Number(position.y);
    if (Number.isFinite(x) && Number.isFinite(y) && Math.hypot(x, y) > 0) {
      const angle = Math.atan2(y, x);
      return { id, angle };
    }
    return { id, angle: (index / ids.length) * Math.PI * 2 - Math.PI / 2 };
  });
  return Object.fromEntries(raw.map(({ id, angle }) => [id, { x: cx + Math.cos(angle) * rx, y: cy - Math.sin(angle) * ry }]));
}

function deriveLinks(ids, distances) {
  const pairs = new Map();
  ids.forEach((source) => {
    const candidates = Object.entries(distances[source] || {})
      .filter(([target, value]) => target !== source && ids.includes(target) && Number.isFinite(Number(value)))
      .sort((a, b) => Number(a[1]) - Number(b[1]))
      .slice(0, 2);
    candidates.forEach(([target]) => {
      const [a, b] = [source, target].sort();
      pairs.set(`${a}:${b}`, { source: a, target: b, derived: true });
    });
  });
  return [...pairs.values()];
}

function renderSatelliteTable(satellites, heartbeats, scores, controller) {
  const rows = Object.keys(satellites).sort().map((id) => {
    const sat = satellites[id] || {};
    const hb = heartbeats[id] || {};
    const metric = scores[id] || {};
    const age = heartbeatAge(hb);
    const heartbeatClass = age < 15 ? "online" : "stale";
    const heartbeatText = Number.isFinite(age) ? `${Math.round(age)}s fa` : "assente";
    const illumination = sat.illumination?.state || "unknown";
    const position = sat.geodetic || {};
    return `<tr>
      <td><span class="sat-name">${escapeHtml(id)}</span><span class="sat-sub">${escapeHtml(sat.name || "—")}</span></td>
      <td><span class="pill ${id === controller ? "active" : "off"}">${id === controller ? "ATTIVO" : "—"}</span></td>
      <td><span class="pill ${heartbeatClass}">${heartbeatText}</span></td>
      <td>${formatNumber(position.latitude_deg, 2)}°, ${formatNumber(position.longitude_deg, 2)}°<span class="sat-sub">${formatNumber(position.altitude_km, 1)} km</span></td>
      <td><span class="pill ${illumination}">${illumination === "sunlight" ? "☀ LUCE" : illumination === "shadow" ? "◐ OMBRA" : "—"}</span></td>
      <td>${formatDuration(hb.time_to_eclipse ?? sat.illumination?.seconds_until_eclipse)}</td>
      <td>${hb.neighbors ?? metric.N ?? "—"}</td>
      <td>${formatNumber(metric.D, 1)} km</td>
      <td>${formatNumber(hb.cpu ?? metric.L, 0)}%</td>
      <td class="score-value">${formatNumber(metric.score, 2)}</td>
    </tr>`;
  });
  $("satelliteRows").innerHTML = rows.length ? rows.join("") : `<tr><td colspan="10" class="empty-state">Nessun satellite disponibile</td></tr>`;
}

function renderRouting(routingTable) {
  const routes = [];
  Object.entries(routingTable).forEach(([source, destinations]) => {
    Object.entries(destinations || {}).forEach(([destination, route]) => routes.push({ source, destination, ...route }));
  });
  $("routeCount").textContent = `${routes.length} rotte`;
  $("routingRows").innerHTML = routes.length ? routes.map((route) => `<tr>
    <td class="sat-name">${escapeHtml(route.source)}</td><td>${escapeHtml(route.destination)}</td>
    <td>${escapeHtml(route.next_hop || "—")}</td><td>${route.hops ?? "—"}</td>
  </tr>`).join("") : `<tr><td colspan="4" class="empty-state">Nessuna rotta calcolata</td></tr>`;
}

function renderMigrations(migrations) {
  const list = [...(migrations.migrations || [])].reverse();
  $("activeMigration").textContent = migrations.active_migration_id ? "In corso" : "Idle";
  $("migrationEvents").innerHTML = list.length ? list.map((migration) => {
    const metrics = migration.metrics || {};
    return `<article class="migration-event ${migration.status === "failed" ? "failed" : ""}">
      <strong>${escapeHtml((migration.mode || "").toUpperCase())} · ${escapeHtml(migration.source_satellite_id || "—")} → ${escapeHtml(migration.target_satellite_id || "—")}</strong>
      <p>${escapeHtml(migration.status || "—")} · ${formatNumber(metrics.duration_ms, 1)} ms · downtime ${formatNumber(metrics.downtime_ms, 1)} ms · seq ${metrics.final_sequence_number ?? "—"}</p>
    </article>`;
  }).join("") : `<div class="empty-state boxed">Nessuna migrazione registrata</div>`;
}

function renderLogs(logs) {
  $("logStream").innerHTML = logs.length ? logs.map((entry) => `<div class="log-line ${escapeHtml(entry.level || "info")}">
    <span class="log-time">${formatClock(entry.timestamp)}</span>
    <span class="log-source">${escapeHtml(entry.source || "system")}</span>
    <span class="log-message">${escapeHtml(entry.message || "")}</span>
  </div>`).join("") : `<div class="empty-state">Nessun evento disponibile</div>`;
}

function setConnection(connected, timestamp) {
  $("connectionDot").className = `status-dot ${connected ? "" : "error"}`;
  $("connectionLabel").textContent = connected ? "Sistema online" : "Connessione persa";
  $("lastUpdate").textContent = connected ? `Aggiornato ${formatClock(timestamp)}` : "Nuovo tentativo tra un secondo";
}

function showErrors(errors) {
  const banner = $("errorBanner");
  if (!errors.length) { banner.classList.add("hidden"); banner.textContent = ""; return; }
  banner.textContent = errors.map((error) => `${error.source}: ${error.message}`).join(" · ");
  banner.classList.remove("hidden");
}

function findController(heartbeats, evaluation) {
  const reported = Object.entries(heartbeats).filter(([, heartbeat]) => heartbeat.controller).map(([id]) => id);
  return reported.length === 1 ? reported[0] : evaluation.current_controller_satellite_id || null;
}

function heartbeatAge(heartbeat) {
  const timestamp = Date.parse(heartbeat?.received_at || "");
  return Number.isFinite(timestamp) ? (Date.now() - timestamp) / 1000 : Infinity;
}

function formatNumber(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("it-IT", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  return `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`;
}

function formatClock(timestamp) {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("it-IT", { hour12: false });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function svg(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function createStars() {
  const group = document.querySelector(".stars");
  for (let index = 0; index < 55; index += 1) {
    const x = (index * 83 + 31) % 980 + 10;
    const y = (index * 47 + 19) % 410 + 15;
    const radius = index % 7 === 0 ? 1.4 : .75;
    group.appendChild(svg("circle", { cx: x, cy: y, r: radius, fill: "#cbe7ff" }));
  }
}
