"""Start, stop or inspect the single TeraFlow Docker Compose group."""
import argparse
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.deployment import VOLUMES, compose_command

# Kept outside src/: every src/*.py file is part of the calibration engine fingerprint.
UP_ARGUMENTS = ('up', '-d', '--no-build', '--wait', '--wait-timeout', '180')


def create_volumes(run):
    for volume in VOLUMES:
        run(['docker', 'volume', 'create', volume], check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('up', 'stop', 'down', 'status'))
    operation = parser.parse_args().operation
    if operation != 'status' and (ROOT / 'results/jobs/lab.lock').exists():
        parser.error('A laboratory job or recovery checkpoint holds the lock; finish recovery first')
    if operation == 'up':
        create_volumes(subprocess.run)
        arguments = list(UP_ARGUMENTS)
    else:
        arguments = {'stop': ['stop'], 'down': ['down'], 'status': ['ps', '-a']}[operation]
    return subprocess.call(compose_command(*arguments), cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
