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
    replicas=calibration.get('replicas_per_mode',3 if len(identifiers)==6 else 1)
    if replicas not in (1,3) or len(identifiers)!=2*replicas or len(set(identifiers))!=2*replicas:
        raise ValueError('Distinct successful cold and hot calibrations required')
    modes={'cold':0,'hot':0}
    for identifier in identifiers:
        evidence = json.loads((root/'results/runs'/identifier/'metadata.json').read_text())
        if not evidence.get('success') or not evidence.get('baseline', {}).get('success'):
            raise ValueError('Calibration contains a run without valid service baseline')
        method=evidence.get('method')
        if method not in modes:raise ValueError('Calibration mode missing or invalid')
        modes[method]+=1
    if any(count!=replicas for count in modes.values()):raise ValueError('Both cold and hot calibrations required')
    verify_artifact(calibration['manifest'])
    manifest = json.loads((root/'config/artifact_manifest.json').read_text())
    item = manifest['image_bundle']
    if full: verify_artifact(item)
    else:
        path = Path(item['path'])
        if not path.is_file() or path.stat().st_size != item['bytes']:
            raise ValueError('Image bundle missing or incomplete')
    return calibration, manifest
