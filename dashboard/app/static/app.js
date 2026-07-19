"use strict";

const state = { pausedLogs: false, lastLogs: [], inFlight: false };
const $ = (id) => document.getElementById(id);
const MATERIAL_SATELLITE_ALT_PATH = "M560-32v-80q117 0 198.5-81.5T840-392h80q0 75-28.5 140.5t-77 114q-48.5 48.5-114 77T560-32Zm0-160v-80q50 0 85-35t35-85h80q0 83-58.5 141.5T560-192ZM222-57q-15 0-30-6t-27-17L23-222q-11-12-17-27t-6-30q0-16 6-30.5T23-335l127-127q23-23 57-23.5t57 22.5l50 50 28-28-50-50q-23-23-23-56t23-56l57-57q23-23 56.5-23t56.5 23l50 50 28-28-50-50q-23-23-23-56.5t23-56.5l127-127q12-12 27-18t30-6q15 0 29.5 6t26.5 18l142 142q12 11 17.5 25.5T895-730q0 15-5.5 30T872-673L745-546q-23 23-56.5 23T632-546l-50-50-28 28 50 50q23 23 22.5 56.5T603-405l-56 56q-23 23-56.5 23T434-349l-50-50-28 28 50 50q23 23 22.5 57T405-207L278-80q-11 11-25.5 17T222-57Zm0-79 42-42-142-142-42 42 142 142Zm85-85 42-42-142-142-42 42 142 142Zm184-184 56-56-142-142-56 56 142 142Zm198-198 42-42-142-142-42 42 142 142Zm85-85 42-42-142-142-42 42 142 142ZM448-504Z";

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
  const displayedMigration = selectDisplayedMigration(migrations);

  renderKpis(satellites, heartbeatMap, currentController, migrations);
  renderMigrationRoute(displayedMigration);
  renderNetwork(satellites, constellation.distances_km || {}, controllerState.topology || {}, scores, currentController, displayedMigration);
  renderTransitionTable(satellites);
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

function selectDisplayedMigration(migrations) {
  const list = migrations.migrations || [];
  const activeId = migrations.active_migration_id;
  if (activeId) {
    return list.find((migration) => migration.migration_id === activeId) || migrations.latest || null;
  }
  return migrations.latest || list.at(-1) || null;
}

function renderMigrationRoute(migration) {
  const route = $("migrationRoute");
  if (!migration) {
    route.className = "migration-route idle";
    route.innerHTML = `<span class="migration-route-label">TRASFERIMENTO CONTROLLER</span><strong>Nessun trasferimento registrato</strong>`;
    return;
  }
  const status = String(migration.status || "unknown").toLowerCase();
  const statusClass = ["completed", "failed"].includes(status) ? status : "active";
  const heading = status === "waiting_for_contact"
    ? "ALLINEAMENTO SATELLITI"
    : ["queued", "in_progress"].includes(status)
      ? "TRASFERIMENTO IN CORSO"
      : "ULTIMO TRASFERIMENTO";
  const labels = {
    waiting_for_contact: "IN ALLINEAMENTO",
    queued: "IN CODA",
    in_progress: "IN TRASFERIMENTO",
    completed: "COMPLETATO",
    failed: "FALLITO",
  };
  const contact = migration.contact_window || {};
  const alignment = status === "waiting_for_contact"
    ? `<span class="alignment-progress">${formatNumber(contact.continuous_alignment_seconds, 0)} / ${formatNumber(contact.required_alignment_seconds, 0)} s</span>`
    : "";
  route.className = `migration-route ${statusClass}`;
  route.innerHTML = `
    <span class="migration-route-label">${heading}</span>
    <strong>${escapeHtml(migration.source_satellite_id || "—")} → ${escapeHtml(migration.target_satellite_id || "—")}</strong>
    <span class="migration-mode">${escapeHtml(String(migration.mode || "—").toUpperCase())}</span>
    <span class="migration-state">${escapeHtml(labels[status] || status.toUpperCase())}</span>
    ${alignment}`;
}

function renderNetwork(satellites, distances, topology, scores, controller, migration) {
  const ids = Object.keys(satellites).sort(compareSatelliteIds);
  const linksGroup = $("networkLinks");
  const migrationGroup = $("migrationTransfer");
  const nodesGroup = $("networkNodes");
  linksGroup.replaceChildren();
  migrationGroup.replaceChildren();
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

  renderMigrationTransfer(migrationGroup, migration, positions);

  ids.forEach((id) => {
    const satellite = satellites[id] || {};
    const point = positions[id];
    const illumination = satellite.illumination?.state === "shadow" ? "shadow" : "sunlit";
    const isMigrationSource = id === migration?.source_satellite_id;
    const isMigrationTarget = id === migration?.target_satellite_id;
    const migrationRoles = `${isMigrationSource ? " migration-source" : ""}${isMigrationTarget ? " migration-target" : ""}`;
    const group = svg("g", { class: `satellite-node ${illumination}${migrationRoles}`, transform: `translate(${point.x} ${point.y})` });
    if (id === controller) group.appendChild(svg("circle", { r: 20, class: "controller-ring" }));
    if (isMigrationSource) group.appendChild(svg("circle", { r: 24, class: "migration-source-ring" }));
    if (isMigrationTarget) group.appendChild(svg("circle", { r: 24, class: "migration-target-ring" }));
    const icon = svg("svg", {
      x: -16, y: -16, width: 32, height: 32,
      viewBox: "0 -960 960 960", class: "material-satellite-icon",
      "aria-hidden": "true",
    });
    icon.appendChild(svg("path", { d: MATERIAL_SATELLITE_ALT_PATH }));
    group.appendChild(icon);
    const label = svg("text", { x: 0, y: 31, "text-anchor": "middle", class: "node-label" });
    label.textContent = id;
    group.appendChild(label);
    const score = svg("text", { x: 0, y: 45, "text-anchor": "middle", class: "node-score" });
    score.textContent = scores[id] ? `score ${formatNumber(scores[id].score, 1)}` : "score —";
    group.appendChild(score);
    if (isMigrationSource || isMigrationTarget) {
      const role = svg("text", { x: 0, y: -27, "text-anchor": "middle", class: "migration-node-tag" });
      role.textContent = isMigrationSource ? "SRC" : "DST";
      group.appendChild(role);
    }
    const title = svg("title");
    title.textContent = `${id}\n${illumination === "sunlit" ? "In luce" : "In ombra"}\nAltitudine ${formatNumber(satellite.geodetic?.altitude_km, 1)} km`;
    group.appendChild(title);
    nodesGroup.appendChild(group);
  });
}

function renderMigrationTransfer(group, migration, positions) {
  if (!migration) return;
  const source = positions[migration.source_satellite_id];
  const target = positions[migration.target_satellite_id];
  if (!source || !target) return;
  const segment = insetSegment(source, target, 30);
  const statusClass = migration.status === "waiting_for_contact"
    ? " aligning"
    : migration.status === "completed"
      ? " completed"
      : migration.status === "failed"
        ? " failed"
        : "";
  group.appendChild(svg("line", {
    x1: segment.x1, y1: segment.y1, x2: segment.x2, y2: segment.y2,
    class: `migration-transfer-line${statusClass}`,
  }));
  const label = svg("text", {
    x: (source.x + target.x) / 2,
    y: (source.y + target.y) / 2 - 10,
    "text-anchor": "middle",
    class: "migration-transfer-label",
  });
  const contact = migration.contact_window || {};
  label.textContent = migration.status === "waiting_for_contact"
    ? `ALIGN ${formatNumber(contact.continuous_alignment_seconds, 0)}/${formatNumber(contact.required_alignment_seconds, 0)}s`
    : `${String(migration.mode || "").toUpperCase()} · CONTROLLER`;
  group.appendChild(label);
}

function insetSegment(source, target, inset) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  return {
    x1: source.x + ux * inset,
    y1: source.y + uy * inset,
    x2: target.x - ux * inset,
    y2: target.y - uy * inset,
  };
}

function projectPositions(ids, satellites) {
  const raw = ids.map((id, index) => {
    const position = satellites[id]?.position_km || {};
    const projected = projectVector(position);
    return { id, angle: projected?.angle ?? (index / ids.length) * Math.PI * 2 - Math.PI / 2 };
  });
  return Object.fromEntries(raw.map(({ id, angle }) => [id, pointOnOrbit(angle)]));
}

function renderTransitionTable(satellites) {
  const rows = Object.keys(satellites).sort(compareSatelliteIds).map((id) => {
    const illumination = satellites[id]?.illumination || {};
    const isSunlit = illumination.state === "sunlight";
    const isShadow = illumination.state === "shadow";
    const rawSeconds = isSunlit ? illumination.seconds_until_eclipse : illumination.seconds_until_sunlight;
    const seconds = rawSeconds === null || rawSeconds === undefined ? Number.NaN : Number(rawSeconds);
    const knownTransition = Number.isFinite(seconds) && seconds >= 0;
    const transitionAt = isSunlit ? illumination.next_eclipse_at : illumination.next_sunlight_at;
    const stateLabel = isSunlit ? "LUCE" : isShadow ? "OMBRA" : "—";
    const nextLabel = isSunlit ? "OMBRA" : isShadow ? "LUCE" : "—";
    const stateClass = isSunlit ? "sunlight" : isShadow ? "shadow" : "";
    const urgencyClass = knownTransition && seconds < 300 ? " urgent" : "";
    return `<tr>
      <td class="sat-name">${escapeHtml(id)}</td>
      <td><span class="transition-state ${stateClass}">${stateLabel}</span></td>
      <td class="transition-next">→ ${nextLabel}</td>
      <td class="transition-countdown${urgencyClass}">${knownTransition ? formatDuration(seconds) : "—"}</td>
      <td class="transition-clock">${formatTransitionClock(transitionAt)}</td>
    </tr>`;
  });
  $("transitionRows").innerHTML = rows.length ? rows.join("") : `<tr><td colspan="5" class="empty-state">Nessuna previsione disponibile</td></tr>`;
}

function projectVector(position) {
  const x = Number(position?.x), y = Number(position?.y);
  if (!Number.isFinite(x) || !Number.isFinite(y) || Math.hypot(x, y) === 0) return null;
  return { angle: Math.atan2(y, x) };
}

function pointOnOrbit(angle) {
  return { x: 500 + Math.cos(angle) * 270, y: 220 - Math.sin(angle) * 155 };
}

function deriveLinks(ids, distances) {
  const pairs = new Map();
  ids.forEach((source) => {
    const candidates = Object.entries(distances[source] || {})
      .filter(([target, value]) => target !== source && ids.includes(target) && Number.isFinite(Number(value)))
      .sort((a, b) => Number(a[1]) - Number(b[1]))
      .slice(0, 2);
    candidates.forEach(([target]) => {
      const [a, b] = [source, target].sort(compareSatelliteIds);
      pairs.set(`${a}:${b}`, { source: a, target: b, derived: true });
    });
  });
  return [...pairs.values()];
}

function renderSatelliteTable(satellites, heartbeats, scores, controller) {
  const rows = Object.keys(satellites).sort(compareSatelliteIds).map((id) => {
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
  const pending = list.find((migration) => ["waiting_for_contact", "queued", "in_progress"].includes(migration.status));
  $("activeMigration").textContent = pending ? "In corso" : "Idle";
  $("migrationEvents").innerHTML = list.length ? list.map((migration) => {
    const metrics = migration.metrics || {};
    const contact = migration.contact_window || {};
    const alignment = migration.status === "waiting_for_contact"
      ? ` · allineamento ${formatNumber(contact.continuous_alignment_seconds, 0)}/${formatNumber(contact.required_alignment_seconds, 0)}s · ${escapeHtml(contact.reason || "—")}`
      : "";
    return `<article class="migration-event ${migration.status === "failed" ? "failed" : ""}">
      <strong>${escapeHtml((migration.mode || "").toUpperCase())} · ${escapeHtml(migration.source_satellite_id || "—")} → ${escapeHtml(migration.target_satellite_id || "—")}</strong>
      <p>${escapeHtml(migration.status || "—")}${alignment} · ${formatNumber(metrics.duration_ms, 1)} ms · downtime ${formatNumber(metrics.downtime_ms, 1)} ms · seq ${metrics.final_sequence_number ?? "—"}</p>
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

function compareSatelliteIds(left, right) {
  const leftNumber = Number(String(left).match(/\d+$/)?.[0]);
  const rightNumber = Number(String(right).match(/\d+$/)?.[0]);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber || String(left).localeCompare(String(right));
  }
  return String(left).localeCompare(String(right));
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

function formatTransitionClock(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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
