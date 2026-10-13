#!/usr/bin/env python3
"""Freeze one docker-save bundle; re-running verifies instead of rebuilding it."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.artifacts import COMPONENTS, SOURCE_COMMIT, describe, verify_artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "images")
    parser.add_argument("--service-image", default="tfs-migration/service:7.0.0-fb870787")
    parser.add_argument("--device-image", default="tfs-migration/device:7.0.0-fb870787")
    parser.add_argument("--device-patch-manifest", type=Path)
    parser.add_argument("--patch-manifest", type=Path,
                        help="Required provenance for an authorized local Service variant.")
    args = parser.parse_args()
    patch = None
    if args.service_image != "tfs-migration/service:7.0.0-fb870787":
        if args.patch_manifest is None:
            parser.error("A local Service variant requires --patch-manifest")
        patch = json.loads(args.patch_manifest.read_text(encoding="utf-8"))
        if patch.get("upstream_commit") != SOURCE_COMMIT:
            parser.error("Patch provenance does not match the pinned source commit")
        patch = {"manifest": describe(args.patch_manifest), "metadata": patch}
    device_patch = None
    if args.device_image != "tfs-migration/device:7.0.0-fb870787":
        if args.device_patch_manifest is None:
            parser.error("A local Device variant requires --device-patch-manifest")
        metadata = json.loads(args.device_patch_manifest.read_text(encoding="utf-8"))
        if metadata.get("upstream_commit") != SOURCE_COMMIT:
            parser.error("Device patch provenance does not match the pinned source commit")
        device_patch = {"manifest": describe(args.device_patch_manifest), "metadata": metadata}
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "bundle.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        verify_artifact(manifest["image_bundle"])
        if manifest["images"]["service"]["reference"] != args.service_image:
            raise ValueError("Frozen bundle contains a different Service image; choose a new output directory")
        if manifest.get("local_patch") != patch:
            raise ValueError("Frozen bundle patch provenance changed")
        if manifest["images"]["device"]["reference"] != args.device_image or manifest.get("device_patch") != device_patch:
            raise ValueError("Frozen Device bundle/provenance changed; choose a new output directory")
        print(json.dumps(manifest, indent=2))
        return
    references = [f"tfs-migration/{component}:7.0.0-fb870787" for component in COMPONENTS]
    references[COMPONENTS.index("service")] = args.service_image
    references[COMPONENTS.index("device")] = args.device_image
    images = json.loads(subprocess.check_output(["docker", "image", "inspect", *references], text=True))
    bundle = args.output / "teraflow-v7-images.tar"
    temporary = args.output / "teraflow-v7-images.tar.partial"
    subprocess.run(["docker", "save", "-o", str(temporary), *references], check=True)
    temporary.replace(bundle)
    manifest = {"schema_version": 2, "source_commit": SOURCE_COMMIT,
                "format": "docker-save-tar-uncompressed", "created_utc": datetime.now(timezone.utc).isoformat(),
                "docker_version": subprocess.check_output(["docker", "version", "--format", "{{.Server.Version}}"], text=True).strip(),
                "image_bundle": {**describe(bundle), "format": "docker-save-tar-uncompressed"},
                "local_patch": patch,
                "device_patch": device_patch,
                "images": {component: {"reference": reference, "image_id": image["Id"],
                                       "repo_digests": image.get("RepoDigests", [])}
                           for component, reference, image in zip(COMPONENTS, references, images)}}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
