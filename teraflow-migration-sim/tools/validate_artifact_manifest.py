#!/usr/bin/env python3
"""Fail closed until all transfer volumes, image digests and timings are measured."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import math
import re

REQUIRED_IMAGE_COMPONENTS = ("context", "device", "pathcomp-frontend", "pathcomp-backend", "service", "nbi")
REQUIRED_STATE_FIELDS = (
    "contexts_bytes", "topologies_bytes", "devices_bytes", "links_bytes",
    "services_connections_policies_bytes", "cold_snapshot_bytes",
    "hot_initial_state_bytes", "hot_final_delta_bytes", "export_format", "sha256",
)
REQUIRED_TIMINGS = (
    "cold_snapshot", "hot_freeze", "hot_delta_apply", "controller_startup",
    "api_restore", "api_verification", "ack_cutover",
)


def validate(doc: dict) -> list[str]:
    errors = []
    if doc.get("schema_version") != 2:
        errors.append("schema_version: bundle accounting requires version 2")
    bundle = doc.get("image_bundle", {})
    if not isinstance(bundle.get("bytes"), int) or isinstance(bundle.get("bytes"), bool) or bundle["bytes"] <= 0:
        errors.append("image_bundle.bytes: positive measured integer required")
    if not re.fullmatch("[0-9a-f]{64}", str(bundle.get("sha256", ""))):
        errors.append("image_bundle.sha256: SHA-256 required")
    if not bundle.get("path") or bundle.get("format") != "docker-save-tar-uncompressed":
        errors.append("image_bundle: frozen path and approved format required")
    controller = doc.get("controller", {})
    if controller.get("source_commit") != "fb8707871eba26806cac7ac373c70b2bb5bd26fc":
        errors.append("controller.source_commit: pin the Release 7 source commit")
    images = controller.get("images", {})
    for component in REQUIRED_IMAGE_COMPONENTS:
        item = images.get(component, {})
        for key in ("image", "digest"):
            if item.get(key) in (None, "", 0):
                errors.append(f"controller.images.{component}.{key}: required measured value missing")
        if item.get("digest") and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(item["digest"])):
            errors.append(f"controller.images.{component}.digest: SHA-256 identity required")
    if not controller.get("dependencies"):
        errors.append("controller.dependencies: list the exact non-component runtime images/services")
    if not controller.get("dependency_policy"):
        errors.append("controller.dependency_policy: specify whether dependencies transfer or are preinstalled")
    state = doc.get("operational_state", {})
    for key in REQUIRED_STATE_FIELDS:
        if state.get(key) in (None, "") or (key != "hot_final_delta_bytes" and state.get(key) == 0):
            errors.append(f"operational_state.{key}: required measured value missing")
        if key.endswith("_bytes"):
            value = state.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"operational_state.{key}: nonnegative measured integer required")
    if not re.fullmatch(r"[0-9a-f]{64}", str(state.get("sha256", ""))):
        errors.append("operational_state.sha256: SHA-256 required")
    timings = doc.get("timing_measurements_s", {})
    for key in REQUIRED_TIMINGS:
        value = timings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            errors.append(f"timing_measurements_s.{key}: required measured value missing")
    resources = doc.get("resources", {})
    for key in ("measured_controller_cpu_cores", "measured_controller_ram_gib", "measured_controller_disk_gib"):
        value = resources.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            errors.append(f"resources.{key}: required measurement missing")
    if not doc.get("measurement_method") or not doc.get("measurement_date_utc"):
        errors.append("measurement_method and measurement_date_utc: record the measurement provenance")
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parents[1] / "config" / "artifact_manifest.template.json"
    issues = validate(json.loads(path.read_text(encoding="utf-8")))
    if issues:
        print(f"NOT READY: {len(issues)} required measurement(s) missing")
        for issue in issues:
            print(f"- {issue}")
        return 2
    print("READY: artifact manifest contains the required pinned and measured inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
