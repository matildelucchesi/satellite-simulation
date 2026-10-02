#!/usr/bin/env python3
"""Run a paired hot/cold by throughput matrix for measured workload inputs."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from src.migration_model import Workload, evaluate
from src.resource_model import reference_horizon_s
from tools.validate_artifact_manifest import validate


def load_workload(path: Path) -> Workload:
    document = json.loads(path.read_text(encoding="utf-8"))
    issues = validate(document)
    if issues:
        raise ValueError("Artifact manifest is not ready:\n" + "\n".join(f"- {item}" for item in issues))
    images = document["controller"]["images"]
    state = document["operational_state"]
    times = document["timing_measurements_s"]
    return Workload(
        image_bytes=sum(images[name]["transferred_bytes"] for name in ("context", "device", "pathcomp-frontend", "pathcomp-backend", "service", "nbi")),
        cold_state_bytes=state["cold_snapshot_bytes"],
        hot_initial_state_bytes=state["hot_initial_state_bytes"],
        hot_final_delta_bytes=state["hot_final_delta_bytes"],
        cold_snapshot_s=times["cold_snapshot"],
        hot_freeze_s=times["hot_freeze"],
        hot_delta_apply_s=times["hot_delta_apply"],
        controller_startup_s=times["controller_startup"],
        api_restore_s=times["api_restore"],
        api_verification_s=times["api_verification"],
        ack_cutover_s=times["ack_cutover"],
    )


def main() -> int:
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "config" / "artifact_manifest.json"
    events_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "config" / "selected_events.json"
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "results" / "migration_matrix"
    if not manifest_path.exists():
        print(f"NOT READY: create and measure {manifest_path} from artifact_manifest.template.json")
        return 2
    try:
        workload = load_workload(manifest_path)
    except (ValueError, KeyError, TypeError) as exc:
        print(str(exc))
        return 2
    if not events_path.exists():
        print(f"NOT READY: no trigger-qualified event set at {events_path}")
        return 2
    scenario = json.loads((ROOT / "config" / "scenario.json").read_text(encoding="utf-8"))
    events = json.loads(events_path.read_text(encoding="utf-8"))["events"]
    rates = scenario["fso"]["useful_throughput_bps"]
    alignment = scenario["fso"]["alignment_s"]
    rows = []
    for event in events:
        for method in ("cold", "hot"):
            for rate in rates:
                case = evaluate(workload, method, rate, alignment,
                                event["contact_window_s"], event["deadline_window_s"])
                row = {"event_id": event["event_id"], "percentile_case": event["percentile_case"],
                       "sat_a": event["sat_a"], "sat_b": event["sat_b"], **asdict(case)}
                row["reference_horizon_s"] = reference_horizon_s(
                    evaluate(workload, "cold", rates[0], alignment, 1e12, 1e12).total_operation_s,
                    scenario["controller"]["resource_forecast_horizon_factor"],
                )
                rows.append(row)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_path.with_suffix(".json")
    csv_path = out_path.with_suffix(".csv")
    json_path.write_text(json.dumps({"manifest": str(manifest_path), "events": str(events_path),
                                     "run_count": len(rows), "runs": rows}, indent=2) + "\n",
                         encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["event_id"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"run_count": len(rows), "json": str(json_path), "csv": str(csv_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
