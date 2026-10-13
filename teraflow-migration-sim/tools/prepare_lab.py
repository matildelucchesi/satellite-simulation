"""Freeze fixture and upstream P4 files, pin the downloaded BMv2 image digest."""
import json
import shutil
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.fixture import build
from src.artifacts import describe

fixture = ROOT / "config/fixture.json"
if not fixture.exists(): fixture.write_text(json.dumps(build(ROOT), indent=2)+"\n")
upstream = ROOT / ".reference/build-context/src/tests/p4-sd-fabric-svc-connectivity/p4src"
destination = ROOT / "deploy/p4"
destination.mkdir(exist_ok=True)
for name in ("bmv2.json", "p4info.txt", "_pp.p4"):
    if not (destination / name).exists(): shutil.copyfile(upstream / name, destination / name)
image = json.loads(subprocess.check_output(["docker", "image", "inspect", "p4lang/behavioral-model:latest"], text=True))[0]
digest = next(value for value in image["RepoDigests"] if value.startswith("p4lang/behavioral-model@"))
(ROOT / "deploy/lab.env").write_text("BMV2_IMAGE="+digest+"\n")
manifest = {"schema_version": 1, "bmv2_image": digest, "fixture": describe(fixture),
            "p4_artifacts": [describe(destination / name) for name in ("bmv2.json", "p4info.txt", "_pp.p4")]}
(ROOT / "config/lab-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
print(json.dumps(manifest, indent=2))
