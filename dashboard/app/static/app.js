"use strict";

const state = { pausedLogs: false, lastLogs: [], inFlight: false, experimentStatus: null };
const $ = (id) => document.getElementById(id);
const ACTIVE_MIGRATION_STATUSES = new Set(["waiting_for_contact", "queued", "in_progress"]);
const MATERIAL_SATELLITE_ALT_PATH = "M560-32v-80q117 0 198.5-81.5T840-392h80q0 75-28.5 140.5t-77 114q-48.5 48.5-114 77T560-32Zm0-160v-80q50 0 85-35t35-85h80q0 83-58.5 141.5T560-192ZM222-57q-15 0-30-6t-27-17L23-222q-11-12-17-27t-6-30q0-16 6-30.5T23-335l127-127q23-23 57-23.5t57 22.5l50 50 28-28-50-50q-23-23-23-56t23-56l57-57q23-23 56.5-23t56.5 23l50 50 28-28-50-50q-23-23-23-56.5t23-56.5l127-127q12-12 27-18t30-6q15 0 29.5 6t26.5 18l142 142q12 11 17.5 25.5T895-730q0 15-5.5 30T872-673L745-546q-23 23-56.5 23T632-546l-50-50-28 28 50 50q23 23 22.5 56.5T603-405l-56 56q-23 23-56.5 23T434-349l-50-50-28 28 50 50q23 23 22.5 57T405-207L278-80q-11 11-25.5 17T222-57Zm0-79 42-42-142-142-42 42 142 142Zm85-85 42-42-142-142-42 42 142 142Zm184-184 56-56-142-142-56 56 142 142Zm198-198 42-42-142-142-42 42 142 142Zm85-85 42-42-142-142-42 42 142 142ZM448-504Z";

document.addEventListener("DOMContentLoaded", () => {
  createStars();
  $("pauseLogs").addEventListener("click", () => {
    state.pausedLogs = !state.pausedLogs;
    $("pauseLogs").textContent = state.pausedLogs ? "Riprendi log" : "Pausa log";
  });
  $("experimentForm").addEventListener("submit", startExperiment);
  $("newSimulationButton").addEventListener("click", resetExperiment);
  $("closeExportPreview").addEventListener("click", closeExportPreview);
  $("exportPreviewModal").addEventListener("click", (event) => {
    if (event.target === $("exportPreviewModal")) closeExportPreview();
  });
  refresh();
  window.setInterval(refresh, 500);
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
  const startupController = data.startup_controller || {};
  const migrations = data.migrations || {};
  renderExperiment(data.experiment || {});
  renderExports(data.exports || []);
  const currentController = findController(
    heartbeatMap,
    evaluation,
    controllerState,
    startupController,
  );
  const displayedMigration = selectDisplayedMigration(migrations);
  const networkMigration = ACTIVE_MIGRATION_STATUSES.has(displayedMigration?.status)
    ? displayedMigration
    : null;

  renderKpis(satellites, heartbeatMap, currentController, migrations);
  renderMigrationRoute(displayedMigration, evaluation);
  renderNetwork(satellites, constellation.distances_km || {}, controllerState.topology || {}, scores, currentController, networkMigration);
  renderMigrationTimeline(displayedMigration, satellites);
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

function renderExperiment(experiment) {
  const status = experiment.status || "awaiting_configuration";
  state.experimentStatus = status;
  const labels = {
    awaiting_configuration: "Da configurare",
    running: "In esecuzione",
    completed: "Completata · clock fermo",
  };
  $("experimentMode").textContent = experiment.mode ? String(experiment.mode).toUpperCase() : "In attesa";
  $("experimentProgress").textContent = `${experiment.completed_migrations || 0} / ${experiment.migration_limit || "—"} migrazioni`;
  $("experimentStatus").textContent = labels[status] || status;
  $("experimentExports").textContent = (experiment.exports || []).join(" · ") || "—";
  $("experimentModal").classList.toggle("hidden", status !== "awaiting_configuration");
}

function renderExports(exports) {
  $("exportCount").textContent = `${exports.length} ${exports.length === 1 ? "file" : "file"}`;
  $("exportRows").innerHTML = exports.length
    ? exports.map((item) => {
      const filename = String(item.filename || "");
      const url = `/exports/${encodeURIComponent(filename)}`;
      return `<tr>
        <td class="export-filename">${escapeHtml(filename)}</td>
        <td><span class="pill export-format">${escapeHtml(item.format || "—")}</span></td>
        <td>${escapeHtml(formatFullTimestamp(item.created_at))}</td>
        <td>${escapeHtml(formatFileSize(item.size_bytes))}</td>
        <td><div class="export-actions">
          <button class="ghost-button export-preview-button" type="button" data-export="${escapeHtml(filename)}">Visualizza</button>
          <a class="ghost-button export-download-button" href="${url}?download=1">Scarica</a>
        </div></td>
      </tr>`;
    }).join("")
    : '<tr><td colspan="5" class="empty-state">Nessun export disponibile</td></tr>';
  document.querySelectorAll(".export-preview-button").forEach((button) => {
    button.addEventListener("click", () => previewExport(button.dataset.export));
  });
}

async function previewExport(filename) {
  const modal = $("exportPreviewModal");
  const title = $("exportPreviewTitle");
  const content = $("exportPreviewContent");
  title.textContent = filename;
  modal.classList.remove("hidden");
  const url = `/exports/${encodeURIComponent(filename)}`;
  if (filename.toLowerCase().endsWith(".pdf")) {
    content.innerHTML = `<iframe class="export-pdf-frame" title="Anteprima ${escapeHtml(filename)}" src="${url}"></iframe>`;
    return;
  }
  content.textContent = "Caricamento…";
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const raw = await response.text();
    try {
      content.textContent = JSON.stringify(JSON.parse(raw), null, 2);
    } catch (_) {
      content.textContent = raw;
    }
  } catch (error) {
    content.textContent = `Impossibile caricare l'export: ${error.message}`;
  }
}

function closeExportPreview() {
  $("exportPreviewModal").classList.add("hidden");
  $("exportPreviewContent").textContent = "";
}

function formatFileSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
}

async function startExperiment(event) {
  event.preventDefault();
  const button = $("startExperimentButton");
  const errorBox = $("experimentFormError");
  const mode = document.querySelector('input[name="migrationMode"]:checked')?.value;
  const migrationLimit = Number.parseInt($("migrationLimit").value, 10);
  button.disabled = true;
  errorBox.classList.add("hidden");
  try {
    const response = await fetch("/api/experiment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, migration_limit: migrationLimit }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || `HTTP ${response.status}`);
    renderExperiment(payload);
    await refresh();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
}

async function resetExperiment() {
  if (
    state.experimentStatus === "running"
    && !window.confirm("Interrompere la simulazione corrente e tornare allo scenario iniziale?")
  ) return;
  const button = $("newSimulationButton");
  button.disabled = true;
  try {
    const response = await fetch("/api/experiment/reset", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || `HTTP ${response.status}`);
    renderExperiment(payload);
    await refresh();
  } catch (error) {
    showErrors([{ source: "experiment", message: error.message }]);
  } finally {
    button.disabled = false;
  }
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

function renderMigrationRoute(migration, evaluation = {}) {
  const route = $("migrationRoute");
  if (!migration) {
    route.className = "migration-route idle";
    route.innerHTML = `<span class="migration-route-label">TRASFERIMENTO CONTROLLER</span><strong>Nessun trasferimento registrato</strong><p class="migration-reason">La motivazione della selezione apparirà quando verrà scelto un satellite destinazione.</p>`;
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
  const selectionReason = describeMigrationSelection(migration, evaluation);
  const failureReason = status === "failed" ? describeMigrationFailure(migration) : "";
  route.className = `migration-route ${statusClass}`;
  route.innerHTML = `
    <span class="migration-route-label">${heading}</span>
    <strong>${escapeHtml(migration.source_satellite_id || "—")} → ${escapeHtml(migration.target_satellite_id || "—")}</strong>
    <span class="migration-mode">${escapeHtml(String(migration.mode || "—").toUpperCase())}</span>
    <span class="migration-state">${escapeHtml(labels[status] || status.toUpperCase())}</span>
      ${alignment}
      <p class="migration-reason">${escapeHtml(selectionReason)}</p>
      ${failureReason ? `<p class="migration-failure"><strong>MOTIVO DEL FALLIMENTO</strong> ${escapeHtml(failureReason)}</p>` : ""}`;
}

function describeMigrationFailure(migration) {
  if (migration.error) return String(migration.error);
  const failedEvent = [...(migration.events || [])]
    .reverse()
    .find((event) => event.name === "migration_failed" || event.error);
  if (failedEvent?.error) return String(failedEvent.error);
  const failedStep = [...(migration.metrics?.steps || [])]
    .reverse()
    .find((step) => step.status === "failed");
  if (failedStep) return stepResultDetail(failedStep);
  return "La migrazione non è stata completata; non è disponibile un dettaglio tecnico.";
}

function describeMigrationSelection(migration, evaluation = {}) {
  const recommendation = migration.recommendation || {};
  const target = migration.target_satellite_id || "Il satellite destinazione";
  const source = migration.source_satellite_id || "il controller corrente";

  if (recommendation.source === "manual_api") {
    return "Trasferimento avviato manualmente: la destinazione non è stata scelta dallo scorer.";
  }

  if (["controller_eclipse_approaching", "controller_in_eclipse_recovery"].includes(recommendation.reason)) {
    const details = [];
    const targetScore = Number(recommendation.target_score);
    const sourceScore = Number(recommendation.source_score);
    if (Number.isFinite(targetScore) && Number.isFinite(sourceScore)) {
      const scoreDifference = targetScore - sourceScore;
      details.push(`score ${formatNumber(targetScore, 1)} contro ${formatNumber(sourceScore, 1)} (${scoreDifference >= 0 ? "+" : ""}${formatNumber(scoreDifference, 1)})`);
    }

    const timeToEclipse = Number(recommendation.target_time_to_eclipse_seconds);
    if (Number.isFinite(timeToEclipse)) {
      details.push(`${formatDuration(timeToEclipse)} di luce residua`);
    }

    const contact = recommendation.contact || {};
    const distance = Number(contact.distance_km);
    if (Number.isFinite(distance)) {
      const visibility = contact.line_of_sight ? "linea di vista libera" : "linea di vista verificata";
      details.push(`collegamento fisico valido a ${formatNumber(distance, 0)} km, ${visibility}`);
    }

    const context = recommendation.reason === "controller_in_eclipse_recovery"
      ? `${source} è già in ombra: recupero d'emergenza verso ${target}`
      : `${target} è stato scelto dallo scorer rispetto a ${source}`;
    return `${context}${details.length ? `: ${details.join("; ")}.` : "."}`;
  }

  if (evaluation.selected_satellite_id === migration.target_satellite_id) {
    return `${target} è il candidato con lo score più alto tra i satelliti fisicamente raggiungibili dal controller corrente.`;
  }

  return `${target} è stato selezionato come destinazione del trasferimento del Controller.`;
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
  const phase = migrationTransferPhase(migration);
  const statusClass = phase.kind === "alignment"
    ? " aligning"
    : phase.kind === "final-update"
      ? " updating"
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
  label.textContent = phase.label;
  group.appendChild(label);
}

function migrationTransferPhase(migration) {
  const contact = migration.contact_window || {};
  const isCold = String(migration.mode || "").toLowerCase() === "cold";
  if (migration.status === "waiting_for_contact" && !contact.channel_established) {
    return {
      kind: "alignment",
      label: `ALIGN ${formatNumber(contact.continuous_alignment_seconds, 0)}/${formatNumber(contact.required_alignment_seconds, 0)}s`,
    };
  }
  if (migration.status === "queued") {
    return { kind: "ready", label: "CANALE STABILITO" };
  }

  const steps = migration.metrics?.steps || [];
  const activeStep = [...steps].reverse().find((step) => step.status === "in_progress");
  if (migration.status === "in_progress") {
    if (activeStep?.name === "transfer_complete_state_and_wait_target_ack") {
      return { kind: "transfer", label: "MIGRATION" };
    }
    if (activeStep?.name === "transfer_final_state_and_wait_target_ack") {
      return { kind: "final-update", label: "UPDATE FINALE → TARGET" };
    }
    if (activeStep?.name === "final_checkpoint") {
      return { kind: "final-update", label: "CREAZIONE UPDATE FINALE" };
    }
    if (["request_source_migration", "ensure_target_passive", "transfer_initial_state_to_target", "initial_checkpoint"].includes(activeStep?.name)) {
      return { kind: "transfer", label: "CHECKPOINT INIZIALE → TARGET" };
    }
    if (["stop_source_controller", "transfer_state_and_wait_ack", "start_target_controller", "update_controller_host"].includes(activeStep?.name)) {
      return { kind: "cutover", label: isCold ? "ATTIVAZIONE TARGET" : "CUTOVER CONTROLLER" };
    }
    const finalTransfer = [...steps].reverse().find(
      (step) => step.name === "transfer_final_state_and_wait_target_ack",
    );
    if (finalTransfer?.status === "ok") {
      return { kind: "cutover", label: "ACK UPDATE RICEVUTO · CUTOVER" };
    }
    return { kind: "transfer", label: isCold ? "MIGRATION" : "HOT · TRASFERIMENTO" };
  }
  if (migration.status === "completed") return { kind: "completed", label: "CONTROLLER TRASFERITO" };
  if (migration.status === "failed") return { kind: "failed", label: "TRASFERIMENTO FALLITO" };
  return { kind: "idle", label: `${String(migration.mode || "").toUpperCase()} · CONTROLLER` };
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

function renderMigrationTimeline(migration, satellites = {}) {
  const container = $("migrationTimeline");
  const summary = $("migrationTimelineSummary");
  const status = $("migrationTimelineStatus");
  if (!migration) {
    status.textContent = "Nessuna migrazione";
    summary.classList.add("hidden");
    summary.replaceChildren();
    container.innerHTML = `<div class="empty-state boxed">La timeline apparirà quando verrà selezionato un satellite target</div>`;
    return;
  }

  const labels = migrationStatusLabels();
  const contact = migration.contact_window || {};
  const metrics = migration.metrics || {};
  const activeStep = [...(metrics.steps || [])].reverse().find((step) => step.status === "in_progress");
  status.textContent = activeStep
    ? `In corso · ${migrationStepDefinition(activeStep.name).title}`
    : labels[migration.status] || migration.status || "—";
  const sourceEclipse = Number(
    satellites[migration.source_satellite_id]?.illumination?.seconds_until_eclipse,
  );
  const requiredAlignment = Number(contact.required_alignment_seconds) || 0;
  const completedAlignment = Number(contact.continuous_alignment_seconds) || 0;
  const remainingAlignment = Math.max(0, requiredAlignment - completedAlignment);
  const expectedMargin = Number.isFinite(sourceEclipse)
    ? sourceEclipse - remainingAlignment
    : Number.NaN;
  summary.classList.remove("hidden");
  summary.innerHTML = [
    ["Percorso", `${migration.source_satellite_id || "—"} → ${migration.target_satellite_id || "—"}`],
    ["Modalità", String(migration.mode || "—").toUpperCase()],
    ["Allineamento", `${formatNumber(contact.continuous_alignment_seconds, 0)} / ${formatNumber(contact.required_alignment_seconds, 0)} s`],
    ["Ombra sorgente", formatDuration(sourceEclipse)],
    ["Margine previsto", formatDuration(expectedMargin)],
    ["Handover", metrics.duration_ms == null ? "—" : `${formatNumber(metrics.duration_ms, 1)} ms`],
  ].map(([label, value]) => `<div class="timeline-summary-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");

  const entries = buildMigrationTimeline(migration);
  container.innerHTML = entries.length
    ? entries.map((entry) => renderTimelineItem(entry, migration.created_at)).join("")
    : `<div class="empty-state boxed">Nessuna fase registrata</div>`;
}

function buildMigrationTimeline(migration) {
  const entries = [];
  const terminalEvents = [];
  let order = 0;
  const add = (timestamp, kind, badge, title, detail = "") => {
    if (!timestamp) return;
    entries.push({ timestamp, kind, badge, title, detail, order: order++ });
  };

  (migration.events || []).forEach((event) => {
    if (["migration_completed", "migration_failed"].includes(event.name)) {
      terminalEvents.push(event);
      return;
    }
    const route = `${migration.source_satellite_id || "—"} → ${migration.target_satellite_id || "—"}`;
    const definitions = {
      target_selected: ["default", "SELECT", "Satellite target selezionato", route],
      contact_alignment_started: ["contact", "ALIGN", "Inizio allineamento", `Distanza ${formatNumber(event.distance_km, 1)} km`],
      contact_alignment_reset: ["failed", "RESET", "Allineamento interrotto", `${event.reason || "contatto perso"} · distanza ${formatNumber(event.distance_km, 1)} km`],
      contact_window_ready: ["contact", "READY", "Contact window completata", `${formatNumber(event.continuous_alignment_seconds, 0)} secondi continui`],
      delta_channel_reused: ["send", "CHANNEL", "Canale esistente riutilizzato per il delta", "Nessun secondo allineamento richiesto"],
      migration_started: ["default", "START", `Avvio ${String(event.mode || migration.mode || "").toUpperCase()} Migration`, route],
      migration_completed: ["complete", "DONE", "Migrazione completata", `Controller attivo su ${migration.target_satellite_id || "—"}`],
      migration_failed: ["failed", "ERROR", "Migrazione fallita", event.error || migration.error || "Errore non specificato"],
    };
    const definition = definitions[event.name];
    if (definition) add(event.timestamp, ...definition);
  });

  (migration.metrics?.steps || []).forEach((step) => {
    const startedAt = step.started_at || step.timestamp;
    const completedAt = step.completed_at || step.timestamp;
    const inProgress = step.status === "in_progress";
    if (step.name === "transfer_final_state_and_wait_target_ack") {
      add(startedAt, "send", "SEND", "Invio final state al target", `${migration.source_satellite_id || "—"} → ${migration.target_satellite_id || "—"} · seq ${migration.metrics?.final_sequence_number ?? "—"}${inProgress ? " · trasferimento in corso" : ""}`);
      if (!inProgress) add(completedAt, step.status === "ok" ? "ack" : "failed", step.status === "ok" ? "ACK" : "NO ACK", step.status === "ok" ? "ACK target ricevuto" : "ACK target non ricevuto", stepResultDetail(step));
      return;
    }
    if (step.name === "transfer_complete_state_and_wait_target_ack") {
      add(startedAt, "send", "SEND", "Migrazione completa del Controller", `${migration.source_satellite_id || "—"} → ${migration.target_satellite_id || "—"} · seq ${migration.metrics?.final_sequence_number ?? "—"}${inProgress ? " · trasferimento in corso" : ""}`);
      if (!inProgress) add(completedAt, step.status === "ok" ? "ack" : "failed", step.status === "ok" ? "ACK" : "NO ACK", step.status === "ok" ? "ACK del satellite target ricevuto" : "ACK del satellite target non ricevuto", stepResultDetail(step));
      return;
    }
    if (step.name === "transfer_state_and_wait_ack") {
      add(startedAt, "send", "SEND", "Invio stato al Controller", `Restore sequence ${migration.metrics?.final_sequence_number ?? "—"}${inProgress ? " · restore in corso" : ""}`);
      if (!inProgress) add(completedAt, step.status === "ok" ? "ack" : "failed", step.status === "ok" ? "ACK" : "NO ACK", step.status === "ok" ? "ACK restore ricevuto" : "ACK restore non ricevuto", stepResultDetail(step));
      return;
    }
    const definition = migrationStepDefinition(step.name);
    add(
      inProgress ? startedAt : completedAt,
      step.status === "failed" ? "failed" : definition.kind,
      inProgress ? "LIVE" : definition.badge,
      inProgress ? `${definition.title} in corso` : definition.title,
      stepResultDetail(step),
    );
  });

  terminalEvents.forEach((event) => {
    if (event.name === "migration_completed") {
      add(event.timestamp, "complete", "DONE", "Migrazione completata", `Controller attivo su ${migration.target_satellite_id || "—"}`);
    } else {
      add(event.timestamp, "failed", "ERROR", "Migrazione fallita", event.error || migration.error || "Errore non specificato");
    }
  });

  if (migration.status === "waiting_for_contact") {
    const contact = migration.contact_window || {};
    add(
      contact.last_observed_at || migration.created_at,
      "contact",
      "LIVE",
      `Allineamento ${formatNumber(contact.continuous_alignment_seconds, 0)} / ${formatNumber(contact.required_alignment_seconds, 0)} s`,
      `${contact.reason || "in attesa"} · distanza ${formatNumber(contact.current_distance_km, 1)} km`,
    );
  }

  return entries.sort((left, right) => {
    const delta = Date.parse(left.timestamp) - Date.parse(right.timestamp);
    return Number.isFinite(delta) && delta !== 0 ? delta : left.order - right.order;
  });
}

function migrationStepDefinition(name) {
  const definitions = {
    initial_checkpoint: { kind: "default", badge: "STATE", title: "Checkpoint iniziale acquisito" },
    final_checkpoint: { kind: "default", badge: "DELTA", title: "Checkpoint finale / delta acquisito" },
    cold_final_checkpoint: { kind: "default", badge: "STATE", title: "Checkpoint definitivo acquisito" },
    request_source_migration: { kind: "send", badge: "REQUEST", title: "Migrazione richiesta dal Controller sorgente" },
    ensure_target_passive: { kind: "default", badge: "PASSIVE", title: "Controller disattivato sul target" },
    transfer_initial_state_to_target: { kind: "send", badge: "PREP", title: "Stato iniziale trasferito al target passivo" },
    prepare_target_for_cold_migration: { kind: "default", badge: "PREP", title: "Target predisposto per la Cold migration" },
    quiesce_source_controller: { kind: "default", badge: "FREEZE", title: "Controller sorgente in quiescenza" },
    stop_source_controller: { kind: "default", badge: "STOP", title: "Controller sorgente arrestato" },
    shutdown_controller: { kind: "default", badge: "DOWN", title: "Microservizio Controller disattivato" },
    start_target_controller: { kind: "complete", badge: "START", title: "Controller avviato sul target" },
    update_controller_host: { kind: "complete", badge: "HOST", title: "Host logico del Controller aggiornato" },
    rollback_stop_target: { kind: "failed", badge: "ROLLBACK", title: "Rollback: arresto target" },
    rollback_restore_controller: { kind: "failed", badge: "ROLLBACK", title: "Rollback: ripristino Controller" },
    rollback_resume_source: { kind: "failed", badge: "ROLLBACK", title: "Rollback: ripresa sorgente" },
    rollback_start_source: { kind: "failed", badge: "ROLLBACK", title: "Rollback: riavvio sorgente" },
  };
  return definitions[name] || {
    kind: "default",
    badge: "STEP",
    title: String(name || "fase").replaceAll("_", " "),
  };
}

function stepResultDetail(step) {
  if (step.status === "in_progress") {
    return `Richiesta REST in corso · tentativo ${Math.max(1, Number(step.attempts) || 1)}`;
  }
  const status = step.http_status == null ? "HTTP —" : `HTTP ${step.http_status}`;
  const duration = `${formatNumber(step.duration_ms, 1)} ms`;
  const attemptCount = Number(step.attempts) || 1;
  const attempts = `${attemptCount} tentativ${attemptCount === 1 ? "o" : "i"}`;
  return `${status} · ${duration} · ${attempts}${step.error ? ` · ${step.error}` : ""}`;
}

function renderTimelineItem(entry, origin) {
  return `<article class="timeline-item ${escapeHtml(entry.kind)}">
    <time class="timeline-time" datetime="${escapeHtml(entry.timestamp)}" title="${escapeHtml(formatFullTimestamp(entry.timestamp))}">
      ${escapeHtml(formatTimelineTime(entry.timestamp))}
      <small>${escapeHtml(formatTimelineDate(entry.timestamp))}</small>
    </time>
    <div class="timeline-rail"><span class="timeline-dot"></span></div>
    <div class="timeline-card">
      <div class="timeline-card-header">
        <span class="timeline-badge">${escapeHtml(entry.badge)}</span>
        <strong>${escapeHtml(entry.title)}</strong>
        <span class="timeline-relative">${escapeHtml(formatRelativeTime(entry.timestamp, origin))}</span>
      </div>
      ${entry.detail ? `<p>${escapeHtml(entry.detail)}</p>` : ""}
    </div>
  </article>`;
}

function migrationStatusLabels() {
  return {
    waiting_for_contact: "Allineamento",
    queued: "In coda",
    in_progress: "Migrazione in corso",
    completed: "Completata",
    failed: "Fallita",
  };
}

function projectPositions(ids, satellites) {
  const raw = ids.map((id, index) => {
    const position = satellites[id]?.position_km || {};
    const projected = projectVector(position);
    return { id, angle: projected?.angle ?? (index / ids.length) * Math.PI * 2 - Math.PI / 2 };
  });
  const separated = spreadProjectedAngles(raw, 0.22);
  return Object.fromEntries(separated.map(({ id, angle }) => [id, pointOnOrbit(angle)]));
}

function spreadProjectedAngles(nodes, minimumGap) {
  if (nodes.length < 2) return nodes;
  const circle = Math.PI * 2;
  const sorted = nodes
    .map((node) => ({ ...node, angle: ((node.angle % circle) + circle) % circle }))
    .sort((left, right) => left.angle - right.angle);
  const gaps = sorted.map((node, index) => {
    const next = sorted[(index + 1) % sorted.length];
    return (next.angle + (index === sorted.length - 1 ? circle : 0)) - node.angle;
  });
  const cutAfter = gaps.indexOf(Math.max(...gaps));
  const ordered = [];
  for (let offset = 1; offset <= sorted.length; offset += 1) {
    const index = (cutAfter + offset) % sorted.length;
    const angle = sorted[index].angle + (index <= cutAfter ? circle : 0);
    ordered.push({ ...sorted[index], originalAngle: angle });
  }
  for (let index = 1; index < ordered.length; index += 1) {
    ordered[index].angle = Math.max(
      ordered[index].originalAngle,
      ordered[index - 1].angle + minimumGap,
    );
  }
  const originalCenter = ordered.reduce((sum, node) => sum + node.originalAngle, 0) / ordered.length;
  const adjustedCenter = ordered.reduce((sum, node) => sum + node.angle, 0) / ordered.length;
  const correction = originalCenter - adjustedCenter;
  return ordered.map(({ id, angle }) => ({ id, angle: angle + correction }));
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
    const failure = migration.status === "failed"
      ? `<p class="migration-event-error"><strong>Motivo:</strong> ${escapeHtml(describeMigrationFailure(migration))}</p>`
      : "";
    return `<article class="migration-event ${migration.status === "failed" ? "failed" : ""}">
      <strong>${escapeHtml((migration.mode || "").toUpperCase())} · ${escapeHtml(migration.source_satellite_id || "—")} → ${escapeHtml(migration.target_satellite_id || "—")}</strong>
      <p>${escapeHtml(migration.status || "—")}${alignment} · ${formatNumber(metrics.duration_ms, 1)} ms · downtime ${formatNumber(metrics.downtime_ms, 1)} ms · seq ${metrics.final_sequence_number ?? "—"}</p>
      ${failure}
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

function findController(heartbeats, evaluation, controllerState = {}, startupController = {}) {
  const controllerHost = controllerState.host_satellite_id;
  if (controllerHost && controllerHost !== "UNASSIGNED") return controllerHost;
  const reported = Object.entries(heartbeats).filter(([, heartbeat]) => heartbeat.controller).map(([id]) => id);
  if (reported.length === 1) return reported[0];
  return evaluation.current_controller_satellite_id
    || (startupController.status === "active" ? startupController.selected_satellite_id : null)
    || null;
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

function formatTimelineTime(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  const clock = date.toLocaleTimeString("it-IT", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  return `${clock}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}

function formatTimelineDate(timestamp) {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function formatFullTimestamp(timestamp) {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("it-IT");
}

function formatRelativeTime(timestamp, origin) {
  const delta = Date.parse(timestamp) - Date.parse(origin);
  if (!Number.isFinite(delta)) return "—";
  const sign = delta < 0 ? "−" : "+";
  const absoluteSeconds = Math.abs(delta) / 1000;
  const minutes = Math.floor(absoluteSeconds / 60);
  const seconds = absoluteSeconds - minutes * 60;
  return minutes
    ? `${sign}${minutes}m ${seconds.toFixed(3)}s`
    : `${sign}${seconds.toFixed(3)}s`;
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
