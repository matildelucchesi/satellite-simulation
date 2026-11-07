"""Command line for laboratory jobs: verification, event experiment, recovery and environment check."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from src.jobs import JobManager, OPERATIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', nargs='?', choices=sorted(OPERATIONS | {'jobs', 'stop'}))
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    parser.add_argument('--job-id', help='Job to stop')
    parser.add_argument('--wait', action='store_true', help='Follow the job until it ends')
    args = parser.parse_args()
    manager = JobManager(ROOT)
    if args.worker:
        manager.work(args.worker)
        return 0
    if args.operation == 'jobs':
        print(json.dumps(manager.list(), indent=2))
        return 0
    if args.operation == 'stop':
        if not args.job_id:
            parser.error('--job-id is required')
        manager.stop(args.job_id)
        return 0
    if not args.operation:
        parser.error('Choose an operation')
    job = manager.start(args.operation, {})
    print(json.dumps(job, indent=2), flush=True)
    if args.wait:
        previous = None
        while job['status'] in ('queued', 'running'):
            time.sleep(1)
            job = manager.get(job['job_id'])
            path = manager.directory / job['job_id'] / 'events.jsonl'
            if path.exists():
                lines = path.read_text(encoding='utf-8').splitlines()
                if lines and lines[-1] != previous:
                    print(lines[-1], flush=True)
                    previous = lines[-1]
        print(json.dumps(job, indent=2))
        return 0 if job['status'] == 'completed' and job.get('application_success') else 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
