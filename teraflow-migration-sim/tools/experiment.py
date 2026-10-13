"""Shared CLI for genuine live operations, calibration and analyses."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).absolute().parents[1]
sys.path.insert(0,str(ROOT))
from src.jobs import JobManager,OPERATIONS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',nargs='?',choices=sorted(OPERATIONS|{'jobs','stop'}))
    parser.add_argument('--worker')
    parser.add_argument('--method',choices=['cold','hot'],default='cold')
    parser.add_argument('--rate-bps',type=int,choices=[100000000,1000000000,10000000000],default=1000000000)
    parser.add_argument('--event-id')
    parser.add_argument('--job-id')
    parser.add_argument('--wait',action='store_true')
    args=parser.parse_args();manager=JobManager(ROOT)
    if args.worker:manager.work(args.worker);return 0
    if args.operation=='jobs':print(json.dumps(manager.list(),indent=2));return 0
    if args.operation=='stop':manager.stop(args.job_id);return 0
    if not args.operation:parser.error('Choose an operation')
    parameters={'method':args.method,'rate_bps':args.rate_bps}
    if args.event_id:parameters['event_id']=args.event_id
    job=manager.start(args.operation,parameters if args.operation=='run' else {})
    print(json.dumps(job,indent=2),flush=True)
    if args.wait:
        previous=None
        while job['status'] in ('queued','running'):
            time.sleep(1);job=manager.get(job['job_id'])
            path=manager.directory/job['job_id']/'events.jsonl'
            if path.exists():
                lines=path.read_text(encoding='utf-8').splitlines()
                if lines and lines[-1]!=previous:print(lines[-1],flush=True);previous=lines[-1]
        print(json.dumps(job,indent=2))
        return 0 if job['status']=='completed' else 2
    return 0


if __name__=='__main__':raise SystemExit(main())
