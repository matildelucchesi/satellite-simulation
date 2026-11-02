"""Durable checkpoints and append-only evidence shared by CLI and web jobs."""
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    """Read an atomic snapshot despite short Windows replacement races."""
    for attempt in range(21):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except PermissionError:
            if os.name != 'nt' or attempt == 20: raise
            time.sleep(.025)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        # Windows readers can briefly deny replacement while opening a snapshot.
        # Retry only this sharing/permission race, with a strict one-second cap.
        for attempt in range(21):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 20: raise
                time.sleep(.05)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def append_json(path, value):
    with Path(path).open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+'\n')
        handle.flush(); os.fsync(handle.fileno())
