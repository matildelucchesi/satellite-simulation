"""Generazione del report PDF conclusivo di un esperimento."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def write_metrics_report(
    output_path: str | Path,
    metrics: dict[str, Any],
    migrations: list[dict[str, Any]],
) -> None:
    """Crea un PDF autosufficiente per confrontare due esperimenti."""
    document = SimpleDocTemplate(
        str(output_path), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.45 * cm, bottomMargin=1.45 * cm,
        title="Starlink Simulation - Export metrics", author="Starlink Simulation",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=colors.HexColor("#103653"), spaceAfter=5)
    subtitle = ParagraphStyle("ReportSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=13, textColor=colors.HexColor("#4e6475"), spaceAfter=15)
    heading = ParagraphStyle("ReportHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#103653"), spaceBefore=12, spaceAfter=7)
    body = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=11)
    mode = str(metrics.get("experiment_mode") or "N/A").upper()
    story = [
        Paragraph("Starlink Simulation - Export metriche", title),
        Paragraph(f"Esperimento {mode} - generato {safe_text(metrics.get('generated_at'))}", subtitle),
        Paragraph("Riepilogo dell'esecuzione", heading),
        _metrics_table(metrics), Spacer(1, 12),
        Paragraph("Il report raccoglie le metriche finali della simulazione e puo essere affiancato al report di un altro esperimento per il confronto Hot/Cold.", body),
        Paragraph("Dettaglio migrazioni", heading), _migrations_table(migrations),
    ]
    if migrations:
        story.append(PageBreak())
        for index, migration in enumerate(migrations, start=1):
            if index > 1:
                story.append(PageBreak())
            story.extend(_migration_detail_story(index, migration, heading, body))
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)


def _metrics_table(metrics: dict[str, Any]) -> Table:
    entries = [
        ("Modalita", str(metrics.get("experiment_mode") or "N/A").upper()),
        ("Limite migrazioni", safe_text(metrics.get("migration_limit"))),
        ("Migrazioni completate", safe_text(metrics.get("completed_migration_count"))),
        ("Migrazioni fallite", safe_text(metrics.get("failed_migration_count"))),
        ("Heartbeat ricevuti", safe_text(metrics.get("heartbeat_count"))),
        ("ACK ricevuti", safe_text(metrics.get("ack_count"))),
        ("Tempo simulazione", f"{number(metrics.get('simulation_time_seconds'))} s"),
        ("Downtime totale", f"{number(metrics.get('total_downtime_ms'))} ms"),
        ("Downtime medio", f"{number(metrics.get('average_downtime_ms'))} ms"),
        ("Handover medio", f"{number(metrics.get('average_handover_time_ms'))} ms"),
        ("Allineamento medio", f"{number(metrics.get('average_alignment_wait_ms'))} ms"),
        ("Elezioni controller", safe_text(metrics.get("controller_election_count"))),
        ("Tempo medio elezione", f"{number(metrics.get('average_controller_election_time_ms'))} ms"),
        ("Ultimo controller selezionato", safe_text(metrics.get("last_selected_controller_satellite_id"))),
    ]
    table = Table(entries, colWidths=[6.5 * cm, 10.4 * cm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e9f2f8")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#203646")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("LEADING", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c8d7e1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _migrations_table(migrations: list[dict[str, Any]]) -> Table:
    rows: list[list[str]] = [["#", "Modalita", "Source", "Target", "Stato", "Durata ms", "Downtime ms", "ACK"]]
    for index, migration in enumerate(migrations, start=1):
        details = migration.get("metrics") if isinstance(migration.get("metrics"), dict) else {}
        rows.append([str(index), safe_text(migration.get("mode")).upper(), safe_text(migration.get("source_satellite_id")), safe_text(migration.get("target_satellite_id")), safe_text(migration.get("status")), number(details.get("duration_ms")), number(details.get("downtime_ms")), "SI" if details.get("ack_received") else "NO"])
    if len(rows) == 1:
        rows.append(["-", "-", "-", "-", "Nessuna migrazione", "-", "-", "-"])
    table = Table(rows, colWidths=[0.55 * cm, 1.55 * cm, 2.0 * cm, 2.0 * cm, 2.4 * cm, 2.2 * cm, 2.35 * cm, 1.05 * cm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#103653")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7), ("LEADING", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c8d7e1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f9fc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _migration_detail_story(
    index: int,
    migration: dict[str, Any],
    heading: ParagraphStyle,
    body: ParagraphStyle,
) -> list[Any]:
    """Build one auditable migration card from data saved during execution.

    No timing is calculated in this module.  It merely formats the immutable
    plan recorded by ``MigrationTimingModel`` in the migration metrics.
    """
    metrics = migration.get("metrics") if isinstance(migration.get("metrics"), dict) else {}
    timing = metrics.get("timing_model") if isinstance(metrics.get("timing_model"), dict) else {}
    source = safe_text(migration.get("source_satellite_id"))
    target = safe_text(migration.get("target_satellite_id"))
    mode = safe_text(migration.get("mode")).upper()
    status = safe_text(migration.get("status")).upper()
    story: list[Any] = [
        Paragraph(f"Migrazione #{index} - {mode}", heading),
        _key_value_table([
            ("Source", source), ("Target", target), ("Stato", status),
            ("Durata misurata", f"{number(metrics.get('duration_ms'))} ms"),
            ("Downtime misurato", f"{number(metrics.get('downtime_ms'))} ms"),
        ]),
        Spacer(1, 9),
    ]
    if not timing.get("enabled"):
        story.append(Paragraph("Piano temporale non disponibile per questa migrazione.", body))
        return story

    story.extend([
        Paragraph("Contributi temporali calcolati", heading),
        _key_value_table(_contribution_rows(timing, metrics)),
        Spacer(1, 8),
        Paragraph("Parametri e condizioni che hanno generato il risultato", heading),
        _key_value_table(_input_rows(timing)),
        Spacer(1, 8),
        Paragraph(_explanation(timing, source, target), body),
    ])
    return story


def _contribution_rows(timing: dict[str, Any], metrics: dict[str, Any]) -> list[tuple[str, str]]:
    totals = timing.get("contribution_totals_ms")
    totals = totals if isinstance(totals, dict) else {}
    labels = {
        "network_latency_ms": "Network latency",
        "serialization_time_ms": "Serialization",
        "state_transfer_time_ms": "State transfer",
        "deserialization_time_ms": "Deserialization",
        "startup_delay_ms": "Container startup",
        "synchronization_delay_ms": "Synchronization",
        "processing_delay_ms": "Processing delay",
        "cpu_load_contribution_ms": "CPU load contribution",
        "gaussian_noise_ms": "Random jitter (gaussiano)",
    }
    ordered = [key for key in labels if key in totals]
    ordered.extend(sorted(key for key in totals if key not in labels))
    rows = [(labels.get(key, _humanize_key(key)), f"{number(totals.get(key))} ms") for key in ordered]
    rows.extend([
        ("Migration duration calcolata", f"{number(timing.get('estimated_duration_ms'))} ms"),
        ("Migration duration misurata", f"{number(metrics.get('duration_ms'))} ms"),
    ])
    return rows


def _input_rows(timing: dict[str, Any]) -> list[tuple[str, str]]:
    parameters = timing.get("model_parameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    rows = [
        ("Distanza source-target", f"{number(timing.get('distance_km'))} km"),
        ("CPU source", f"{number(timing.get('source_cpu_load_percent'))} %"),
        ("CPU target", f"{number(timing.get('target_cpu_load_percent'))} %"),
        ("Banda disponibile", f"{number(timing.get('available_bandwidth_mbps'))} Mbps"),
        ("Stato effettivo", _bytes(timing.get("effective_state_bytes"))),
        ("Delta effettivo", _bytes(timing.get("effective_delta_state_bytes"))),
        ("Latenza di rete per operazione", f"{number(timing.get('network_latency_ms'))} ms"),
        ("Seed globale / derivato", f"{safe_text(timing.get('seed'))} / {safe_text(timing.get('derived_seed'))}"),
    ]
    parameter_labels = {
        "base_link_latency_ms": "Latenza base collegamento",
        "distance_latency_ms_per_1000_km": "Incremento latenza per 1000 km",
        "link_processing_ms": "Processing ISL base",
        "serialization_throughput_mbps": "Throughput serializzazione",
        "deserialization_throughput_mbps": "Throughput deserializzazione",
        "cpu_penalty_factor": "Fattore penalita CPU",
        "gaussian_noise_stddev_ms": "Deviazione standard jitter",
        "gaussian_noise_limit_ms": "Limite assoluto jitter",
    }
    for key, label in parameter_labels.items():
        if key in parameters:
            unit = "" if key == "cpu_penalty_factor" else (" Mbps" if "throughput" in key else " ms")
            rows.append((label, f"{number(parameters[key])}{unit}"))
    return rows


def _explanation(timing: dict[str, Any], source: str, target: str) -> str:
    jitter = float(timing.get("gaussian_noise_ms") or 0.0)
    sign = "+" if jitter >= 0 else ""
    return escape(
        f"La durata di {source} verso {target} deriva dai contributi sopra salvati durante il protocollo. "
        f"La distanza era {number(timing.get('distance_km'))} km, la banda disponibile "
        f"{number(timing.get('available_bandwidth_mbps'))} Mbps e il carico CPU del target "
        f"{number(timing.get('target_cpu_load_percent'))}%. Il jitter deterministico associato al seed "
        f"ha contribuito {sign}{number(jitter)} ms. Le differenze con altre migrazioni sono quindi "
        "riconducibili ai rispettivi valori di distanza, banda, stato, CPU e jitter riportati nel PDF."
    )


def _key_value_table(entries: list[tuple[str, str]]) -> Table:
    table = Table(entries, colWidths=[7.1 * cm, 9.8 * cm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf4f8")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#203646")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("LEADING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c8d7e1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _humanize_key(key: str) -> str:
    return key.replace("_ms", "").replace("_", " ").capitalize()


def _bytes(value: Any) -> str:
    return f"{int(value):,} bytes" if isinstance(value, int) and not isinstance(value, bool) else "N/A"


def _footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#c8d7e1"))
    canvas.line(document.leftMargin, 1.05 * cm, A4[0] - document.rightMargin, 1.05 * cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#4e6475"))
    canvas.drawString(document.leftMargin, 0.68 * cm, "Starlink Simulation - report automatico")
    canvas.drawRightString(A4[0] - document.rightMargin, 0.68 * cm, f"Pagina {document.page}")
    canvas.restoreState()


def safe_text(value: Any) -> str:
    return str(value) if value not in {None, ""} else "N/A"


def number(value: Any) -> str:
    return f"{float(value):.3f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "N/A"
