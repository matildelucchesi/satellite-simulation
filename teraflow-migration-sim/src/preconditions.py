"""Shared calibration prerequisites; full payload hashing only in the worker."""
import json
from pathlib import Path
from .artifacts import verify_artifact


def calibration_inputs(root, *, full):
    from .simulation import engine_fingerprint
    calibration = json.loads((root/'results/calibration.json').read_text())
    if not calibration.get('complete') or calibration.get('engine_fingerprint') != engine_fingerprint(root):
        raise ValueError('Calibration incomplete or implementation changed; recalibrate before admission')
    identifiers = calibration.get('runs', [])
    if len(set(identifiers)) != 6: raise ValueError('Six distinct measured calibrations required')
    for identifier in identifiers:
        evidence = json.loads((root/'results/runs'/identifier/'metadata.json').read_text())
        if not evidence.get('success') or not evidence.get('baseline', {}).get('success'):
            raise ValueError('Calibration contains a run without valid service baseline')
    verify_artifact(calibration['manifest'])
    manifest = json.loads((root/'config/artifact_manifest.json').read_text())
    item = manifest['image_bundle']
    if full: verify_artifact(item)
    else:
        path = Path(item['path'])
        if not path.is_file() or path.stat().st_size != item['bytes']:
            raise ValueError('Image bundle missing or incomplete')
    return calibration, manifest
