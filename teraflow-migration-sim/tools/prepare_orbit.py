import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.orbit import generate
from src.artifacts import verify_artifact

path = ROOT / "artifacts/orbit/replay.npz"
if path.with_suffix(".json").exists():
    metadata = json.loads(path.with_suffix(".json").read_text())
    verify_artifact(metadata["artifact"])
else:
    metadata = generate(ROOT, path)
print(json.dumps(metadata, indent=2))
